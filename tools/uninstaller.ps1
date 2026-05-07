#Requires -RunAsAdministrator

param(
    [switch]$RemoveSteamCmd,
    [switch]$RemoveAcEvoServer,
    [switch]$RemovePythonDeps,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=== PitLane DEV reset test environment ===" -ForegroundColor Cyan
Write-Host ""

function Confirm-DangerousAction {
    param([string]$Message)

    Write-Host ""
    Write-Host $Message -ForegroundColor Red
    $confirm = Read-Host "Tape RESET-PITLANE pour confirmer"

    if ($confirm -ne "RESET-PITLANE") {
        Write-Host "Annulé." -ForegroundColor Yellow
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
    Confirm-DangerousAction "Attention : tu as demandé une suppression avancée."
}

Write-Host "[1] Arrêt de l'agent PitLane" -ForegroundColor Cyan

if (-not $DryRun) {
    Stop-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue |
Where-Object {
    $_.CommandLine -like "*pitlane-agent*" -or $_.CommandLine -like "*app.py*"
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
Write-Host "[2] Suppression tâche planifiée" -ForegroundColor Cyan

if (Get-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue) {
    if ($DryRun) {
        Write-Host "[DRY RUN] Supprimerait la tâche PitLaneAgent" -ForegroundColor DarkYellow
    } else {
        Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false
        Write-Host "Tâche PitLaneAgent supprimée" -ForegroundColor Green
    }
} else {
    Write-Host "Aucune tâche PitLaneAgent trouvée"
}

Write-Host ""
Write-Host "[3] Suppression règles firewall PitLane" -ForegroundColor Cyan

$pitlaneRules = Get-NetFirewallRule -DisplayName "PitLane -*" -ErrorAction SilentlyContinue

if ($pitlaneRules) {
    foreach ($rule in $pitlaneRules) {
        if ($DryRun) {
            Write-Host "[DRY RUN] Supprimerait règle firewall : $($rule.DisplayName)" -ForegroundColor DarkYellow
        } else {
            Write-Host "Suppression règle firewall : $($rule.DisplayName)"
            $rule | Remove-NetFirewallRule
        }
    }
} else {
    Write-Host "Aucune règle firewall PitLane trouvée"
}

Write-Host ""
Write-Host "[4] Détection installations" -ForegroundColor Cyan

$AcEvoPath = Find-AcEvoServer
$SteamCmdExe = Find-SteamCmd

Write-Host "AC EVO   : $AcEvoPath"
Write-Host "SteamCMD : $SteamCmdExe"

Write-Host ""
Write-Host "[5] Suppression agent PitLane" -ForegroundColor Cyan

if ($AcEvoPath) {
    Remove-PathSafe "$AcEvoPath\pitlane-agent"
} else {
    Write-Host "AC EVO introuvable, impossible de déduire le chemin de l'agent"
}

if ($RemoveSteamCmd) {
    Write-Host ""
    Write-Host "[6] Suppression SteamCMD" -ForegroundColor Cyan

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
    Write-Host "[7] Suppression AC EVO Dedicated Server" -ForegroundColor Cyan

    if ($AcEvoPath) {
        Remove-PathSafe $AcEvoPath
    } else {
        Write-Host "AC EVO introuvable"
    }
}

if ($RemovePythonDeps) {
    Write-Host ""
    Write-Host "[8] Suppression dépendances Python PitLane" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host "[DRY RUN] Désinstallerait les dépendances Python PitLane" -ForegroundColor DarkYellow
    } else {
        python -m pip uninstall -y flask flask-cors pyjwt pyyaml requests psutil waitress 2>$null
    }
}

Write-Host ""
Write-Host "Reset terminé." -ForegroundColor Green
