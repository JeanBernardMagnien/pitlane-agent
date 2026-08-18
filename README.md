# PitLane Agent

Agent léger installé sur chaque serveur Windows dédié Assetto Corsa EVO.

Il s'enregistre auprès du serveur PitLane via WebSocket, exécute les commandes reçues (démarrage/arrêt d'instances, gestion du firewall, mises à jour SteamCMD) et remonte en temps réel les métriques serveur et l'état des instances.

Le serveur est propriétaire de toute la logique métier — serveurs, instances, ports, presets. L'agent exécute uniquement les effets techniques demandés et observe ce qui se passe réellement sur la machine.

## Prérequis

- Windows Server 2019 / 2022 ou Windows 10/11 (64 bits)
- PowerShell 5.1 ou supérieur
- Droits administrateur
- Accès Internet (téléchargement initial uniquement)

Python 3 et ses dépendances sont installés automatiquement par les scripts si absents.

## Installation rapide

Ouvrir **PowerShell en administrateur** sur le serveur Windows :

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/PitLaneInstaller.exe" `
  -OutFile "$env:USERPROFILE\Downloads\PitLaneInstaller.exe"

Start-Process "$env:USERPROFILE\Downloads\PitLaneInstaller.exe" -Verb RunAs
```

Le launcher détecte l'état du serveur et propose d'installer l'agent seul, l'installation complète, ou la désinstallation.

## Documentation

La documentation complète est centralisée dans le dépôt [`pitlane-docs`](https://github.com/JeanBernardMagnien/pitlane-docs), cloné à côté de celui-ci :

| Sujet | Document |
| --- | --- |
| Installation détaillée, mise à jour, désinstallation, vérification | `../pitlane-docs/repositories/pitlane-agent/installation.md` |
| Fichier `config.yml` | `../pitlane-docs/repositories/pitlane-agent/configuration.md` |
| Protocole, commandes, journal durable | `../pitlane-docs/repositories/pitlane-agent/protocol.md` |
| Pipeline de résultats | `../pitlane-docs/repositories/pitlane-agent/results-pipeline.md` |
| API locale | `../pitlane-docs/repositories/pitlane-agent/local-api.md` |
| Service Windows | `../pitlane-docs/repositories/pitlane-agent/windows-service.md` |
| Installateurs et outils | `../pitlane-docs/repositories/pitlane-agent/installers.md`, `tools.md` |
| Publication | `../pitlane-docs/repositories/pitlane-agent/release.md` |

Point d'entrée : `../pitlane-docs/repositories/pitlane-agent/README.md`.

## Contenu du dépôt

```text
agent/        code de l'agent
contracts/    copie générée du contrat d'échange — ne jamais éditer ici
installers/   scripts PowerShell d'installation
tools/        scripts de maintenance et de test
tests/        suite de tests locale
```

La rétro-ingénierie du serveur dédié AC EVO n'est plus copiée ici : sa source unique est `../pitlane-docs/references/ac-evo/dedicated-server.md`, une référence lourde ouverte uniquement pour une tâche AC EVO.
