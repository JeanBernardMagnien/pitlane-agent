# PitLane Agent

Agent léger installé sur chaque serveur Windows de jeu Assetto Corsa EVO.
Expose une API REST + WebSocket consommée par le hub PitLane (Symfony).

## Prérequis

- Windows Server 2025
- Droits administrateur
- Python 3+ (installé automatiquement par les scripts si absent)

## Installation

### Scénario 1 — AC EVO déjà installé

Télécharger et exécuter `setup-agent.ps1` en tant qu'administrateur.
Le script détecte automatiquement AC EVO, installe l'agent et configure tout.

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\installers\setup-agent.ps1
```

### Scénario 2 — Serveur vierge (AC EVO pas encore installé)

Télécharger et exécuter `setup-full.ps1` en tant qu'administrateur.
Le script installe steamcmd, télécharge AC EVO via Steam, puis installe l'agent.

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\installers\setup-full.ps1
```

Les deux scripts installent automatiquement :
- Python 3 (via winget si absent)
- Les dépendances Python (`requirements.txt`)
- La tâche planifiée Windows (`PitLaneAgent`) au démarrage
- Les règles firewall (ports 8181, 9700, 8081)
- Le `config.yml` pré-rempli avec les chemins détectés

## Structure du dépôt

```
pitlane-agent/
├── agent/                        ← code Python de l'agent
│   ├── app.py
│   ├── server_manager.py
│   ├── encode_config.py
│   ├── log_streamer.py
│   ├── requirements.txt
│   └── config.example.yml
├── installers/
│   ├── setup-agent.ps1           ← install si AC EVO déjà présent
│   └── setup-full.ps1            ← install complète depuis zéro
├── .github/
│   └── workflows/
│       └── release.yml             ← publie agent.zip sur chaque tag v*
└── README.md
```

## Configuration

Après installation, deux champs sont à renseigner dans `agent/config.yml` :

| Clé | Description |
|---|---|
| `http.base_url` | URL publique du serveur |
| `auth.jwt_secret` | Secret partagé avec le hub Symfony |

Les chemins du jeu et Steam sont remplis automatiquement par les scripts.

## Structure des logs

```
logs/
├── log_server1_2026-05-06_19-00-00.log
├── log_server1_2026-05-06_21-00-00.log
└── steam_update.log              ← sortie steamcmd lors des mises à jour
```

## API REST

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/system` | Infos système (CPU, instances max) |
| GET | `/api/instances` | Liste toutes les instances avec statut |
| POST | `/api/instances` | Créer une instance |
| PUT | `/api/instances/{id}` | Modifier une instance |
| DELETE | `/api/instances/{id}` | Supprimer une instance |
| GET | `/api/instances/{id}/status` | Statut détaillé (RAM, uptime, pilotes) |
| POST | `/api/instances/{id}/start` | Démarrer une instance |
| POST | `/api/instances/{id}/stop` | Arrêter une instance |
| POST | `/api/instances/{id}/restart` | Redémarrer une instance |
| POST | `/api/instances/{id}/switch` | Charger une config et redémarrer |
| GET | `/api/instances/{id}/logs` | Dernières lignes de log |
| WS | `/api/instances/{id}/logs/stream` | Logs en temps réel |
| GET | `/api/configs` | Liste les configs disponibles |
| POST | `/api/configs` | Créer une config |
| PUT | `/api/configs/{filename}` | Modifier une config |
| DELETE | `/api/configs/{filename}` | Supprimer une config |
| **POST** | **`/api/steam/update`** | **Déclenche la mise à jour AC EVO via steamcmd** |
| **GET** | **`/api/steam/update/logs`** | **Logs steamcmd (100 dernières lignes + finished)** |
| **GET** | **`/api/steam/update-check`** | **Compare buildid local vs Steam (sans auth Steam)** |

### `/api/steam/update` — détail

Body JSON requis : `{ "steam_username": "...", "steam_password": "..." }`

Les credentials ne sont jamais écrits sur le disque.
Réponses : `202 { status, pid }` | `409` (instances en cours) | `503` (steamcmd non configuré)

### `/api/steam/update-check` — détail

Réponse : `{ up_to_date, local_build, remote_build, update_available }`

Appelle l'API publique Steam — aucune authentification requise.

## Mise à jour d'AC EVO

### Via le hub (recommandé)

Depuis le dashboard serveur, cliquer sur "Mettre à jour AC EVO".
Les credentials Steam sont configurés une seule fois dans le hub (`.env`).

### Manuellement

```powershell
# Arrêter les instances depuis le hub, puis :
steamcmd.exe +login <compte_steam> <pass_steam> +force_install_dir <chemin_acevo> +app_update 4564210 validate +quit
```

## Authentification

Toutes les routes requièrent un token JWT dans le header :

```
Authorization: Bearer <token>
```

Le secret JWT est partagé avec le hub Symfony (`auth.jwt_secret` dans `config.yml`).
