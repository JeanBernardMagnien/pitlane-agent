# PitLane Agent

Agent léger installé sur chaque serveur Windows dédié Assetto Corsa EVO.

Il s'enregistre auprès du hub PitLane via WebSocket, exécute les commandes reçues (démarrage/arrêt d'instances, gestion du firewall, mises à jour SteamCMD) et remonte en temps réel les métriques serveur et l'état des instances.

Le hub est propriétaire de toute la logique métier (serveurs, instances, ports, presets). L'agent exécute uniquement les effets techniques demandés.

---

## Prérequis

- Windows Server 2019 / 2022 ou Windows 10/11 (64 bits)
- PowerShell 5.1 ou supérieur
- Droits administrateur
- Accès Internet (téléchargement initial uniquement)

Python 3 et les dépendances Python sont installés automatiquement par les scripts si absents.

---

## Installation

### Méthode recommandée — launcher unique

Ouvrir **PowerShell en administrateur** sur le serveur Windows et exécuter :

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/PitLaneInstaller.exe" `
  -OutFile "$env:USERPROFILE\Downloads\PitLaneInstaller.exe"

Start-Process "$env:USERPROFILE\Downloads\PitLaneInstaller.exe" -Verb RunAs
```

Le launcher détecte l'état du serveur (AC EVO, SteamCMD, agent, service Windows) et propose :

| Option | Usage |
|---|---|
| Installer l'agent seulement | AC EVO Dedicated Server est déjà installé |
| Installation complète | Serveur vierge — installe SteamCMD, AC EVO et l'agent |
| Désinstaller / reset | Supprime l'agent et le service Windows |

### Méthode alternative — installateurs directs

Si le launcher n'est pas utilisable, télécharger et lancer l'installateur adapté.

**Agent seulement** (AC EVO déjà installé) :

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/setup-agent.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-agent.exe"

Start-Process "$env:USERPROFILE\Downloads\setup-agent.exe" -Verb RunAs
```

**Installation complète** (serveur vierge) :

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/setup-full.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-full.exe"

Start-Process "$env:USERPROFILE\Downloads\setup-full.exe" -Verb RunAs
```

### Méthode depuis le dépôt (développement)

AC EVO déjà installé :

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\installers\setup-agent.ps1
```

Serveur vierge :

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\installers\setup-full.ps1
```

### Ce qu'installe chaque script

- Python 3 (si absent)
- Les dépendances Python (`requirements.txt`)
- La tâche planifiée Windows `PitLaneAgent` (démarre l'agent au démarrage)
- La règle firewall entrante TCP/8181 pour l'API agent
- Le fichier `agent/config.yml` avec les chemins détectés automatiquement

Les ports des instances AC EVO ne sont **pas** ouverts à l'installation. Ils sont gérés dynamiquement par le hub lors de la création, modification ou suppression d'une instance.

---

## Mise à jour

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/updater.exe" `
  -OutFile "$env:USERPROFILE\Downloads\updater.exe"

Start-Process "$env:USERPROFILE\Downloads\updater.exe" -Verb RunAs
```

L'updater remplace les fichiers agent et relance le service. Il **conserve** `config.yml`.

---

## Désinstallation

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/uninstaller.exe" `
  -OutFile "$env:USERPROFILE\Downloads\uninstaller.exe"

Start-Process "$env:USERPROFILE\Downloads\uninstaller.exe" -Verb RunAs
```

---

## Configuration

Après installation, le fichier de configuration est :

```text
agent/config.yml
```

Il est généré à partir de `agent/config.template.yml`. Les chemins sont détectés automatiquement à l'installation ; seul le `jwt_secret` doit correspondre à celui configuré côté hub.

```yaml
http:
  host: 0.0.0.0
  port: 8181
  base_url: https://mon-serveur.example.com  # URL publique de l'agent

game:
  install_path: C:\ACEVOServer
  executable_name: AssettoCorsaEVOServer.exe
  configs_path: C:\ACEVOServer\configs
  results_path: C:\ACEVOServer\results
  result_scan_interval: 1.0
  result_stable_scans: 2
  result_upload_timeout: 10.0

steam:
  steamcmd_path: C:\SteamCMD\steamcmd.exe
  app_id: 4564210
  appmanifest_path: C:\SteamCMD\steamapps\appmanifest_4564210.acf

hubs:
  - name: my-hub
    enabled: true
    required: true
    base_url: https://your-hub.example.com
    runtime_report_endpoint: /api/agent/runtime-report
    websocket_endpoint: /api/agent/ws
    websocket_enabled: true
    runtime_report_interval: 1      # secondes entre chaque envoi de métriques live
    runtime_scan_interval: 0.5
    instance_http_timeout: 0.5
    # agent_token: token-dédié       # optionnel, utilise jwt_secret si absent

auth:
  jwt_secret: CHANGEME
  jwt_algorithm: HS256

logging:
  logs_path: C:\ACEVOServer\logs
  # results_spool_path: C:\ACEVOServer\logs\result-spool
  results_spool_max_bytes: 1073741824
  results_spool_minimum_free_bytes: 5368709120
  max_lines: 500
