# Installateurs PitLane Agent

Ce dossier contient les scripts PowerShell permettant d'installer PitLane Agent sur un serveur Windows sans avoir besoin de Git.

## Scripts disponibles

| Script            | Usage                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------ |
| `setup-agent`     | Installer uniquement l'agent PitLane sur un serveur ou AC EVO Dedicated Server est deja installe |
| `setup-full`      | Installer SteamCMD, AC EVO Dedicated Server et PitLane Agent sur un serveur vierge               |

---

## Telecharger les installateurs

Ouvrir PowerShell sur le serveur Windows, puis executer les commandes suivantes.

Les fichiers seront telecharges dans le dossier Windows :

```txt
%USERPROFILE%\Downloads
```

---

## Telecharger `setup-agent.ps1`

Le .exe : 

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-agent.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-agent.exe"
```

ou ps1 :

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-agent.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-agent.exe"
```

---

## Telecharger `setup-full.ps1`

Le .exe : 

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-full.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-full.ps1"
```

ou ps1 :

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-full.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-full.ps1"
```

---

## Telecharger les deux installateurs

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-agent.ps1" `
  -OutFile "$env:USERPROFILE\Downloads\setup-agent.ps1"

Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-full.ps1" `
  -OutFile "$env:USERPROFILE\Downloads\setup-full.ps1"
```

---

## Lancer `setup-agent.ps1`

A utiliser si AC EVO Dedicated Server est deja installe.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\setup-agent.ps1"
```

---

## Lancer `setup-full.ps1`

A utiliser sur un serveur vierge ou si AC EVO Dedicated Server n'est pas encore installe.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\setup-full.ps1"
```

---

## Debloquer les fichiers si necessaire

Si Windows bloque l'execution du script parce qu'il vient d'Internet :

```powershell
Unblock-File "$env:USERPROFILE\Downloads\setup-agent.ps1"
Unblock-File "$env:USERPROFILE\Downloads\setup-full.ps1"
```

Puis relancer le script voulu.

---

## Notes importantes

* Executer PowerShell en administrateur.
* Les scripts ne necessitent pas Git.
* Les scripts telechargent automatiquement `agent.zip` depuis la derniere release GitHub.
* Le depot GitHub doit etre public pour que le telechargement sans authentification fonctionne.
* Les scripts sont volontairement en ASCII simple pour eviter les problemes d'encodage avec Windows PowerShell 5.1.
