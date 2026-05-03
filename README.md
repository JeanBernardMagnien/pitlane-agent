# PitLane Server Agent

Agent léger installé sur chaque serveur Windows de jeu Assetto Corsa EVO.
Expose une API REST + WebSocket consommée par le hub PitLane (Symfony).

## Prérequis

- Windows Server
- Python 3.12+
- Assetto Corsa EVO Server installé dans `C:\ACE\`

## Installation

```powershell
# 1. Cloner le repo
git clone https://github.com/ton-user/pitlane.git
cd pitlane/pitlane-server-agent

# 2. Lancer le script d'installation
.\install.ps1

# 3. Éditer la configuration
notepad config.yml
```

## Configuration

Copier `config.example.yml` en `config.yml` et renseigner :

| Clé | Description |
|---|---|
| `http.port` | Port de l'agent Flask (défaut : 8182) |
| `http.base_url` | URL publique du serveur |
| `game.install_path` | Dossier d'installation AC EVO |
| `auth.jwt_secret` | Secret partagé avec le hub Symfony |

## API REST

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/instances` | Liste toutes les instances |
| GET | `/api/instances/{id}/status` | Statut, RAM, uptime |
| POST | `/api/instances/{id}/start` | Démarrer une instance |
| POST | `/api/instances/{id}/stop` | Arrêter une instance |
| POST | `/api/instances/{id}/restart` | Redémarrer une instance |
| POST | `/api/instances/{id}/switch` | Charger une config et redémarrer |
| GET | `/api/configs` | Liste les configs disponibles |
| POST | `/api/configs` | Créer une config |
| PUT | `/api/configs/{filename}` | Modifier une config |
| DELETE | `/api/configs/{filename}` | Supprimer une config |
| GET | `/api/instances/{id}/logs` | Dernières lignes de log |
| WS | `/api/instances/{id}/logs/stream` | Logs en temps réel |

## Authentification

Toutes les routes requièrent un token JWT dans le header :
Authorization: Bearer <token>
Le secret JWT est partagé avec le hub Symfony (`auth.jwt_secret` dans `config.yml`).

## Structure

pitlane-server-agent/
├── app.py               ← Flask — routes API REST
├── server_manager.py    ← gestion des process Windows
├── encode_config.py     ← encodage JSON → base64 AC EVO
├── log_streamer.py      ← WebSocket logs temps réel
├── config.yml           ← configuration (ignoré par Git)
├── config.example.yml   ← exemple de configuration
├── requirements.txt     ← dépendances Python
└── install.ps1          ← installation automatique

## Déploiement sur un nouveau serveur

```powershell
# 1. Cloner le repo sur le serveur Windows
# 2. Modifier config.yml
# 3. Lancer install.ps1
# 4. Ajouter le serveur dans le panel admin du hub PitLane
```