```

Le fichier `config.yml` est **rechargé à chaud** : toute modification est prise en compte sans redémarrer l'agent.

Il est possible de déclarer plusieurs hubs (production + dev local) dans la section `hubs`.

---

## Vérification après installation

Vérifier que la tâche planifiée existe et que `websocket-client` est installé :

```powershell
Get-ScheduledTask -TaskName PitLaneAgent
python -m pip show websocket-client
```

Puis vérifier dans les logs de l'agent que la connexion WebSocket est établie :

```text
[hub-ws] Connecte a "my-hub"
```

Si l'agent reste en boucle déconnexion/reconnexion, vérifier en priorité :

- que le hub expose bien l'endpoint WebSocket (`/api/agent/ws`)
- que le `jwt_secret` (ou `agent_token`) est identique côté hub et côté agent
- que l'URL `base_url` du hub est accessible depuis le serveur Windows

---

## Responsabilités

### Hub

- Propriétaire de la liste des serveurs, instances, ports, presets et sessions
- Décide des actions (création, modification, suppression)
- Affiche l'état serveur/instance dans l'interface
- Stocke les métriques live dans Redis

### Agent

- Expose une API locale sécurisée par JWT (TCP/8181)
- Maintient une connexion WebSocket persistante vers chaque hub configuré
- Remonte heartbeat, métriques CPU/RAM/processus et état des instances en temps réel
- Ouvre/ferme les ports firewall sur demande du hub
- Lance, arrête et redémarre les processus AC EVO
- Exécute SteamCMD pour les mises à jour et vérifications de build
- Expose les logs des instances (REST + WebSocket streaming)

---

## Communication WebSocket

L'agent maintient une connexion WebSocket persistante vers chaque hub avec `websocket_enabled: true`.

### Messages envoyés par l'agent

| Message | Déclencheur |
|---|---|
| `hello` | Connexion initiale |
| `runtime_report` | Chaque tick (`runtime_report_interval`) + après chaque commande |
| `result_artifact_available` | Un fichier résultat stable est présent dans le spool pour ce hub |
| `command_ack` | Progression durable `received`, `executing`, `succeeded` ou `failed` |

### Commandes reçues par l'agent

| Commande | Action |
|---|---|
| `prepare_instance` | Ouvre les ports firewall |
| `update_instance_network` | Remplace les règles firewall existantes |
| `cleanup_instance` | Ferme les ports (refuse si l'instance tourne) |
| `launch_instance` | Lance l'instance avec une config runtime fournie |
| `start_instance` | Démarre avec la dernière config runtime en mémoire |
| `stop_instance` | Arrête le processus |
| `restart_instance` | Redémarre avec une config runtime fournie |
| `get_instance_logs` | Retourne les dernières lignes de log |
| `resync_result_artifacts` | Rescanne les fichiers d'une tentative et remet ses artefacts en file |
| `purge_result_artifacts` | Dry-run ou purge une liste explicitement autorisée de Practice/WarmUp déjà livrés |
| `steam_update_check` | Compare le build local et le build distant |
| `steam_update` | Lance la mise à jour via SteamCMD |
| `steam_update_logs` | Retourne les logs SteamCMD |
| `runtime_report` | Retourne immédiatement un rapport runtime |

Les commandes de schéma 2 portent un identifiant, une clé d'idempotence et un
fence stables. L'agent les écrit d'abord dans
`<logs_path>/agent-commands.sqlite3`, puis répond par des `command_ack`
progressifs. Une même commande n'est jamais exécutée deux fois : son état ou sa
réponse terminale est rejoué jusqu'à confirmation du Hub. Les mutations visant
la même instance sont sérialisées, tandis que des instances différentes peuvent
rester concurrentes.

SQLite est fourni par la bibliothèque standard de la distribution Python
complète utilisée par l'installateur ; aucun paquet `pip` supplémentaire n'est
nécessaire. L'ancien `command_result` reste accepté uniquement pour la
compatibilité avec un Hub antérieur pendant la migration.

Les lectures de monitoring utilisent un contrat séparé
`diagnostic_request`/`diagnostic_response`. Elles ne sont ni journalisées ni
rejouées comme des mutations. La requête versionnée `technical_history` lit une
tranche bornée de l'historique SQLite local : un point par minute et 30 jours de
rétention par défaut, configurables avec
`technical_history_interval_seconds` et `technical_history_retention_days`.
Chaque point conserve les charges CPU globale, maximale et par cœur, la RAM,
les débits réseau et disque globaux, ainsi que les métriques non sensibles des
instances. La réponse calcule min, moyenne, p95, maximum et dernière valeur sur
la fenêtre complète avant de réduire les séries à 120 points. Cette collecte
continue reste indépendante des runs détaillés du Capacity Profiler et n'alourdit
pas le heartbeat : les séries ne quittent l'agent que lors d'une lecture
diagnostique explicite.

Le rapport runtime inclut les compteurs et la taille de ce journal. Son
nettoyage reste conservateur : seuls les succès dont l'accusé terminal a été
confirmé par le Hub depuis plus de 365 jours sont supprimés automatiquement au
démarrage du journal, puis au plus une fois par jour. Les commandes échouées,
en cours ou encore en attente d'une confirmation ne sont jamais purgées par
cette politique. La durée et la taille de lot peuvent être ajustées avec
`command_journal_success_retention_days` et
`command_journal_cleanup_limit`.

### Pipeline de résultats

À chaque lancement corrélé, l'agent crée un manifeste local puis scanne le
`ResultsPath` isolé par instance et par `ResultCorrelationId`. Un fichier doit être inchangé pendant deux
scans et contenir un objet JSON valide avant d'être copié atomiquement dans le
spool. La copie porte une identité déterministe et un SHA-256, puis est envoyée
par HTTP vers le `ResultsPostUrl` signé fourni par le hub. En cas d'échec, le
spool reste sur disque et l'upload reprend avec un délai exponentiel, y compris
après redémarrage de l'agent. Les Quick Sessions et lancements techniques gardent
le répertoire local de l'instance mais ferment toute fenêtre collectée précédente.

Le rapport runtime expose le volume du spool, son nombre de fichiers, les
statuts d'artefacts et l'espace disque libre. Les seuils configurés produisent
un état `healthy`, `warning` ou `critical`, mais ne déclenchent aucune suppression
automatique. La commande `purge_result_artifacts` reste en dry-run sans
`execute: true` et n'accepte qu'une liste explicite d'artefacts déjà `delivered`
de type Practice/WarmUp. Qualification, Race, pending et les artefacts non
autorisés restent protégés ; le hub ne doit envoyer cette autorisation qu'après
la clôture sportive sans incident.

Le scan périodique est volontairement la seule source de découverte en V1 : il
n'ajoute aucune dépendance Windows et ne peut pas perdre une notification
filesystem. Avec plusieurs hubs configurés, le signal WebSocket est envoyé
uniquement au hub dont l'origine correspond au `ResultsPostUrl`; l'URL signée
elle-même n'est jamais incluse dans la notification ou l'inventaire.

Le push HTTP `runtime_report_endpoint` n'est utilisé que si `websocket_enabled: false` est explicitement configuré sur un hub (fallback).

---

## API REST

Toutes les routes requièrent :

```
Authorization: Bearer <token>
```

### Système

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/system` | Infos système ponctuelles (CPU, RAM, OS, build) |

