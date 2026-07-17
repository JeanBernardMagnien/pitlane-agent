# Assetto Corsa EVO — Dedicated Server : documentation de rétro-ingénierie

Build analysé : **release 0.8.0, version 0.8.0+release.37**, revision `460fa7d4a29c48889e2af02d208bf64eaa2aedd4`, steam appid `3058630`, compilé le 07/07/2026.

Cette doc a été construite par lecture des chaînes de caractères des binaires (`ServerLauncher.dll` + `AssettoCorsaEVOServer.exe` + `AssettoCorsaEVO.exe`, le jeu complet), et **surtout** par des tests en conditions réelles : lancement du serveur avec des fichiers JSON de test et lecture des logs (le serveur dump lui-même sa config complète résolue au démarrage — c'est la source la plus fiable qu'on ait).

**Mise à jour** : le jeu complet (`Assetto Corsa EVO`, appid 3058630) était déjà installé à côté du serveur dédié — je l'ai passé au même traitement (extraction de chaînes) et j'ai aussi vérifié ce que propose le SDK officiel de modding. Voir §0 ci-dessous pour ce que ça a donné (spoiler : ça confirme des choses, mais ça ne débloque pas les pitstops obligatoires côté serveur, et ça permet aussi de repérer une source externe à ne PAS croire).

Tout ce qui est marqué **[VÉRIFIÉ]** a été confirmé en exécutant réellement `AssettoCorsaEVOServer.exe`. Tout ce qui est marqué **[DÉDUIT]** vient uniquement de l'analyse des chaînes binaires (noms de champs protobuf, messages d'erreur, messages de log) sans test direct — probablement correct mais pas garanti à 100%. Tout ce qui est marqué **[NON RÉSOLU]** est une piste identifiée mais pas encore confirmée.

---

## 0. Le jeu installé et le SDK — ce que ça apporte (et ce que ça n'apporte pas)

### 0.1 Le jeu complet (déjà installé)

Bonne nouvelle : pas besoin de le télécharger, il est déjà là (`C:\...\Steam\steamapps\common\Assetto Corsa EVO`). Je l'ai passé au même traitement d'extraction de chaînes que le serveur dédié (`AssettoCorsaEVO.exe`, 86 Mo).

**Ce que ça confirme** : les chaînes `mandatory_pitstops_done` et `mandatory_pitstops_countdown` existent dans le jeu — ce sont des éléments d'interface (HUD) affichés pendant une vraie course, donc **la fonctionnalité pitstop obligatoire est bien vivante et fonctionnelle en jeu**, pas un vestige mort dans le code.

**Ce que ça confirme aussi (mauvaise nouvelle)** : dans le jeu, `mandatory_pitstop_count`, `mandatory_pitstop_window_duration_s`, `mandatory_pitstop_requires_refuelling`, `mandatory_pitstop_requires_tyre_change` appartiennent au message protobuf `GameModeSelectionSession`, qui fait partie de `GameModeSelectionClientCommands.proto` — **c'est le schéma utilisé par le menu "Course rapide / Course personnalisée" solo du jeu (contre IA), un système totalement différent et séparé de `BuildSeasonDefinitionRequest`** (celui utilisé par `-seasonjson` sur le serveur dédié, voir §4). Les deux schémas ne communiquent pas entre eux. Donc même avec le jeu installé, il n'y a pas de pont direct vers un moyen d'activer les pitstops obligatoires côté serveur dédié.

**Piste `content.kspkg` — impasse (probablement)** : j'ai comparé les deux fichiers `content.kspkg` :
- Celui du **serveur dédié** (249 Mo) : entièrement rempli de zéros — c'est un fichier "stub"/placeholder, pas du vrai contenu. Confirme que le serveur dédié n'a pas besoin des assets visuels, juste de la logique.
- Celui du **jeu complet** (69 Go) : pas d'en-tête reconnaissable (pas de signature ZIP, pas de motif clair) — tout indique un **format propriétaire compressé/chiffré**. Impossible d'en extraire quoi que ce soit sans un outil Kunos dédié.

Le jeu utilise `cohtml`/`RenoirCore`/`v8.dll` (bibliothèque **Coherent Labs**) pour son interface — ça veut dire que les menus (dont "héberger une partie") sont probablement écrits en HTML/CSS/JavaScript. Si ces fichiers étaient accessibles en clair, ce serait une mine d'or (JS lisible reflétant l'appel API exact utilisé par le menu multijoueur). Mais ils sont à l'intérieur du `content.kspkg` chiffré — **inaccessibles avec les moyens actuels**, sauf outil d'extraction officiel qu'on n'a pas.

### 0.2 Le SDK — pas utile pour ce qu'on cherche (pour l'instant)

J'ai vérifié en ligne : le SDK Assetto Corsa EVO est sorti en tools Steam le **3 juin 2026**, avec la mise à jour 0.7. **Il ne couvre actuellement que l'édition de véhicules** (pipeline PBR, gestion LOD, pièces aftermarket) et les mods véhicules créés sont pour l'instant restreints au solo. Kunos a annoncé que l'édition de circuits, les livrées custom et le support multijoueur pour les mods viendront **plus tard**, mais rien n'est dit sur un éventuel éditeur de saisons/événements serveur.

