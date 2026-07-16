# Krystal Palace Hôtel Yaoundé — Système PMS-GTC v7.1

> Projet de mémoire de fin de cycle — PyCharm Community 2024 · Python 3.11 · PostgreSQL

📖 **Guide complet de reconstruction (installation + configuration + dépannage) :**
`krystal_palace/docs/GUIDE_RECONSTRUCTION_v7.pdf` — à lire en premier, remplace tous les
anciens guides.

## Nouveautés v7

- **Page 0** : espace client (Réserver / Modifier / Annuler)
- **Annulation intelligente** : gratuite avant J-3, pénalité 20%/jour après, bloquée après J+3
- **Remboursement automatique** Orange Money simulé
- **Modification des dates** uniquement avant la période de pénalité, avec webhook `MODIFICATION` dédié
- **Nouvelle facture PDF** après modification
- **Check-In (vert) / Check-Out (rouge)** dans l'interface admin
- **Réf. chambre + Réf. climatisation** gérées par l'administrateur
- **PostgreSQL** comme base de données (remplacement de SQLite)

## Nouveautés v7.1 (corrections)

- Imports relatifs corrigés dans `gateway/` (la passerelle ne démarrait plus en v7.0)
- `.env` fourni + chargement automatique (`python-dotenv` était présent mais jamais appelé)
- `pyproject.toml`, `Procfile`, `render.yaml` ajoutés
- `api_tests.http` complété (clients admin, Page 0, tests directs de la Gateway)
- Guide de reconstruction unique et à jour dans `docs/`
- Détail complet des corrections : section 15 du guide de reconstruction

## Structure du projet

```
krystal_palace_pycharm/
├── .idea/
│   └── runConfigurations/
│       ├── PMS_Serveur_8000.xml     ← Config Run PyCharm serveur PMS
│       └── Gateway_BACnet_8001.xml  ← Config Run PyCharm gateway
├── .gitignore
├── README.md
├── pyproject.toml                   ← Déclare krystal_palace comme package installable
├── Procfile                         ← Déploiement (Render/Railway/Heroku)
├── render.yaml                      ← Blueprint de déploiement Render
└── krystal_palace/
    ├── main.py                  ← Serveur PMS FastAPI (port 8000)
    ├── requirements.txt         ← Bibliothèques Python à installer
    ├── .env                     ← Variables d'environnement (secrets, non versionné)
    ├── .env.example             ← Modèle versionnable de .env
    ├── __init__.py
    ├── templates/
    │   ├── client.html          ← Interface client (Page 0 + wizard 5 étapes)
    │   └── admin.html           ← Dashboard admin (Check-In vert / Check-Out rouge)
    ├── gateway/
    │   ├── main.py              ← Passerelle BACnet (port 8001)
    │   ├── bacnet_client.py     ← Client bacpypes3
    │   ├── scheduler.py         ← APScheduler préconditionning
    │   ├── config.py            ← Mapping chambres BACnet/YABE, lit .env
    │   ├── requirements_gateway.txt
    │   └── __init__.py
    ├── database/
    │   └── create_database_postgresql.sql
    └── docs/
        ├── GUIDE_RECONSTRUCTION_v7.pdf   ← Guide complet (lire en premier)
        ├── GUIDE_RECONSTRUCTION_v7.md    ← Même guide, source Markdown
        ├── diagrammes_plantuml.puml
        ├── architecture_drawio.xml
        └── uml_*.xml
```

## Démarrage rapide PyCharm Community 2024

### 1. Ouvrir le projet
```
File → Open → sélectionner le dossier krystal_palace_pycharm/
```

### 2. Créer l'environnement virtuel
```
File → Settings → Project → Python Interpreter → Add Interpreter → Virtualenv
Base interpreter : Python 3.11
Location : krystal_palace_pycharm/venv
```

### 3. Installer les bibliothèques
Dans le terminal PyCharm (Alt+F12) :
```bash
pip install -r krystal_palace/requirements.txt
pip install -r krystal_palace/gateway/requirements_gateway.txt
pip install -e .
```

### 4. Configurer PostgreSQL
- Installer PostgreSQL 15+ et pgAdmin 4
- Ouvrir pgAdmin → Query Tool → exécuter :
  `krystal_palace/database/create_database_postgresql.sql`
- Vérifier que `.env` contient le bon `DATABASE_URL`

### 5. Configurer YABE
- Lancer YABE DemoServer
- Créer Device ID 1001 avec objets AO/BO/MV (instances 1 à 11)

### 6. Lancer les serveurs
Ordre obligatoire :
1. YABE → 2. Gateway (port 8001) → 3. PMS (port 8000)

Via PyCharm : Run → sélectionner la configuration → ▶

Ou terminal :
```bash
# Terminal 1 — Gateway BACnet
uvicorn krystal_palace.gateway.main:app --host 127.0.0.1 --port 8001 --reload

# Terminal 2 — Serveur PMS
uvicorn krystal_palace.main:app --host 127.0.0.1 --port 8000 --reload
```

### 7. Accès
| Page | URL |
|---|---|
| Interface client | http://127.0.0.1:8000 |
| Dashboard admin | http://127.0.0.1:8000/admin |
| Documentation API | http://127.0.0.1:8000/docs |
| Santé serveur | http://127.0.0.1:8000/api/health |

## Règles métier — Annulation

| Situation | Pénalité | Remboursement |
|---|---|---|
| Avant J-3 (arrivée) | 0% | 100% |
| J-2 (1 jour dépassé) | 20% | 80% |
| J-1 (2 jours dépassés) | 40% | 60% |
| Jour J (3 jours dépassés) | 60% | 40% |
| J+1 (4 jours dépassés) | 80% | 20% |
| J+2 (5 jours dépassés) | 100% | 0% |
| Après J+3 | **Bloquée** | — |

## Identifiants par défaut

| Champ | Valeur |
|---|---|
| Admin login | admin |
| Admin password | krystal2024 |
| DB utilisateur | krystal_user |
| DB mot de passe | krystal2024 |
| Orange Money réception | +237 655 448 731 |
