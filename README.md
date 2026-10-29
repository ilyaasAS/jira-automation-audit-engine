# Jira Automation Governance & Audit Engine

Outil CLI d'audit, de cartographie et de contrôle qualité des règles Jira Automation multi-projets (+8 500 exécutions auditées).

## 0. Se positionner dans le bon emplacement

Ouvrir un terminal dans le dossier du projet (au même niveau que le fichier README.md).

## 1. Création et activation de l'environnement virtuel

### Sur Windows :
python -m venv venv
venv\Scripts\activate

### Sur macOS et Linux :
python3 -m venv venv
source venv/bin/activate

## 2. Installation des dépendances 
pip install -r requirements.txt

## 3. Configuration des accès
cp .env.example .env

Renseigner JIRA_EMAIL et JIRA_API_TOKEN dans le fichier .env.

## 4. Lancer le projet

### Mode Démo (audit local via fixture) :
python3 main.py --project CFIT --rules-file tests/fixtures/sample_rules.json

### Mode Analyse Projet Réel :
python3 main.py --project CFIT

### Lancer tous les projets configurés :
python3 main.py

Les rapports sont générés dans le dossier output/ (.xlsx, .html, .json).

## 5. Lancer les tests unitaires (37 tests)

### Sur Windows :
python -m pytest -v

### Sur macOS et Linux :
python3 -m pytest -v

## 6. Quitter l'environnement
deactivate