### Provisioning réseau instance

Ces routes appliquent uniquement les effets firewall demandés par le hub. Elles ne créent pas d'objet instance dans l'agent.

| Méthode | Route | Description |
|---|---|---|
| POST | `/api/instances/{id}/prepare` | Ouvre les ports firewall TCP/UDP/HTTP |
| PUT | `/api/instances/{id}/network` | Remplace les règles firewall existantes par les nouvelles |
| POST | `/api/instances/{id}/cleanup` | Ferme les ports (erreur si l'instance tourne) |

### Commandes runtime instance

Le hub fournit l'instance complète dans le payload.

| Méthode | Route | Description |
|---|---|---|
| POST | `/api/instances/{id}/launch` | Lance avec une config runtime fournie |
| POST | `/api/instances/{id}/start` | Démarre avec la dernière config runtime en mémoire |
| POST | `/api/instances/{id}/stop` | Arrête l'instance |
| POST | `/api/instances/{id}/restart` | Redémarre avec une config runtime fournie |
| POST | `/api/instances/{id}/results/resync` | Rescanne et remet en file les résultats de la tentative demandée |
| GET | `/api/instances/{id}/logs` | Dernières lignes de log |
| WS | `/api/instances/{id}/logs/stream` | Streaming live des logs |

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
| GET | `/api/steam/update/logs` | Logs de la dernière mise à jour SteamCMD |
| POST | `/api/steam/update-check` | Compare build local et build distant |

---

## Logs

```text
logs/
├── log_<instance_id>_YYYY-MM-DD_HH-MM-SS.log   # log par instance
├── result-spool/                                # manifests et copies résultat persistantes
└── steam_update.log                              # log SteamCMD
```

---

## Release (workflow GitHub Actions)

Sur un push vers `main`, le workflow produit les artifacts de build uniquement (pas de release publique).

Pour publier une release, créer et pousser un tag :

```powershell
git tag v0.4.0
git push origin v0.4.0
```

Le workflow crée alors la release GitHub avec les assets suivants :

| Asset | Description |
|---|---|
| `PitLaneInstaller.exe` | Launcher recommandé — détection + menu interactif |
| `setup-agent.exe` | Installation agent seulement |
| `setup-full.exe` | Installation complète (SteamCMD + AC EVO + agent) |
| `updater.exe` | Mise à jour de l'agent |
| `uninstaller.exe` | Désinstallation |
| `agent.zip` | Archive des sources agent (utilisée par les scripts) |

Le workflow peut aussi être déclenché manuellement depuis GitHub Actions avec un input `tag` (ex. `v0.4.0`) pour créer la release sur le commit courant.
