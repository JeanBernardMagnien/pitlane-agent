# PitLane Server Agent

Agent léger installé sur chaque serveur Windows de jeu Assetto Corsa EVO.
Expose une API REST + WebSocket consommée par le hub PitLane (Symfony).

## Prérequis

- Windows Server 2025
- Assetto Corsa EVO Dedicated Server installé via SteamCMD (App ID : 4564210)
- Python 3+ (installé automatiquement par `install.ps1` si absent)

## Installation

```powershell
# 1. Se placer dans le dossier d'installation d'AC EVO
cd "C:\SteamCMD\steamapps\common\Assetto Corsa EVO Dedicated Server"

# 2. Cloner le repo
git clone https://github.com/JeanBernardMagnien/pitlane-server-agent.git

# 3. Lancer le script d'installation
cd pitlane-server-agent
.\install.ps1
```

`install.ps1` installe automatiquement :
- Python 3 (via winget si absent)
- Les dépendances Python (`requirements.txt`)
- La tâche planifiée Windows (`PitLaneAgent`) au démarrage
- Les règles firewall pour le port de l'agent
- Les dossiers `configs`, `Results` et `logs`
- Le `config.yml` pré-rempli avec les chemins détectés automatiquement

## Configuration

Après installation, seuls deux champs sont à renseigner dans `config.yml` :

| Clé | Description |
|---|---|
| `http.base_url` | URL publique du serveur (ex: `https://server.pitlane-evo.fr`) |
| `auth.jwt_secret` | Secret partagé avec le hub Symfony |

Les chemins du jeu sont remplis automatiquement par `install.ps1`.

## Structure des logs

Chaque instance génère son propre fichier de log horodaté :
```
logs/
├── log_server1_2026-05-06_19-00-00.log
├── log_server1_2026-05-06_21-00-00.log
└── log_server2_2026-05-06_19-00-00.log
```

## API REST

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/system` | Infos système (CPU, RAM, instances max) |
| GET | `/api/instances` | Liste toutes les instances avec statut |
| POST | `/api/instances` | Créer une instance |
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

## Authentification

Toutes les routes requièrent un token JWT dans le header :

Authorization: Bearer <token>

Le secret JWT est partagé avec le hub Symfony (`auth.jwt_secret` dans `config.yml`).

## Structure du projet
```
pitlane-server-agent/
├── app.py               ← Flask — routes API REST
├── server_manager.py    ← gestion des process Windows
├── encode_config.py     ← encodage JSON → base64 AC EVO
├── log_streamer.py      ← WebSocket logs temps réel
├── config.yml           ← configuration (ignoré par Git)
├── config.example.yml   ← template de configuration
├── requirements.txt     ← dépendances Python
└── install.ps1          ← installation automatique (se supprime après)
```

## Mise à jour d'AC EVO

```powershell
# Arrêter les instances depuis le hub, puis :
steamcmd.exe +login <compte_steam> <pass_steam> +app_update 4564210 validate +quit
```
