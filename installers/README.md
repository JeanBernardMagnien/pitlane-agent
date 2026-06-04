# Installateurs PitLane Agent

Ce dossier contient les scripts PowerShell permettant d'installer PitLane Agent sur un serveur Windows sans avoir besoin de Git.

## Scripts disponibles

| Script            | Usage                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------ |
| `setup-agent`     | Installer uniquement l'agent PitLane sur un serveur ou AC EVO Dedicated Server est deja installe |
| `setup-full`      | Installer SteamCMD, AC EVO Dedicated Server et PitLane Agent sur un serveur vierge               |

---

## Installateur recommande

Telecharger et lancer le launcher unique :

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/PitLaneInstaller.exe" `
  -OutFile "$env:USERPROFILE\Downloads\PitLaneInstaller.exe"

Start-Process "$env:USERPROFILE\Downloads\PitLaneInstaller.exe" -Verb RunAs
```

Le launcher detecte AC EVO, SteamCMD, l'agent et le service Windows, puis propose l'installation agent, l'installation complete ou la desinstallation/reset.

---

## Telecharger les installateurs

Ouvrir PowerShell sur le serveur Windows, puis executer les commandes suivantes.

Les fichiers seront telecharges dans le dossier Windows :

```txt
%USERPROFILE%\Downloads
```

---

## Telecharger `setup-agent`

Le .exe :

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/setup-agent.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-agent.exe"
```

Ou le ps1 :

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-agent.ps1" `
  -OutFile "$env:USERPROFILE\Downloads\setup-agent.ps1"
```

---

## Telecharger `setup-full`

Le .exe :

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/setup-full.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-full.exe"
```

Ou le ps1 :

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/installers/setup-full.ps1" `
  -OutFile "$env:USERPROFILE\Downloads\setup-full.ps1"
```

---

## Lancer `setup-agent`

A utiliser si AC EVO Dedicated Server est deja installe.

```powershell
Start-Process "$env:USERPROFILE\Downloads\setup-agent.exe" -Verb RunAs
```

Ou pour le ps1 :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\setup-agent.ps1"
```

---

## Lancer `setup-full`

A utiliser sur un serveur vierge ou si AC EVO Dedicated Server n'est pas encore installe.

```powershell
Start-Process "$env:USERPROFILE\Downloads\setup-full.exe" -Verb RunAs
```

Ou pour le ps1 :

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
