#Requires -RunAsAdministrator

<#
PitLane uninstaller / reset tool.

Encoding note:
Save this file as UTF-8 with BOM for Windows PowerShell 5.1.
In VS Code: Save with Encoding > UTF-8 with BOM.

Usage prevu : tests d'installation, maintenance et remise a zero controlee.
Par defaut, le script supprime uniquement :
- l'agent PitLane
- l'ancien agent pitlane-server-agent (legacy install)
- la tache planifiee PitLaneAgent
- les regles firewall prefixees "PitLane -"
- les logs AC EVO
- les configs AC EVO apres backup sur le Bureau

Le dossier Results est conserve.

Les suppressions avancees necessitent des options explicites :
-RemoveSteamCmd
-RemoveAcEvoServer
-RemovePythonDeps
#>

param(
    [switch]$RemoveSteamCmd,
    [switch]$RemoveAcEvoServer,
    [switch]$RemovePythonDeps,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=== PitLane uninstaller / reset tool ===" -ForegroundColor Cyan
Write-Host ""

function Confirm-DangerousAction {
    param([string]$Message)

    Write-Host ""
    Write-Host $Message -ForegroundColor Red
    $confirm = Read-Host "Tape RESET-PITLANE pour confirmer"

    if ($confirm -ne "RESET-PITLANE") {
        Write-Host "Annule." -ForegroundColor Yellow
        exit 1
    }
}

function Remove-PathSafe {
    param([string]$Path)

    if (-not $Path) { return }

    if (Test-Path $Path) {
        if ($DryRun) {
            Write-Host "[DRY RUN] Supprimerait : $Path" -ForegroundColor DarkYellow
        } else {
            Write-Host "Suppression : $Path" -ForegroundColor Yellow
            Remove-Item -Path $Path -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Backup-DirectorySafe {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    if (-not $SourcePath -or -not (Test-Path $SourcePath)) {
        Write-Host "Aucun dossier a sauvegarder : $SourcePath"
        return
    }

    if ($DryRun) {
        Write-Host "[DRY RUN] Sauvegarderait : $SourcePath -> $DestinationPath" -ForegroundColor DarkYellow
        return
    }

    Write-Host "Sauvegarde : $SourcePath -> $DestinationPath" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
    Copy-Item -Path (Join-Path $SourcePath "*") -Destination $DestinationPath -Recurse -Force -ErrorAction SilentlyContinue
}

function Find-AcEvoServer {
    $drives = (Get-PSDrive -PSProvider FileSystem).Root

    foreach ($drive in $drives) {
        Write-Host "Recherche AC EVO sur $drive ..."
        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 6 -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($found) {
            return $found.DirectoryName
        }
    }

    return $null
}

function Find-SteamCmd {
    $drives = (Get-PSDrive -PSProvider FileSystem).Root

    foreach ($drive in $drives) {
        Write-Host "Recherche steamcmd.exe sur $drive ..."
        $found = Get-ChildItem -Path $drive -Filter "steamcmd.exe" `
            -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($found) {
            return $found.FullName
        }
    }

    return $null
}

if ($RemoveSteamCmd -or $RemoveAcEvoServer -or $RemovePythonDeps) {
    Confirm-DangerousAction "Attention : tu as demande une suppression avancee. SteamCMD, AC EVO ou des dependances Python peuvent etre supprimes."
}

Write-Host "[1] Arret de l'agent PitLane" -ForegroundColor Cyan

if (-not $DryRun) {
    Stop-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue |
Where-Object {
    $_.CommandLine -like "*pitlane-agent*" -or
    $_.CommandLine -like "*pitlane-server-agent*" -or
    $_.CommandLine -like "*app.py*"
} |
ForEach-Object {
    if ($DryRun) {
        Write-Host "[DRY RUN] Stopperait process python PID $($_.ProcessId)" -ForegroundColor DarkYellow
    } else {
        Write-Host "Stop process python PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "[2] Suppression tache planifiee" -ForegroundColor Cyan

if (Get-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue) {
    if ($DryRun) {
        Write-Host "[DRY RUN] Supprimerait la tache PitLaneAgent" -ForegroundColor DarkYellow
    } else {
        Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false
        Write-Host "Tache PitLaneAgent supprimee" -ForegroundColor Green
    }
} else {
    Write-Host "Aucune tache PitLaneAgent trouvee"
}

Write-Host ""
Write-Host "[3] Suppression regles firewall PitLane" -ForegroundColor Cyan

$pitlaneRules = Get-NetFirewallRule -DisplayName "PitLane -*" -ErrorAction SilentlyContinue

if ($pitlaneRules) {
    foreach ($rule in $pitlaneRules) {
        if ($DryRun) {
            Write-Host "[DRY RUN] Supprimerait regle firewall : $($rule.DisplayName)" -ForegroundColor DarkYellow
        } else {
            Write-Host "Suppression regle firewall : $($rule.DisplayName)"
            $rule | Remove-NetFirewallRule
        }
    }
} else {
    Write-Host "Aucune regle firewall PitLane trouvee"
}

Write-Host ""
Write-Host "[4] Detection installations" -ForegroundColor Cyan

$AcEvoPath = Find-AcEvoServer
$SteamCmdExe = Find-SteamCmd

Write-Host "AC EVO   : $AcEvoPath"
Write-Host "SteamCMD : $SteamCmdExe"

Write-Host ""
Write-Host "[5] Backup configs et nettoyage fichiers generes" -ForegroundColor Cyan

if ($AcEvoPath) {
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ConfigBackupPath = Join-Path $DesktopPath "PitLane AC EVO config backup"

    Backup-DirectorySafe -SourcePath "$AcEvoPath\configs" -DestinationPath $ConfigBackupPath
    Remove-PathSafe "$AcEvoPath\configs"
    Remove-PathSafe "$AcEvoPath\logs"
} else {
    Write-Host "AC EVO introuvable, impossible de nettoyer configs/logs"
}

Write-Host ""
Write-Host "[6] Suppression agent PitLane" -ForegroundColor Cyan

if ($AcEvoPath) {
    Remove-PathSafe "$AcEvoPath\pitlane-agent"
    Remove-PathSafe "$AcEvoPath\pitlane-server-agent"
} else {
    Write-Host "AC EVO introuvable, impossible de deduire le chemin de l'agent"
}

if ($RemoveSteamCmd) {
    Write-Host ""
    Write-Host "[7] Suppression SteamCMD" -ForegroundColor Cyan

    if ($SteamCmdExe) {
        $SteamCmdDir = Split-Path $SteamCmdExe
        Remove-PathSafe $SteamCmdDir
    } else {
        Write-Host "steamcmd.exe introuvable"
    }

    Remove-PathSafe "C:\SteamCMD"
}

if ($RemoveAcEvoServer) {
    Write-Host ""
    Write-Host "[8] Suppression AC EVO Dedicated Server" -ForegroundColor Cyan

    if ($AcEvoPath) {
        Remove-PathSafe $AcEvoPath
    } else {
        Write-Host "AC EVO introuvable"
    }
}

if ($RemovePythonDeps) {
    Write-Host ""
    Write-Host "[9] Suppression dependances Python PitLane" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host "[DRY RUN] Desinstallerait les dependances Python PitLane" -ForegroundColor DarkYellow
    } else {
        python -m pip uninstall -y flask flask-cors pyjwt pyyaml requests psutil waitress 2>$null
    }
}

Write-Host ""
Write-Host "Results conserve volontairement." -ForegroundColor Green
Write-Host "Desinstallation / reset termine." -ForegroundColor Green
Write-Host ""
Read-Host "Appuie sur Entree pour fermer"
