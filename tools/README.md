# Outils de developpement

## `uninstaller.ps1`

Outil Windows Forms de desinstallation / reset pour tester les installateurs PitLane sur un serveur Windows, ou remettre proprement une installation de test.

> [!WARNING]
> Outil de developpement / maintenance uniquement.
> Ne pas inclure dans `agent.zip`.

---

## Emplacement dans le repo

```txt
tools/uninstaller.ps1
```

---

## Telecharger `uninstaller.ps1`

Ouvrir PowerShell sur le serveur Windows, puis executer :

Le .exe  

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/tools/uninstaller.exe" `
  -OutFile "$env:USERPROFILE\Downloads\uninstaller.exe"
```
ou le ps1

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/main/tools/uninstaller.ps1" `
  -OutFile "$env:USERPROFILE\Downloads\uninstaller.ps1"
```

Le fichier sera telecharge dans :

```txt
%USERPROFILE%\Downloads
```

---

## Lancement

Ouvrir PowerShell en administrateur, puis lancer :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\uninstaller.ps1"
```

Le script ouvre une interface graphique avec :

* une liste des etapes
* une zone de logs
* une barre de progression
* un bouton `Run reset`
* un bouton `Fermer`
* des cases a cocher pour les suppressions avancees

---

## Debloquer le fichier si necessaire

Si Windows bloque l'execution du script parce qu'il vient d'Internet :

```powershell
Unblock-File "$env:USERPROFILE\Downloads\uninstaller.ps1"
```

Puis relancer :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\uninstaller.ps1"
```

---

## Reset standard

Sans cocher d'option avancee, le bouton `Run reset` supprime :

* l'agent PitLane `pitlane-agent/`
* l'ancien agent legacy `pitlane-server-agent/`
* la tache planifiee `PitLaneAgent`
* les regles firewall prefixees `PitLane -`
* le dossier `logs/`
* le dossier `configs/` apres sauvegarde

Le dossier `configs/` est sauvegarde sur le Bureau dans :

```txt
PitLane AC EVO config backup
```

---

## Ce qui est conserve par defaut

Le reset standard ne supprime pas :

* AC EVO Dedicated Server
* SteamCMD
* Python
* les dependances Python
* le dossier `Results/`

`Results/` est volontairement conserve.

---

## Options dans l'interface

| Option                 | Effet                                                    |
| ---------------------- | -------------------------------------------------------- |
| `Dry run only`         | Affiche les actions prevues sans rien supprimer          |
| `Remove SteamCMD`      | Supprime SteamCMD                                        |
| `Remove AC EVO server` | Supprime le dossier AC EVO Dedicated Server              |
| `Remove Python deps`   | Desinstalle les dependances Python utilisees par PitLane |

---

## Securite

Les suppressions avancees demandent une confirmation via une popup Windows.

Le script ne supprime jamais SteamCMD, AC EVO ou les dependances Python sans option explicite.

---

## Scenarios de test

### Reset standard entre deux tests

1. Lancer `uninstaller.ps1`
2. Ne cocher aucune option avancee
3. Cliquer sur `Run reset`

---

### Simulation sans suppression

1. Lancer `uninstaller.ps1`
2. Cocher `Dry run only`
3. Cliquer sur `Run reset`

---

### Simulation : AC EVO installe, sans SteamCMD

1. Lancer `uninstaller.ps1`
2. Cocher `Remove SteamCMD`
3. Cliquer sur `Run reset`
4. Confirmer la popup

---

### Simulation : SteamCMD installe, sans AC EVO

1. Lancer `uninstaller.ps1`
2. Cocher `Remove AC EVO server`
3. Cliquer sur `Run reset`
4. Confirmer la popup

---

### Simulation : serveur vierge

1. Lancer `uninstaller.ps1`
2. Cocher :

   * `Remove SteamCMD`
   * `Remove AC EVO server`
   * `Remove Python deps`
3. Cliquer sur `Run reset`
4. Confirmer la popup

---

## Note release

Le workflow GitHub Release zippe uniquement le dossier :

```txt
agent/
```

Donc ce script n'est pas inclus dans `agent.zip`.
