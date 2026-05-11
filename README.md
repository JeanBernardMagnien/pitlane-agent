# PitLane Agent

Agent léger installé sur chaque serveur Windows de jeu Assetto Corsa EVO.

Il expose une API REST + WebSocket consommée par le hub PitLane, et pousse aussi l'état runtime des instances vers le hub.

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
│   ├── app.py                    ← bootstrap Flask + routes + monitor
│   ├── config.template.yml       ← template utilisé par les installateurs
│   ├── core/                     ← config, auth, helpers communs
│   ├── routes/                   ← endpoints REST/WebSocket
│   ├── services/                 ← logique métier/runtime
│   └── requirements.txt
├── installers/
│   ├── setup-agent.ps1           ← install si AC EVO déjà présent
│   └── setup-full.ps1            ← install complète depuis zéro
├── tools/
│   └── uninstaller.ps1
├── .github/
│   └── workflows/
│       └── release.yml           ← publie agent.zip sur chaque tag v*
└── README.md
```

## Configuration

Après installation, le fichier principal est :

```text
agent/config.yml
```

Champs importants :

| Clé | Description |
|---|---|
| `http.base_url` | URL publique de l'agent serveur |
| `auth.jwt_secret` | Secret partagé entre le hub et l'agent |
| `hub.base_url` | URL publique du hub PitLane |
| `hub.state_endpoint` | Endpoint hub recevant les états d'instances |
| `hub.monitor_interval` | Intervalle local de surveillance en secondes |

Exemple :

```yaml
http:
  host: 0.0.0.0
  port: 8181
  base_url: "http://IP_DU_SERVEUR:8181"

auth:
  jwt_secret: "TOKEN_UNIQUE_DU_SERVEUR"
  jwt_algorithm: HS256

hub:
  base_url: https://pitlane-evo.fr
  state_endpoint: /api/agent/instances/state
  monitor_interval: 5
```

Le même `auth.jwt_secret` est utilisé dans les deux sens :

```text
Hub → Agent : piloter les instances
Agent → Hub : pousser l'état runtime des instances
```

## Push d'état vers le hub

L'agent surveille localement les instances et construit un snapshot runtime.
Lorsqu'un changement est détecté, il envoie l'état au hub :

```text
POST {hub.base_url}{hub.state_endpoint}
Authorization: Bearer <auth.jwt_secret>
```

Payload envoyé :

```json
{
  "instances": [
    {
      "id": "server1",
      "name": "Serveur 1",
      "status": "online",
      "pid": 1234,
      "ram_mb": 120.7,
      "connected_drivers": 0,
      "active_config": "practice_nord.json",
      "active_config_loaded_at": "2026-05-11T08:17:56Z",
      "tcp_port": 9700,
      "http_port": 8081,
      "started_at": "2026-05-11T08:17:56Z"
    }
  ]
}
```

Ce push réduit la dépendance au polling côté hub pour l'affichage des instances.
Les actions `start`, `stop`, `restart`, `switch`, etc. passent encore par l'API agent.

## Structure des logs

```
logs/
├── log_server1_2026-05-06_19-00-00.log
├── log_server1_2026-05-06_21-00-00.log
└── steam_update.log              ← sortie steamcmd lors des mises à jour
```

## API REST

Toutes les routes ci-dessous sont exposées par l'agent et consommées par le hub.

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
| POST | `/api/steam/update` | Déclenche la mise à jour AC EVO via steamcmd |
| GET | `/api/steam/update/logs` | Logs steamcmd + état de fin |
| POST | `/api/steam/update-check` | Compare buildid local vs Steam |

### `/api/steam/update` — détail

Body JSON requis :

```json
{ "steam_username": "...", "steam_password": "..." }
```

Les credentials ne sont jamais écrits sur le disque.
Réponses : `202 { status, pid }` | `409` (instances en cours) | `503` (steamcmd non configuré)

### `/api/steam/update/logs` — détail

Réponse :

```json
{
  "lines": [],
  "finished": false,
  "running": true,
  "success": false,
  "exit_code": null,
  "pid": 1234
}
```

SteamCMD peut bufferiser sa sortie : les logs peuvent apparaître surtout en fin de mise à jour.

### `/api/steam/update-check` — détail

Body JSON requis :

```json
{ "steam_username": "...", "steam_password": "..." }
```

Réponse :

```json
{ "up_to_date": true, "local_build": 123, "remote_build": 123, "update_available": false }
```

## Mise à jour d'AC EVO

### Via le hub (recommandé)

Depuis le dashboard serveur, cliquer sur "Mettre à jour AC EVO".
Les credentials Steam sont transmis à l'agent le temps de la commande et ne sont pas écrits sur le disque.

### Manuellement

```powershell
# Arrêter les instances depuis le hub, puis :
steamcmd.exe +login <compte_steam> <pass_steam> +force_install_dir <chemin_acevo> +app_update 4564210 validate +quit
```

## Authentification

Toutes les routes agent requièrent un token dans le header :

```text
Authorization: Bearer <token>
```

Le secret partagé est `auth.jwt_secret` dans `config.yml`.
Il sert aussi à authentifier le push de l'agent vers le hub.