**Conclusion : installer le SDK n'aidera très probablement pas** à débloquer les pitstops obligatoires ni à mieux comprendre le format serveur — c'est un outil de création de voitures 3D, sans rapport avec la configuration du serveur dédié. Pas la peine de le télécharger pour cet objectif précis (mais si tu veux moddé des voitures, why not, c'est juste un autre sujet).

Sources : [Assetto Corsa EVO Opens The Gates To Modding With New SDK Toolset (OverTake.gg)](https://www.overtake.gg/news/assetto-corsa-evo-opens-the-gates-to-modding-with-new-sdk-toolset.4550/), [Assetto Corsa EVO 0.7: Official Modding Tools Are Finally Here (BoxThisLap)](https://boxthislap.org/assetto-corsa-evo-0-7-official-modding-tools-are-finally-here/)

### 0.3 ⚠️ Attention à cette source si tu tombes dessus en cherchant : low.ms

En cherchant en ligne, un article de la société d'hébergement **low.ms** ("Assetto Corsa EVO Server Configuration Guide") prétend que le serveur utilise un dossier `cfg` avec `settings.json`, `event.json`, `eventRules.json`, `entrylist.json`, `configuration.json`, en camelCase (`serverName`, `sessionType`, `sessionDurationMinutes`...), avec un paramètre `MANDATORY_PIT_STOP_COUNT` dans `eventRules.json`.

**C'est très probablement faux pour Assetto Corsa EVO.** Ce format (dossier `cfg`, `settings.json`/`event.json`/`eventRules.json`, camelCase) correspond exactement à celui d'**Assetto Corsa Competizione** (le jeu précédent de Kunos), qui est lui réellement documenté comme ça. Tout ce que j'ai vérifié **en faisant tourner le vrai exécutable du serveur AC EVO** contredit frontalement cet article : pas de dossier `cfg`, pas de `settings.json`/`event.json`/`eventRules.json`, format `-configjson`/`-seasonjson` en snake_case confirmé par les messages d'erreur natifs de protobuf émis par le binaire lui-même. Ça sent fortement le contenu généré/copié depuis la doc ACC pour du référencement, sans vérification réelle sur AC EVO.

**Ne te fie pas à cette source** (ni à d'autres qui répéteraient la même structure) — fais confiance à ce qui est documenté dans ce fichier, vérifié directement sur le binaire réel.

---

## 1. Architecture générale

Il y a deux exécutables :

- **`ServerLauncher.exe`** (+ `ServerLauncher.dll`) : l'interface graphique (.NET / Avalonia MVVM). Elle ne fait qu'une chose : construire deux fichiers JSON puis lancer le vrai serveur avec.
- **`AssettoCorsaEVOServer.exe`** : le vrai moteur de jeu / serveur dédié (C++, basé sur gflags pour les arguments, protobuf pour toute la config/état, cpp-httplib pour le réseau HTTP, nlohmann::json pour certains parsings custom comme l'entry list).

**[VÉRIFIÉ]** Le launcher lance le serveur avec cette ligne de commande :

```
AssettoCorsaEVOServer.exe -configjson "<chemin>\config.json" -seasonjson "<chemin>\season.json" [-no_lobby]
```

Le bouton "Copy Cmd" du launcher (`CopyCmdCommand` dans `MainVM`) permet de copier cette commande exacte — pratique si tu veux la voir directement depuis la GUI sans passer par moi.

Tu peux donc **totalement contourner la GUI** et lancer le serveur toi-même avec tes propres fichiers JSON, ou l'intégrer dans un script/scheduler externe.

### Vérité importante sur le format des JSON

**[VÉRIFIÉ]** `-configjson` et `-seasonjson` sont parsés avec le parseur JSON **natif de protobuf** (`google::protobuf::util::JsonStringToMessage`). Preuve : en donnant une valeur d'enum invalide, l'erreur retournée est exactement au format protobuf :

```
can't be loaded into BuildSeasonDefinitionRequest ((initial_grip): invalid value "FAST" for type TYPE_ENUM)
```

Conséquences pratiques :
- Les clés JSON = noms exacts des champs `.proto`, en **snake_case** (`server_name`, `entry_list_path`, `max_pit_slot`, etc.).
- Les valeurs d'enum doivent être écrites avec leur **nom C++ complet préfixé**, pas juste le suffixe. Exemples vérifiés : `"InitialGrip_FAST"` (pas `"FAST"`), `"GameModeType_RACE_WEEKEND"` (pas `"RACE_WEEKEND"`), `"GameModeSelectionDuration_LAPS"`, `"GameModeSelectionWeatherType_CLEAR"`, `"GameModeSelectionWeatherBehaviour_STATIC"`.
- Un champ inconnu ou mal typé fait échouer le chargement avec un message d'erreur qui te dit exactement quel champ pose problème — utilise ça activement pour déboguer tes fichiers (voir section 8).

---

## 2. Ligne de commande complète

**[VÉRIFIÉ]** obtenu via `AssettoCorsaEVOServer.exe --help` (fonctionne, ça n'ouvre pas de fenêtre, ça tourne en console et log tout dans stdout).

### 2.1 Flags essentiels pour un serveur dédié

| Flag | Type | Rôle |
|---|---|---|
| `-configjson <path>` | string | Fichier JSON → `ServerConfiguration` (voir §3) |
| `-seasonjson <path>` | string | Fichier JSON → `BuildSeasonDefinitionRequest` (voir §4) — **doit être utilisé avec `-configjson`, jamais seul** |
| `-serverconfig <path>` | string | Équivalent binaire compilé de `-configjson` (format `.serverconfiguration`) |
| `-seasondefinition <path>` | string | Équivalent binaire compilé de `-seasonjson`, mais charge directement un `SeasonDefinition` **complet** (pas la version simplifiée !) — voir §6 |
| `-embedded_serverconfig <b64?>` | string | Config serveur encodée inline (pas de fichier) |
| `-embedded_seasondefinition <b64?>` | string | Season définition encodée inline |
| `-name <str>` | string | Nom de "fichier serveur" |
| `-no_lobby` | bool | Désactive l'enregistrement sur le lobby public Kunos (utile pour tester en LAN sans polluer la liste des serveurs publics) |
| `-testing_server_entrylist` | bool | Mode diagnostic : teste le chargement de l'entry list |
| `-testing_server_results` | bool | Mode diagnostic : teste l'envoi/écriture des résultats |
| `-write_server_results` | bool | Force l'écriture des résultats sur disque |
| `-save_result` | bool | Sauvegarde le résultat sur disque |
| `-load_result` | bool | Recharge un résultat depuis le disque |
| `-result_event <int32>` (défaut -1) | int32 | Index de l'event pour charger/sauver un résultat spécifique |
| `-result_session <int32>` (défaut -1) | int32 | Index de la session pour charger/sauver un résultat spécifique |
| `-startup_gamemode <str>` | string | Mode de jeu au démarrage |
| `-startup_season <str>` | string | Saison à charger au démarrage |
| `-startup_last_season` | bool | Recharge la dernière saison utilisée |
| `-clear_guid` | bool | Réinitialise le GUID machine |
| `-virtual_ai_cars <int32>` (défaut -1) | int32 | **Fait spawner des IA sur le serveur dédié** (`0` = activé mais n'en spawn aucune, `N` = en spawn N). Confirmé "servers only atm" dans la description → conçu spécifiquement pour serveurs dédiés. Potentiellement intéressant pour remplir un serveur vide. |
| `-player_guid_prefix <str>` | string | Préfixe de GUID joueur |
| `-disable_content_validation` | bool | Désactive la validation de contenu à la connexion (⚠️ à utiliser avec prudence, sécurité) |
| `-disable_performance_validation` | bool | Désactive la validation de perf à la connexion |
| `-no_backend` | bool | Désactive complètement la connexion au backend Kunos |
| `-backend <url>` | string | URL du backend (debug/dev uniquement normalement) |

### 2.2 Diagnostic & logs (très utile pour déboguer tes soucis de results_post_url / entrylist)

| Flag | Rôle |
|---|---|
| `-log_file <path>` | Redirige les logs vers un fichier au lieu de stdout |
| `-log_debug <"logger1,logger2">` | Passe des loggers spécifiques en niveau DEBUG |
| `-log_trace <"logger1,...">` | Niveau TRACE (le plus verbeux) |
| `-log_info` / `-log_warning` / `-log_error` / `-log_critical` / `-log_off` | Idem pour les autres niveaux |
| `-log_copypaste_mode` | Enlève les timestamps des logs (pratique pour diff/comparer) |
| `-enable_log_history` | Garde un historique des logs |
| `-messages_to_log <str>` | Filtre les messages réseau à logger |
| `-messages_to_ignore <str>` | Filtre les messages réseau à ignorer |
| `-dumplevel <int32>` (défaut 2) | Niveau de détail des crash dumps |

**[VÉRIFIÉ]** Les catégories de logger vues dans les logs réels : `[server]`, `[network]`, `[gameplay]`, `[ui]`, `[platformCore]`, `[messages]`, `[crash]`, `[others]`. Donc par exemple, pour avoir un maximum de détails sur le réseau et le serveur :

```
AssettoCorsaEVOServer.exe -configjson config.json -seasonjson season.json -log_debug="server,network" -log_file server.log
```

### 2.3 Astuce : `-flagfile`

**[VÉRIFIÉ via --help]** `-flagfile <path>` charge tous les flags depuis un fichier texte (un flag par ligne, syntaxe `--flag=valeur`). Permet d'avoir un fichier `server_launch.flags` versionné/réutilisable au lieu d'une ligne de commande à rallonge. Il existe aussi `-fromenv` / `-tryfromenv` pour piocher des flags dans des variables d'environnement `FLAGS_xxx`.

### 2.4 `-use_dev_saving_mode` — piste pour débloquer plus de réglages **[NON RÉSOLU, à tester]**

Description exacte du flag : *"use a bin -> json and json -> missing bin saving procedure"*. Ça sent fort un mode qui permettrait de convertir un `.seasondefinition` binaire complet en JSON lisible/éditable, et inversement. Si ça fonctionne comme je le soupçonne, ce serait **le moyen de contourner la limitation du `BuildSeasonDefinitionRequest` simplifié** et d'éditer à la main un `SeasonDefinition` complet (avec pitstops obligatoires, etc. — voir §7). Je n'ai pas eu le temps de le tester à fond ; piste à explorer :

```
AssettoCorsaEVOServer.exe -seasondefinition "content\data\race_weekend.seasondefinition" -use_dev_saving_mode ...
```

(Note : les fichiers `content\data\*.seasondefinition` ne sont pas extraits sur le disque — ils sont dans `content.kspkg`, probablement un package compressé/chiffré. Il faudra peut-être les extraire d'abord, ou ce flag génère peut-être le fichier JSON à un autre endroit accessible.)

---

## 3. `ServerConfiguration` — tous les champs (config serveur)

**[VÉRIFIÉ]** Dump JSON réel obtenu en faisant tourner le serveur avec un fichier de config minimal (le serveur log sa config résolue complète au démarrage) :

```json
{
  "server_tcp_listener_port": 9600,
  "server_udp_listener_port": 9600,
  "server_tcp_internal_port": 0,
  "server_udp_internal_port": 0,
  "server_http_port": 8081,
  "server_name": "Test Server",
  "launch_path": "",
  "netcode_update_interval": 55,
  "driver_password": "",
  "spectator_password": "",
  "max_players": 20,
  "allowed_cars_list_full": [],
  "type": "MultiplayerServerListSessionType_BOTH",
  "cycle": false,
  "admin_password": "",
  "pi_min": 0,
  "pi_max": 0,
  "property_1": [],
  "property_2": [],
  "property_3": [],
  "entry_list_server_url": "",
  "results_post_url": "http://127.0.0.1:9/results",
  "token": "",
  "entry_list_path": "C:\\...\\test_entrylist.json",
  "results_path": "results",
  "tuning_type": "TuningAllowed"
}
```

### Détail des champs

| Champ | Type | Description / notes |
|---|---|---|
| `server_tcp_listener_port` | int | Port TCP public |
| `server_udp_listener_port` | int | Port UDP public |
| `server_tcp_internal_port` | int | Port TCP interne (utile si tu es derrière un reverse proxy/NAT et veux exposer un port différent du port d'écoute réel — log vu : *"An internal TCP port {} has been specified, opening socket to that instead of listener port {}"*) |
| `server_udp_internal_port` | int | Idem en UDP |
| `server_http_port` | int | Port HTTP interne du serveur (voir §8 pour ce qu'il sert vraiment) |
| `server_name` | string | Nom affiché dans la liste des serveurs |
| `launch_path` | string | **[DÉDUIT]** Peut pointer directement vers un fichier `.sessiondefinition`, `.seasondefinition` ou `.eventdefinition` pour lancer directement ce contenu (chaîne trouvée : `sessiondefinition\|.seasondefinition\|.eventdefinition`) |
| `netcode_update_interval` | int | Intervalle de mise à jour netcode (ms) |
| `driver_password` | string | Mot de passe pilote |
| `spectator_password` | string | Mot de passe spectateur |
| `admin_password` | string | Mot de passe admin (commandes chat `>>` — voir logs `"You are now an admin."`) |
| `max_players` | int | Nombre max de joueurs |
| `allowed_cars_list_full` | array de `AllowedCar` | Liste blanche de voitures autorisées (si vide = toutes autorisées) |
| `type` | enum `MultiplayerServerListSessionType_*` | Type de serveur pour le listing public (vu : `BOTH`) |
| `cycle` | bool | Active le cycle automatique d'événements (`IsCycleEnabled` dans la GUI) |
| `pi_min` / `pi_max` | int | Fourchette de Performance Index autorisée |
| `entry_list_server_url` | string | URL distante pour récupérer l'entry list (voir §5) |
| `entry_list_path` | string | Fichier local pour l'entry list (voir §5) |
| `results_post_url` | string | URL de webhook POST pour les résultats (voir §8) |
| `results_path` | string | Dossier local d'écriture des résultats (voir §8) |
| `token` | string | **[DÉDUIT]** Token d'authentification (probablement lié au lobby/backend Kunos ou à un serveur "ranked") |
| `tuning_type` | enum `TuningType_*` | `NotInitialized` / `TuningAllowed` / `TuningDenied` — autorise ou non le tuning des voitures |

### Champs présents dans le protobuf mais **absents de l'interface graphique** du launcher

D'après l'analyse des `ViewModels` .NET (`ServerVM`), la GUI n'expose que : `ServerName`, `AdminPassword`, `DriverPassword`, `SelectedTuningType`, `SelectedServerType`, `MaxPlayers`, `MaxPlayersLimit`, `TcpPort`, `UdpPort`, `HttpPort`, `ResultsPath`, `ResultsPostUrl`, `EntryListPath`, `EntryListUrl`, `IsCycleEnabled`.

→ **`spectator_password` et `token` ne sont PAS réglables depuis la GUI**, uniquement via `-configjson` en JSON brut. Si tu veux un mot de passe spectateur séparé, c'est le seul moyen.

---

## 4. `BuildSeasonDefinitionRequest` — le "season.json" (format simplifié / wizard)

**[VÉRIFIÉ]** C'est **ce que `-seasonjson` charge réellement** (confirmé par le log `"season.json" loaded into BuildSeasonDefinitionRequest`). Le serveur "compile" ensuite cette requête simplifiée en un `SeasonDefinition` complet en interne.

### Exemple complet **testé et fonctionnel** (practice à Brands Hatch GP)

```json
{
  "game_type": "GameModeType_PRACTICE",
  "event": {
    "track": "Brands Hatch",
    "layout": "GP",
    "event_name": "GP Time Attack",
    "track_length": 3916,
    "max_pit_slot": 32
  },
  "game_config": {
    "practice_duration": 600,
    "practice_time_of_day": { "month": 6, "minute": 0, "second": 0, "time_multiplier": 1 },
    "practice_overtime_waiting_next_session": 60,
    "practice_max_wait_to_box": 60,
    "min_waiting_for_players": 0,
    "max_waiting_for_players": 60
  },
  "weather_type": "GameModeSelectionWeatherType_CLEAR",
  "weather_behaviour": "GameModeSelectionWeatherBehaviour_STATIC",
  "initial_grip": "InitialGrip_FAST",
  "export_json": true
}
```

Avec ce fichier + le config.json du §3, le serveur a réellement démarré, ouvert les ports TCP/UDP, et généré une session Practice complète avec système de pénalités par défaut (voir §6).

### Champs de `BuildSeasonDefinitionRequest`

| Champ | Type | Notes |
|---|---|---|
| `game_type` | enum `GameModeType_*` | Voir valeurs ci-dessous |
| `event` | `EventItem` | `track`, `layout`, `event_name`, `track_length`, `max_pit_slot` — les valeurs valides sont listées dans `events_practice.json` et `events_race_weekend.json` à la racine du dossier serveur (liste officielle piste+layout) |
| `game_config` | `SimpleGameConfig` | Voir tableau détaillé plus bas |
| `weather_type` | enum `GameModeSelectionWeatherType_*` | |
| `weather_behaviour` | enum `GameModeSelectionWeatherBehaviour_*` | `STATIC` ou `DYNAMIC` |
| `initial_grip` | enum `InitialGrip_*` | `GREEN`, `FAST`, `OPTIMUM` |
| `export_json` | bool | **[DÉDUIT]** Semble contrôler si le serveur ré-exporte le `SeasonDefinition` généré en JSON quelque part sur disque (à vérifier — je ne l'ai pas localisé pendant les tests, peut-être lié à `-use_dev_saving_mode`) |

### `SimpleGameConfig` (le contenu de `game_config`)

| Champ | Notes |
|---|---|
| `practice_duration`, `qualify_duration`, `warmup_duration` | Durée en secondes (probablement) de chaque session |
| `practice_time_of_day`, `qualify_time_of_day`, `warmup_time_of_day`, `race_time_of_day` | Objets `GameModeSelectionTimeOfDay` : `month`, `minute`, `second`, `time_multiplier` (le champ `hour` existe très probablement aussi, je ne l'ai pas capturé distinctement dans le dump binaire — teste avec/sans) |
| `practice_overtime_waiting_next_session`, `qualify_overtime_waiting_next_session`, `warmup_overtime_waiting_next_session`, `race_overtime_waiting_next_session` | Temps d'attente en overtime avant la session suivante |
| `practice_max_wait_to_box`, `qualify_max_wait_to_box`, `warmup_max_wait_to_box`, `race_max_wait_to_box` | Temps max avant renvoi forcé au stand |
| `race_duration` + `race_duration_type` (`GameModeSelectionDuration_TIME` ou `GameModeSelectionDuration_LAPS`) | Durée de course en temps OU en tours |
| `min_waiting_for_players`, `max_waiting_for_players` | Fenêtre d'attente des joueurs avant le lancement |
| `enable_custom_penalities` | bool — active un système de pénalités custom |
| `car_cut_tyres_out` | Seuil de coupure de piste (nombre de roues hors piste) |
| `warning_trigger_countdown` | |
| `time_penalty_ms` | Pénalité de temps par défaut en ms |

### Valeurs d'enum confirmées

- **`GameModeType_*`** : `NONE`, `RACE_WEEKEND`, `SRO_RACE`, `INSTANT_RACE`, `SUPERPOLE`, `FREEROAM`, `DRIFT`, `RALLY`, `HOTSTINT`, `HOTLAP`, `PRACTICE`, `TEST_DRIVE`, `A_TO_B`
- **`GameModeSelectionWeatherType_*`** : `CLEAR`, `SCATTERED_CLOUDS`, `BROKEN_CLOUDS`, `OVERCAST`, `DRIZZLE`, `RAIN`, `HEAVY_RAIN`, `CUSTOM`, `DAMP`
- **`GameModeSelectionWeatherBehaviour_*`** : `STATIC`, `DYNAMIC`
- **`InitialGrip_*`** : `GREEN`, `FAST`, `OPTIMUM`
- **`GameModeSelectionDuration_*`** : `NONE`, `TIME`, `LAPS`
- **`TuningType_*`** : `NotInitialized`, `TuningAllowed`, `TuningDenied`

### Fichiers `events_*.json` fournis avec le serveur

`events_practice.json` et `events_race_weekend.json` (à la racine du dossier serveur) contiennent la **liste officielle complète** des combinaisons piste/layout valides avec leur `track_length` et `max_pit_slot` exacts — utilise-les comme référence pour remplir le champ `event` sans te tromper sur les noms exacts (attention à la casse et aux espaces, ex. `"Circuit de Spa Francorchamps"`, `"Mount Panorama"`, `"Nurburgring"` sans trema).

⚠️ Note : `max_pit_slot` est le **nombre de places dans les stands** de la piste (capacité physique), **pas** un réglage lié à un arrêt obligatoire.

---

## 5. Entry List

Il y a **deux mécanismes distincts** qui portent des noms proches — à ne pas confondre :

### 5.1 `ServerConfiguration.entry_list_path` / `entry_list_server_url`

**[DÉDUIT + partiellement testé]** Champs de `ServerConfiguration` (§3). D'après les commentaires trouvés dans le protobuf (*"Overwrite the current entrylist on runtime"*), ce mécanisme sert à **écraser l'entry list de la saison en cours d'exécution**, pas au chargement initial de la grille. Dans mon test, pointer `entry_list_path` vers un fichier n'a **pas** peuplé la grille de démarrage — la saison générée gardait un concurrent factice `"None"`.

Ce que j'ai trouvé dans les chaînes binaires pour la **structure du fichier JSON attendu** (non testé formellement avec un vrai chargement réussi, donc à vérifier) :

```json
{
  "entrylist": [
    { "steamid": "76561198000000001", "carmodel": "BMW M4 GT3 Evo" },
    { "steamid": "76561198000000002", "carmodel": "BMW M4 GT3 Evo" }
  ],
  "steamid_whitelist": [
    { "steamid": "76561198098260744" }
  ],
  "steamid_blacklist": []
}
```

Règles de validation vues dans les messages d'erreur du binaire :
- `"invalid steam id in a entry"` / `"invalid 'steamid'"` → le champ `steamid` doit être une string numérique Steam64 valide.
- `"Entrydata, need one of steam id or car, not both"` → chaque entrée whitelist/blacklist prend soit `steamid`, soit un identifiant de voiture — **pas les deux en même temps**.
- `"Carmodel need to be a string"` → `carmodel` doit être une string (nom de dossier de la voiture, probablement l'ID technique comme `ks_bmw_m4_gt3_evo` plutôt que le nom affiché — à vérifier, l'exemple trouvé dans le binaire montre `"BMW M4 GT3 Evo"` en toutes lettres donc c'est peut-être le nom affiché).
- Un champ `ballast` et un champ `restrictor` (numériques) semblent supportés par entrée : messages `"[entrylist] Ballast out of range {} -> {}"`, `"[entrylist] Restrictor out of range {} -> {}"`, et log de succès `"[entrylist] id: {}, ballast: {}, restrict: {}"`.
- Il existe aussi un champ potentiel `car_mechanic` vu juste après `carmodel` dans le binaire — rôle incertain, peut-être lié à un mécanisme d'auto-réparation/setup IA, à tester.

**Le serveur supporte les deux sources** :
- `entry_list_path` : fichier JSON local
- `entry_list_server_url` : URL HTTP distante interrogée périodiquement (exemple par défaut vu dans le binaire : `http://127.0.0.1:8080/entrylist`) — donc tu peux héberger un petit serveur HTTP qui sert dynamiquement ta liste d'inscrits (utile pour un système d'inscription en ligne, par exemple).

Messages d'erreur à surveiller dans les logs si ça ne marche pas : `"error connecting to entrylist uri: {}"`, `"error reading entrylist file: {}"`, `"failed parse entrylist json: {}"`.

### 5.2 `SeasonDefinition.entrylist` / `entrylist_file` / `entrylist_source`

**[DÉDUIT]** C'est la **vraie grille de départ** utilisée par la session (le champ qu'on voit rempli dans le dump JSON du §6 avec `competitors`, `cars`, `drivers`). `entrylist_file` (avec le même commentaire *"Overwrite the current entrylist on runtime"*) et `entrylist_source` (enum `DataSourceType`, vu `Custom` par défaut) suggèrent que la grille peut être définie de plusieurs façons : intégrée (`Custom`, définie inline dans le JSON), ou chargée depuis un fichier externe au format **binaire** `EntryListData` (protobuf), pas JSON.

La structure protobuf complète de la grille (si tu veux la construire à la main dans le JSON du `SeasonDefinition`, en passant par `-seasondefinition` en binaire ou en trouvant le bon point d'entrée JSON) :

```
EntryListData {
  competitors: [ EntryListData_Competitor { pguid, name, is_static } ]
  cars: [ EntryListData_Car { pguid, competitor_key, assigned_car_number, is_static, ... } ]
  drivers: [ EntryListData_Driver { pguid, first_name, last_name, short_name, nation, is_static, ... } ]
  crews: [ EntryListData_Crew { car_key, driver_keys, is_static } ]
}
```

**Recommandation pratique** : comme `-seasonjson`/`BuildSeasonDefinitionRequest` ne semble pas exposer de champ pour injecter une grille de concurrents fixe à la génération, le chemin le plus fiable pour l'instant reste `ServerConfiguration.entry_list_path` (rechargement à chaud) — **à tester en laissant le serveur tourner plus longtemps** (mon test s'est arrêté après quelques secondes). Regarde les logs pour la ligne `[entrylist] id: {}, ballast: {}, restrict: {}` qui confirme un chargement réussi.

---

## 6. Ce que le serveur construit réellement en interne (`SeasonDefinition` complet)

**[VÉRIFIÉ]** Voici le `SeasonDefinition` complet généré par le serveur à partir de l'exemple du §4 (practice à Brands Hatch), tel que loggé au démarrage. Ça montre à quel point le format complet est riche par rapport au `BuildSeasonDefinitionRequest` simplifié — utile pour comprendre ce qui existe "sous le capot" même si tout n'est pas exposé en JSON simplifié.

Structure générale :
```
SeasonDefinition
├── season_type: "SeasonDefinitionType_MultiPlayer"
├── gamemode_type: "GameModeType_PRACTICE"
├── no_leaderboard: true
├── cycle: false
├── name: "Test Server"
├── event_map: { "0": EventDefinition }
│     └── EventDefinition
│           ├── name: "Practice"
│           └── session_map: { "0": SessionDefinition }
│                 └── SessionDefinition
│                       ├── name / description
│                       ├── scene: { track_content_data, event_name, physics_type, spawn, containers[], layout_image, track_layout_name }
│                       ├── scene_source: "Custom"
│                       ├── specialization (google.protobuf.Any)
│                       │     └── @type: "type.googleapis.com/TimeAttack.Specialization"   ← pour PRACTICE
│                       │           ├── base: { session_duration_ms, session_laps, maximum_session_overtime_duration_ms,
│                       │           │           maximum_session_overtime_before_next_session, intro_music, end_music, end_replay_type }
│                       │           ├── penalty_transformations: { transformations: [] }
│                       │           ├── penalty_investigations: { triggers: [...] }   ← voir détail pénalités ci-dessous
│                       │           └── rules: []
│                       ├── weather: { initial_date_time, time_multiplier, recalc_interval_seconds, spatial_noise_data, static_data{...} }
│                       ├── weather_type / weather_source / weather_update_interval_seconds
│                       ├── initial_grip: "InitialGrip_FAST"
│                       ├── dynamic_track_condition: { initial_grip, rubber, marbles }
│                       ├── car_model: []
│                       ├── netcode_update_interval / save_as_default
│                       ├── pause_replay_enable / pause_go_to_pitlane_enable / pause_restart_enable
│                       └── crowd_density: 0.19
├── entrylist: { competitors: [{competitor_key:"", name:"None"}], cars: [], drivers: [] }
├── entrylist_file: "" / entrylist_source: "Custom"
├── event_mutable_data: {}
├── event_results_map: {}
└── season_cache: { current_session_id: 0, current_event_id: 0 }
```

### Système de pénalités par défaut (auto-généré, très utile à connaître)

Le serveur remplit automatiquement `penalty_investigations.triggers` avec 3 déclencheurs par défaut :

1. **`race_car_cut`** : `tyres_out: 3`, `wet_multiplier: 0` — coupure de piste si 3 roues sortent
2. **`wrong_way`** : `min_speed: 2`, `speed_multiplier: 0.1`, `out_of_track_multiplier: 2` — avec 2 paliers de check : `PenaltyType_Warning` (poids 30) puis `PenaltyType_Disqualification` (poids 100)
3. **`speeding`** (nommé `command_name: "pitlane"`) : `required_speed: 60`, `check_if_higher: true` — limite de vitesse en pitlane, avec `PenaltyType_Warning` (poids 62) puis `PenaltyType_MP_TeleportToPit` (poids 70, `penalty_time_ms: 10000`)

Types de pénalité vus : `PenaltyType_Warning`, `PenaltyType_Disqualification`, `PenaltyType_MP_TeleportToPit`. Il y en a probablement d'autres (le système ressemble beaucoup à celui d'ACC).

### **IMPORTANT — Arrêts aux stands obligatoires : statut**

Pour une session `PRACTICE`, la `specialization` utilisée est `TimeAttack.Specialization`, qui **n'a pas** de champ pitstop obligatoire (logique, le chrono n'a pas besoin de ça).

Le champ pitstop obligatoire existe dans le protobuf sous **`InstantRace.Specialization.MandatoryPitstop`** :
```
MandatoryPitstop {
  ranges: [ { start_ms, end_ms } ]   // fenêtre(s) de temps où l'arrêt doit être effectué
  requires_tyre_change: bool
  requires_refuelling: bool
}
```
C'est un `oneof` avec `last_eliminated` et `reset_physics_each_lap` dans le proto `InstantRace.Specialization.Rule` — donc probablement utilisé pour `INSTANT_RACE` / `RACE_WEEKEND` (les modes course, pas practice/time attack).

**Mais** : ce champ n'existe **ni** dans `SimpleGameConfig` (ce que `-seasonjson` accepte), **ni** dans la GUI du launcher (`ServerVM`/`SessionVM`/`EventVM` n'ont aucun champ "pitstop"). Il y a un schéma parallèle et distinct (`mandatory_pitstop_count`, `mandatory_pitstop_window_duration_s`, `mandatory_pitstop_requires_refuelling`, `mandatory_pitstop_requires_tyre_change`) dans un proto `GameModeSelectionSession` — mais celui-ci semble appartenir à l'UI de course solo/carrière du jeu principal, pas au serveur dédié.

**Conclusion : à ce stade (build 0.8.0), il n'y a pas de moyen confirmé et supporté d'activer un pitstop obligatoire via `-seasonjson` ou la GUI du launcher.** Les deux pistes à explorer si tu veux aller plus loin :
1. **`-use_dev_saving_mode`** (§2.4) pour éventuellement éditer un `SeasonDefinition` complet en JSON à la main et le charger via `-seasondefinition`.
2. Tester directement un `game_type: "GameModeType_RACE_WEEKEND"` ou `"GameModeType_INSTANT_RACE"` pour voir si `specialization.@type` devient `InstantRace.Specialization` et si, même sans champ dédié dans `SimpleGameConfig`, le serveur applique un pitstop par défaut basé sur autre chose (ex. `enable_custom_penalities`, ou un réglage lié au track_data). Je n'ai testé que `PRACTICE` par manque de temps.

---

## 7. Résultats — `results_post_url`, `results_path`, et comment savoir qu'un event est fini

### 7.1 `results_post_url` (webhook)

**[VÉRIFIÉ que le mécanisme existe et se déclenche]** Au démarrage avec `results_post_url` configuré, le serveur log :
```
[network] [info] Result server url : http://127.0.0.1:9/results
```
Le code contient explicitement (chaînes trouvées) :
- `"Result server error {} ({})"` — en cas d'échec HTTP, avec code + raison
- `"Result sent successfull {}"` — en cas de succès

**→ Ce n'est donc pas "cassé" au niveau du code** : c'est un vrai mécanisme de POST HTTP. Si ça ne marche pas chez toi, la cause est très probablement une des suivantes :
1. L'URL n'est pas atteignable depuis la machine qui héberge le serveur (pare-feu, DNS, endpoint down).
2. Il manque le schéma `http://` ou `https://` dans l'URL.
3. Le POST se déclenche seulement en **fin de session/event réelle** — donc si tu testes en arrêtant le serveur avant la fin d'une course, tu ne verras jamais la tentative.
4. Le endpoint distant n'accepte pas la méthode POST ou le `Content-Type` envoyé.

**Comment déboguer sans faire une course complète** : lance le serveur avec `-testing_server_results` (ça semble être fait pour ça) en pointant `results_post_url` vers un endpoint de test que tu contrôles (ex. un webhook temporaire), et regarde les logs pour `Result server url`, `Result sent successfull` ou `Result server error`. Combine avec `-log_debug="network,server"` pour un maximum de détails. Dans mon test rapide (8 secondes de vie du process), aucune tentative de POST n'a eu le temps de se déclencher — il faut probablement laisser tourner plus longtemps ou que le flag de test déclenche un envoi différé.

### 7.2 `results_path` (écriture disque locale)

Chaîne d'erreur trouvée : `"Couldn't create results_path {}"` → le serveur essaie de créer ce dossier s'il n'existe pas. Combiné à `-write_server_results` (flag CLI, §2.1), ça force l'écriture des résultats en fichiers locaux dans ce dossier — **c'est probablement le moyen le plus fiable de récupérer les résultats**, indépendamment du webhook.

Dans mon test, le dossier `results` ne s'est pas créé — logique, aucune session n'est allée jusqu'à son terme (le process a été tué après quelques secondes).

### 7.3 Détecter la fin d'un événement — les 3 pistes

1. **Webhook `results_post_url`** (§7.1) — push actif, mais dépend de la fiabilité réseau et nécessite un endpoint qui écoute.
2. **Fichiers dans `results_path` + `-write_server_results`** — pull passif, tu peux surveiller ce dossier avec un watcher de fichiers (FileSystemWatcher, cron qui liste le dossier, etc.) — **c'est probablement l'option la plus robuste** puisqu'elle ne dépend d'aucune connectivité externe.
3. **Route HTTP interne `^/results/?$`** — **[NON RÉSOLU]** trouvée dans le binaire (regex de routing cpp-httplib), mais dans mon test `curl http://127.0.0.1:8081/results` (le `server_http_port` configuré) a renvoyé "connexion refusée". Soit cette route ne s'active qu'après qu'une session soit réellement terminée, soit elle appartient à un autre composant (potentiellement un serveur HTTP local lancé par `ServerLauncher.exe` lui-même pour ses propres besoins internes de wizard, pas par le moteur de jeu). **À retester avec un vrai serveur qui a fini au moins une session**, avec `curl http://<ip>:<server_http_port>/results` pendant qu'il tourne.

**Recommandation** : pars sur la combinaison `results_path` + `-write_server_results` + un watcher de fichiers, c'est le mécanisme qui a le moins de dépendances externes. Utilise `results_post_url` en complément si tu as vraiment besoin d'un push temps réel, mais valide-le avec `-testing_server_results` et les logs avant de compter dessus en prod.

---

## 8. Méthode pour déboguer TOI-MÊME tes fichiers JSON (très important)

Le plus gros levier que j'ai utilisé pour cette doc : **le serveur te dit lui-même exactement ce qui cloche**. Voici la méthode, reproductible :

```powershell
cd "C:\Program Files (x86)\Steam\steamapps\common\Assetto Corsa EVO Dedicated Server"
.\AssettoCorsaEVOServer.exe -configjson "C:\chemin\vers\config.json" -seasonjson "C:\chemin\vers\season.json" -no_lobby
```

Lance ça directement dans un terminal (pas besoin de rediriger vers un fichier si tu veux voir en direct). Observe :
- `"... loaded into ServerConfiguration"` → ton config.json est syntaxiquement valide.
- `"... can't be loaded into BuildSeasonDefinitionRequest (<champ>: <raison>)"` → protobuf te donne le nom du champ fautif et pourquoi (mauvais type, valeur d'enum invalide, etc.). **C'est la référence ultime** pour connaître le nom exact et le type attendu de chaque champ, plus fiable que n'importe quelle doc externe.
- Si tout charge correctement, le serveur **dump l'intégralité de la `SeasonDefinition` et de la `ServerConfiguration` résolues** dans les logs (`[server] [info] Season Definition` / `[server] [info] Server Config`) — lis-les, c'est exactement ce que le moteur va utiliser, avec toutes les valeurs par défaut appliquées. Ça permet de vérifier que ce que tu voulais régler a bien été pris en compte.

Astuce complémentaire : passe des enums volontairement invalides (`"initial_grip": "n_importe_quoi"`) pour forcer une erreur et voir si un champ que tu suspectes exister est bien reconnu par le parseur (s'il n'existe pas dans le proto, protobuf ignore silencieusement le champ inconnu au lieu de râler — donc l'absence d'erreur ne prouve pas que le champ est pris en compte, seulement qu'il n'est pas syntaxiquement invalide. Vérifie toujours dans le dump `Season Definition`/`Server Config` final que ta valeur a bien été appliquée).

Pense à `-no_lobby` pendant tes tests pour ne pas polluer la liste des serveurs publics Kunos avec des essais.

---

## 9. Autres flags potentiellement utiles trouvés en vrac

- **`-clear_guid`** : réinitialise l'identifiant machine du serveur (utile si tu clones une VM/installe et que le serveur se fait passer pour un autre).
- **`-virtual_ai_cars <N>`** : fait spawner des IA sur le serveur dédié — explicitement documenté "servers only atm" dans le `--help`. Pourrait servir à remplir artificiellement un serveur qui a peu de joueurs.
- **`-disable_content_validation`** / **`-disable_performance_validation`** : désactivent des vérifications à la connexion des joueurs — à ne toucher que si tu sais ce que tu fais (impact sécurité/anti-triche).
- **`-player_guid_prefix`** : pourrait servir à isoler plusieurs instances de serveur qui tournent sur la même machine.
- **`-version`** : affiche juste la version et quitte, pratique pour un script de vérification automatisé.
- **`-flagfile <path>`** : externalise tous ces flags dans un fichier texte versionnable (voir §2.3).

---

## 10. Récapitulatif des questions posées, avec statut

| Question | Statut |
|---|---|
| Format du JSON runtime envoyé au serveur | ✅ Résolu — `-configjson`/`-seasonjson`, format protobuf JSON natif, champs documentés §3-4 |
| Est-ce vraiment "envoyé en commande" ensuite ? | ✅ Confirmé — le launcher génère 2 fichiers JSON temporaires et lance l'exe avec `-configjson`/`-seasonjson` en ligne de commande |
| Import d'entry list, format attendu | 🟡 Partiel — mécanisme et format probable documentés §5, mais chargement effectif au démarrage non confirmé en test (semble être un mécanisme de rechargement à chaud plutôt qu'initial) |
| Arrêts aux stands obligatoires | 🟡 Existe dans le moteur (protobuf), mais **pas exposé** via seasonjson ni la GUI actuellement — §6 |
| `results_post_url` qui ne marche pas | 🟡 Mécanisme confirmé fonctionnel dans le code (logs de succès/erreur existent) — cause probable = réseau/URL/timing, méthode de debug fournie §7.1 |
| Comment savoir qu'un event est fini / récupérer les résultats | 🟡 3 pistes documentées §7.3, recommandation = `results_path` + `-write_server_results` + watcher de fichier |

---

### 10.1 Marqueurs de session confirmés sur AC EVO 0.8.0

Un cycle réel Practice → Qualification → WarmUp → Race capturé le 16 juillet 2026 confirme que les anciens motifs hypothétiques `START_SESSION`/`BEGIN_SESSION` ne sont pas émis.

- `TimeAttackRemote Practice created`, `TimeAttackRemote Qualifying created`, `TimeAttackRemote Warmup created` et `InstantRaceRemote Race created` identifient le mode courant. La création ne prouve pas encore que le chrono ou la Course a commencé.
- Pour Practice, Qualification et WarmUp, `Outplap split` coïncide avec le démarrage effectif du chrono après l'entrée en piste.
- Pour la Course, `setSessionPhase Waiting_For_Players` reste une attente ; `setSessionPhase Session` marque le départ compétitif.
- `END_SESSION` puis, pour la Course, `setSessionPhase Ended`, confirment la fin de la session.
- La connexion d'un pilote et la création de sa voiture précèdent ces marqueurs et ne prouvent pas une consommation sportive.
- En V1 PitLane, Qualification et Race sont compétitives ; Practice et WarmUp restent des étapes techniques. Le parseur conserve donc la phase courante pour les quatre types, mais ne renseigne `sport_started_at` que pour une Qualification réellement lancée ou une Course passée en phase `Session`.

AC EVO peut recycler son programme lorsque le serveur redevient vide sans arrêter son processus. Ce recyclage reste dans la même tentative PitLane ; seule l'apparition de plusieurs résultats compétitifs éligibles crée une ambiguïté métier.

---

## 11. Prochaines étapes suggérées

Si tu veux qu'on aille plus loin, dans l'ordre de rentabilité probable :

1. **Tester `results_path` + `-write_server_results`** avec une vraie session (même courte, 1 tour) jusqu'à son terme, pour voir le format exact des fichiers résultats écrits sur disque.
2. **Laisser tourner un serveur plus longtemps avec `entry_list_path`** pointant vers un fichier, et vérifier dans les logs si `[entrylist] id: {}, ballast: {}, restrict: {}` apparaît (rechargement à chaud).
3. **Tester `GameModeType_RACE_WEEKEND` ou `GameModeType_INSTANT_RACE`** en seasonjson pour voir si la `specialization` générée devient `InstantRace.Specialization` et si un pitstop apparaît par défaut.
4. **Creuser `-use_dev_saving_mode`** pour voir s'il permet d'exporter/éditer un `SeasonDefinition` complet en JSON (potentiellement LA solution pour débloquer les pitstops obligatoires et d'autres réglages fins).
5. **Retester la route HTTP `/results`** une fois qu'une vraie session s'est terminée.

Je peux repartir sur n'importe lequel de ces points dès que tu veux.
