# TED-APP-COBOMI — Station de Traitement des Eaux

Application Flask de supervision et de saisie des mesures de la station de traitement des eaux COBOMI.

## Structure

```text
TED-APP-COBOMI-GITHUB-FINAL/
├── app.py
├── requirements.txt
├── Procfile
├── README.md
├── .gitignore
├── static/
│   ├── style.css
│   └── synoptique_station.png
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── measure.html
    ├── history.html
    ├── alerts.html
    ├── reports.html
    ├── settings.html
    └── users.html
```

## Render

Build Command:
```bash
pip install -r requirements.txt
```

Start Command:
```bash
gunicorn app:app
```

Environment variables:
```text
DATABASE_URL = Internal Database URL de PostgreSQL Render
SECRET_KEY = une valeur secrète
```

L'application crée automatiquement les tables nécessaires.

## GitHub

Les fichiers doivent être placés directement à la racine du dépôt, et non dans un sous-dossier supplémentaire.

## Réinitialisation automatique du schéma PostgreSQL

Au démarrage, l'application vérifie les colonnes nécessaires des tables
`measurement_point`, `measurement` et `alert`. Si une ancienne version de
la base est détectée, les trois tables de l'application sont recréées.
Le service PostgreSQL lui-même n'est pas supprimé.
