# Outils de développement

## `uninstaller.ps1`t Script de désinstallation / reset pour tester les installateurs PitLane sur un serveur Windows, ou remettre proprement une installation de test.ur Windows, ou reOutil de développement / maintenance uniquement. de test.

> [!WARNING]
> Outil de développement / maintenance uniqtools/uninstaller.ps1ans `agent.## Ce que fait la désinstallation standardxt
> tools/uninstaller.ps1

````

---

## Ce que fait le reset standard

Commande :

```powershell
.\tools\dev-reset-test-env.ps1
````

Supprime uniquement :

* l’agent PitLane
* la tâche planifiée `PitLaneAgent`
* les règles firewall préfixées `PitLane -`

Ne supprime pas :

* AC EVO Dedicated Server
* SteamCMD
* Python
* les dépendances Python

---

## Mode simulation

Permet de voir ce qui serait supprimé sans rien supprimer réellement.

```powershell
.\tools\dev-reset-test-env.ps1 -DryRun
```

---

## Simulation : AC EVO installé, sans SteamCMD

```powershell
.\tools\dev-reset-test-env.ps1 -RemoveSteamCmd
```

---

## Simulation : SteamCMD installé, sans AC EVO

```powershell
.\tools\dev-reset-test-env.ps1 -RemoveAcEvoServer
```

---

## Simulation : serveur vierge

```powershell
.\tools\dev-reset-test-env.ps1 -RemoveSteamCmd -RemoveAcEvoServer -RemovePythonDeps
```

---

## Options disponibles

| Option               | Effet                                                    |
| -------------------- | -------------------------------------------------------- |
| `-DryRun`            | Affiche les suppressions prévues sans rien supprimer     |
| `-RemoveSteamCmd`    | Supprime SteamCMD                                        |
| `-RemoveAcEvoServer` | Supprime AC EVO Dedicated Server                         |
| `-RemovePythonDeps`  | Désinstalle les dépendances Python utilisées par PitLane |

---

## Sécurité

Les suppressions avancées demandent une confirmation manuelle :

```txt
RESET-PITLANE
```

Le script ne supprime jamais SteamCMD, AC EVO ou les déDésinstallation standard : sans option explicite.

---

## Exemples rapides

Reset stanshell
.\tools\dev-reset-test-env.ps1

````

Reset complet serveur vierge :

```powershell
.\tools\dev-reset-test-env.ps1 -RemoveSteamCmd -RemoveAcEvoServer -RemovePythonDeps
````

Test sans rien supprimer :

```powershell
.\tools\dev-reset-test-env.ps1 -DryRun
```

---

## Note release

Le workflow GitHub Release zippe uniquement le dossier :

```txt
agent/
```

Donc ce script n’est pas inclus dans `agent.zip`.
