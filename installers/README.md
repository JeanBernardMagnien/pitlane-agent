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
  -Uri "https://dl.pitlane-evo.fr/latest/PitLaneInstaller.exe" `
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

```powershell
Invoke-WebRequest `
  -Uri "https://dl.pitlane-evo.fr/latest/setup-agent.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-agent.exe"
```

---

## Telecharger `setup-full`

```powershell
Invoke-WebRequest `
  -Uri "https://dl.pitlane-evo.fr/latest/setup-full.exe" `
  -OutFile "$env:USERPROFILE\Downloads\setup-full.exe"
```

---

## Lancer `setup-agent`

A utiliser si AC EVO Dedicated Server est deja installe.

```powershell
Start-Process "$env:USERPROFILE\Downloads\setup-agent.exe" -Verb RunAs
```

---

## Lancer `setup-full`

A utiliser sur un serveur vierge ou si AC EVO Dedicated Server n'est pas encore installe.

```powershell
Start-Process "$env:USERPROFILE\Downloads\setup-full.exe" -Verb RunAs
```

---

## Notes importantes

* Executer PowerShell en administrateur.
* Les scripts ne necessitent pas Git.
* Les scripts telechargent automatiquement `agent.zip` depuis `https://dl.pitlane-evo.fr/latest/`, un miroir sur notre VPS mis a jour automatiquement a chaque release.
* Le depot GitHub peut rester prive : le telechargement ne passe plus par GitHub, seul le CI y pousse les fichiers apres chaque release.
* Les scripts sont volontairement en ASCII simple pour eviter les problemes d'encodage avec Windows PowerShell 5.1.

---

## Mise en place du miroir de release sur le VPS (une seule fois)

Le CI (`.github/workflows/release.yml`) pousse les assets vers le VPS en SFTP a chaque release taguee (`vX.Y.Z`). Cote VPS :

### 1. Utilisateur de deploiement restreint (chroot SFTP)

```bash
sudo useradd -M -d /srv/pitlane-releases -s /usr/sbin/nologin pitlane-deploy

sudo mkdir -p /srv/pitlane-releases/latest /srv/pitlane-releases/.ssh
sudo chown root:root /srv/pitlane-releases /srv/pitlane-releases/.ssh
sudo chmod 755 /srv/pitlane-releases /srv/pitlane-releases/.ssh
sudo chown pitlane-deploy:pitlane-deploy /srv/pitlane-releases/latest
sudo chmod 755 /srv/pitlane-releases/latest
```

Generer une paire de cles dediee (sur ta machine, pas sur le VPS) et copier la cle publique :

```bash
ssh-keygen -t ed25519 -f pitlane-deploy-key -C "github-actions-pitlane-deploy" -N ""
sudo install -m 644 -o root -g root pitlane-deploy-key.pub /srv/pitlane-releases/.ssh/authorized_keys
```

Dans `/etc/ssh/sshd_config`, ajouter :

```
Match User pitlane-deploy
    ChrootDirectory /srv/pitlane-releases
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
    PasswordAuthentication no
```

Puis `sudo systemctl restart sshd`. Cet utilisateur ne peut rien faire d'autre que deposer des fichiers dans `/srv/pitlane-releases/latest` via SFTP : pas de shell, pas d'acces au reste du serveur, meme si la cle privee fuite.

### 2. Nginx sur `dl.pitlane-evo.fr`

Ajouter un enregistrement DNS `A` pour `dl.pitlane-evo.fr` vers l'IP du VPS, puis :

```nginx
server {
    listen 80;
    server_name dl.pitlane-evo.fr;
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name dl.pitlane-evo.fr;

    ssl_certificate     /etc/letsencrypt/live/dl.pitlane-evo.fr/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dl.pitlane-evo.fr/privkey.pem;

    root /srv/pitlane-releases;
    autoindex off;

    location / {
        try_files $uri =404;
    }
}
```

```bash
sudo certbot --nginx -d dl.pitlane-evo.fr
```

### 3. Secrets GitHub Actions

Dans Settings > Secrets and variables > Actions du repo, ajouter :

| Secret | Valeur |
| --- | --- |
| `DEPLOY_SSH_HOST` | IP ou hostname du VPS |
| `DEPLOY_SSH_USER` | `pitlane-deploy` |
| `DEPLOY_SSH_KEY` | Contenu de la cle privee `pitlane-deploy-key` |
| `DEPLOY_SSH_KNOWN_HOSTS` | Sortie de `ssh-keyscan -t ed25519 dl.pitlane-evo.fr` (a executer une fois depuis un poste de confiance, pour epingler la cle hote et eviter un MITM) |

Une fois ces trois etapes faites, chaque tag `vX.Y.Z` pousse produit la release GitHub **et** met a jour `https://dl.pitlane-evo.fr/latest/` (`agent.zip`, les `.exe` compiles et `version.json`). Le depot GitHub peut alors repasser en prive sans casser aucune installation.
