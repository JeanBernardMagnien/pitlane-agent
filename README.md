# PitLane Agent

Agent léger installé sur chaque serveur Windows de jeu Assetto Corsa EVO.

L'agent n'est plus propriétaire des instances métier. Le hub PitLane possède les serveurs, les instances, les ports et les presets. L'agent exécute les commandes reçues, prépare le réseau local, lance les processus AC EVO et expose les logs.

## Installation

### AC EVO déjà installé

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\installers\setup-agent.ps1
```

### Serveur vierge

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\installers\setup-full.ps1
```

Les scripts installent :

- Python 3 si absent
- les dépendances Python
- la tâche planifiée Windows `PitLaneAgent`
- la règle firewall de l'API agent `TCP/8181`
- le fichier `config.yml` avec les chemins détectés

Les ports des instances AC EVO ne sont plus ouverts à l'installation. Ils sont gérés par le hub lors de la création, modification ou suppression d'une instance.

## Configuration

Après installation, le fichier principal est :

```text
agent/config.yml
```

Il contient les chemins machine/runtime :

- URL publique de l'agent
- secret JWT partagé
- chemin d'installation AC EVO
- chemin global des configs
- chemin global des résultats
- chemin global des logs
- chemin SteamCMD
- chemin appmanifest

Il ne contient plus de section `instances`.

## Responsabilités

### Hub

Le hub est propriétaire de :

- la liste des serveurs
- la liste des instances
- les ports TCP/UDP/HTTP
- les presets/sessions
- les décisions de création/modification/suppression
- l'état serveur/instance affiché dans l'interface

### Agent

L'agent est responsable de :

- exposer une API locale sécurisée
- ouvrir/fermer les ports demandés par le hub
- lancer/arrêter/redémarrer un processus AC EVO
- appliquer les chemins runtime nécessaires
- exposer les logs
- exécuter SteamCMD pour les mises à jour/vérifications

## Push agent vers hub

L'agent pousse automatiquement son état runtime vers un ou plusieurs hubs.

Chaque hub configuré reçoit :

- heartbeat agent
- état runtime des instances lancées
- infos techniques serveur : CPU, RAM, processus, build local, erreurs
- persistance côté hub
- diffusion Mercure vers l'interface

La configuration se fait via `hubs` dans `config.yml`, avec `runtime_report_endpoint`, `runtime_report_interval` et éventuellement `agent_token`.

L'ancien push basé sur `config.yml.instances` est désactivé. Le hub ne doit plus interroger l'agent pour récupérer l'état serveur ou instance.

## API REST

Toutes les routes agent requièrent :

```text
Authorization: Bearer <token>
```

### Système

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/system` | Infos système ponctuelles |

### Provisioning technique instance

Ces routes ne créent pas d'instance métier dans l'agent. Elles appliquent uniquement les effets techniques demandés par le hub.

| Méthode | Route | Description |
|---|---|---|
| POST | `/api/instances/{id}/prepare` | Prépare les ports firewall |
| PUT | `/api/instances/{id}/network` | Remplace les anciennes règles firewall par les nouvelles |
| POST | `/api/instances/{id}/cleanup` | Nettoie les règles firewall et refuse si l'instance tourne |

### Commandes runtime instance

Le hub fournit l'instance complète dans le payload quand l'agent doit agir.

| Méthode | Route | Description |
|---|---|---|
| POST | `/api/instances/{id}/launch` | Lance une instance avec une config runtime fournie |
| POST | `/api/instances/{id}/start` | Démarre une instance avec la dernière config runtime courante |
| POST | `/api/instances/{id}/stop` | Arrête une instance |
| POST | `/api/instances/{id}/restart` | Redémarre une instance avec une config runtime fournie |
| GET | `/api/instances/{id}/logs` | Dernières lignes de log |
| WS | `/api/instances/{id}/logs/stream` | Logs en temps réel |

Les anciennes routes de lecture/synchro/CRUD instance ne sont plus exposées :

| Méthode | Route |
|---|---|
| GET | `/api/instances` |
| POST | `/api/instances` |
| GET | `/api/instances/{id}` |
| PUT | `/api/instances/{id}` |
| DELETE | `/api/instances/{id}` |
| GET | `/api/instances/{id}/status` |
| POST | `/api/instances/{id}/switch` |

### Configs

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/configs` | Liste les configs disponibles |
| POST | `/api/configs` | Crée une config |
| PUT | `/api/configs/{filename}` | Modifie une config |
| DELETE | `/api/configs/{filename}` | Supprime une config |

### Steam

| Méthode | Route | Description |
|---|---|---|
| POST | `/api/steam/update` | Déclenche la mise à jour AC EVO via SteamCMD |
| GET | `/api/steam/update/logs` | Logs SteamCMD |
| POST | `/api/steam/update-check` | Compare build local et build distant |

## Logs

```text
logs/
├── log_<instance_id>_YYYY-MM-DD_HH-MM-SS.log
└── steam_update.log
```
