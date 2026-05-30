# Service Windows natif

Cette branche ajoute un point d'entree `agent/service.py` base sur `pywin32`.

L'objectif est de remplacer progressivement la tache planifiee `PitLaneAgent` par un vrai service Windows.

## Installer ou migrer le service

Ouvrir PowerShell en administrateur depuis la racine du depot ou du package agent, puis lancer :

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\tools\install-service.ps1
```

Le script :

- installe les dependances Python de l'agent ;
- installe `pywin32` ;
- supprime l'ancienne tache planifiee `PitLaneAgent` si elle existe ;
- installe le service Windows `PitLaneAgent` ;
- demarre le service.

Si l'agent est installe ailleurs, passer le chemin explicitement :

```powershell
.\tools\install-service.ps1 -AgentPath "C:\SteamCMD\steamapps\common\Assetto Corsa EVO Dedicated Server\pitlane-agent"
```

## Commandes utiles

```powershell
Get-Service PitLaneAgent
Start-Service PitLaneAgent
Stop-Service PitLaneAgent
Restart-Service PitLaneAgent
```

## Supprimer le service

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\tools\remove-service.ps1
```

Ou avec un chemin explicite :

```powershell
.\tools\remove-service.ps1 -AgentPath "C:\SteamCMD\steamapps\common\Assetto Corsa EVO Dedicated Server\pitlane-agent"
```

## Logs

Le service ecrit ses logs ici :

```text
agent/logs/service.log
```

Les logs metier existants de l'agent restent inchanges.

## Notes de test

A verifier sur Windows :

```powershell
Get-Service PitLaneAgent
Get-Process python -ErrorAction SilentlyContinue
Invoke-WebRequest http://127.0.0.1:8181/api/system
```

La route `/api/system` demande toujours le JWT, donc une reponse `401` est acceptable pour confirmer que l'API repond.
