
import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cobomi-water-treatment")
database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///water_treatment.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

POINTS = [
    ("PT-01", "Eau de ville"),
    ("PT-02", "Eau de forage"),
    ("PT-03", "Sortie filtres à sable"),
    ("PT-04", "Sortie bassin eau chlorée"),
    ("PT-05", "Entrée filtres à charbon"),
    ("PT-06", "Sortie filtres à charbon"),
    ("PT-07", "Sortie filtres à cartouches"),
    ("PT-08", "Sortie osmose inverse"),
    ("PT-09", "Sortie lampes UV"),
]

PARAMETERS = [
    ("pH", "pH"),
    ("Température", "°C"),
    ("Conductivité", "µS/cm"),
    ("Turbidité", "NTU"),
    ("Chlore", "mg/L"),
    ("Pression", "bar"),
    ("Débit", "m³/h"),
    ("TDS", "mg/L"),
]

class MeasurementPoint(db.Model):
    __tablename__ = "measurement_point"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)

class Measurement(db.Model):
    __tablename__ = "measurement"
    id = db.Column(db.Integer, primary_key=True)
    point_id = db.Column(db.Integer, db.ForeignKey("measurement_point.id"), nullable=False)
    parameter = db.Column(db.String(80), nullable=False)
    value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(30), nullable=False)
    measured_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    operator = db.Column(db.String(120), default="Opérateur", nullable=False)
    compliant = db.Column(db.Boolean, default=True, nullable=False)
    point = db.relationship("MeasurementPoint", backref=db.backref("measurements", lazy=True))

class Alert(db.Model):
    __tablename__ = "alert"
    id = db.Column(db.Integer, primary_key=True)
    point_id = db.Column(db.Integer, db.ForeignKey("measurement_point.id"), nullable=False)
    parameter = db.Column(db.String(80), nullable=False)
    value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(30), nullable=False)
    message = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed = db.Column(db.Boolean, default=False, nullable=False)
    point = db.relationship("MeasurementPoint")

def init_db():
    with app.app_context():
        db.create_all()

        # Detect old V2/V3 PostgreSQL schemas and rebuild only the
        # application's three tables when required columns are missing.
        # This fixes errors such as:
        #   column measurement_point.code does not exist
        #   column alert.value does not exist
        if database_url.startswith("postgresql"):
            try:
                required = {
                    "measurement_point": {"id", "code", "name"},
                    "measurement": {"id", "point_id", "parameter", "value", "unit", "measured_at", "operator", "compliant"},
                    "alert": {"id", "point_id", "parameter", "value", "unit", "message", "created_at", "closed"},
                }

                reset_required = False
                for table_name, required_columns in required.items():
                    rows = db.session.execute(text("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name=:table_name
                    """), {"table_name": table_name}).fetchall()
                    existing = {r[0] for r in rows}

                    # If the table exists but its schema is incomplete, reset
                    # the app tables so db.create_all() can recreate them.
                    if existing and not required_columns.issubset(existing):
                        reset_required = True
                        break

                if reset_required:
                    db.session.execute(text("DROP TABLE IF EXISTS alert CASCADE"))
                    db.session.execute(text("DROP TABLE IF EXISTS measurement CASCADE"))
                    db.session.execute(text("DROP TABLE IF EXISTS measurement_point CASCADE"))
                    db.session.commit()
                    db.create_all()

            except Exception:
                db.session.rollback()

        if MeasurementPoint.query.count() == 0:
            db.session.add_all([
                MeasurementPoint(code=code, name=name)
                for code, name in POINTS
            ])
            db.session.commit()

def today_measurements(point):
    return {
        m.parameter: m
        for m in point.measurements
        if m.measured_at.date() == date.today()
    }

def point_status(point):
    ms = today_measurements(point)
    if not ms:
        return "red"
    if any(not m.compliant for m in ms.values()):
        return "red"
    return "green"

def global_status(points):
    return all(point_status(p) == "green" for p in points)

@app.context_processor
def globals_for_templates():
    return {"now": datetime.now(), "parameters": PARAMETERS}

@app.route("/")
def dashboard():
    points = MeasurementPoint.query.order_by(MeasurementPoint.id).all()
    recent = Measurement.query.order_by(Measurement.measured_at.desc()).limit(6).all()
    recent_alerts = Alert.query.order_by(Alert.created_at.desc()).limit(5).all()
    statuses = {p.code: point_status(p) for p in points}
    missing = {p.code: not bool(today_measurements(p)) for p in points}
    return render_template(
        "dashboard.html",
        points=points,
        statuses=statuses,
        missing=missing,
        recent=recent,
        recent_alerts=recent_alerts,
        station_ok=global_status(points)
    )

@app.route("/measure/<code>", methods=["GET", "POST"])
def measure(code):
    point = MeasurementPoint.query.filter_by(code=code).first_or_404()
    if request.method == "POST":
        operator = request.form.get("operator", "Opérateur").strip() or "Opérateur"
        for parameter, unit in PARAMETERS:
            raw = request.form.get(parameter)
            if raw is None or raw.strip() == "":
                continue
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                flash(f"Valeur invalide : {parameter}", "error")
                continue

            # General placeholder conformity rule.
            compliant = True
            if parameter == "TDS" and value > 2000:
                compliant = False
            if parameter == "Chlore" and (value < 0.1 or value > 2):
                compliant = False

            db.session.add(Measurement(
                point_id=point.id, parameter=parameter, value=value,
                unit=unit, operator=operator, compliant=compliant
            ))
            if not compliant:
                db.session.add(Alert(
                    point_id=point.id, parameter=parameter, value=value,
                    unit=unit, message=f"{parameter} hors limite"
                ))
        db.session.commit()
        flash("Mesures enregistrées avec succès.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "measure.html",
        point=point,
        values=today_measurements(point)
    )

@app.route("/history")
def history():
    measurements = Measurement.query.order_by(Measurement.measured_at.desc()).limit(500).all()
    return render_template("history.html", measurements=measurements)

@app.route("/alerts")
def alerts():
    alerts_list = Alert.query.order_by(Alert.created_at.desc()).limit(300).all()
    return render_template("alerts.html", alerts=alerts_list)

@app.post("/alerts/<int:alert_id>/close")
def close_alert(alert_id):
    item = Alert.query.get_or_404(alert_id)
    item.closed = True
    db.session.commit()
    return redirect(url_for("alerts"))

@app.route("/reports")
def reports():
    return render_template("reports.html")

@app.route("/settings")
def settings():
    return render_template("settings.html")

@app.route("/users")
def users():
    return render_template("users.html")

@app.get("/api/status")
def api_status():
    points = MeasurementPoint.query.order_by(MeasurementPoint.id).all()
    return jsonify([
        {"code": p.code, "name": p.name, "status": point_status(p)}
        for p in points
    ])

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
