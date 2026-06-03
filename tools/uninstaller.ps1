#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms

$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

function Add-Info {
    param([string]$Message)
    Write-Host $Message
}

function Find-AcEvoServer {
    $knownPaths = @(
        "C:\SteamCMD\steamapps\common",
        "D:\SteamCMD\steamapps\common",
        "C:\steamcmd\steamapps\common",
        "D:\steamcmd\steamapps\common"
    )

    foreach ($path in $knownPaths) {
        if (-not (Test-Path $path)) { continue }
        $found = Get-ChildItem -Path $path -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 3 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.DirectoryName }
    }

    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 6 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.DirectoryName }
    }

    return $null
}

function Remove-PathSafe {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path $Path)) {
        Add-Info "Introuvable : $Path"
        return
    }

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath -match '^[A-Z]:\\$') {
        Add-Info "SECURITE : refus de supprimer une racine de disque : $fullPath"
        return
    }

    Add-Info "Suppression : $Path"
    try {
        Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
    } catch {
        Add-Info "Remove-Item echoue, tentative via cmd rmdir..."
        & cmd /c rmdir /s /q `"$Path`"
    }
}

$answer = [System.Windows.Forms.MessageBox]::Show(
    "Supprimer PitLane Agent ?`n`nLe service/tache, les regles firewall PitLane, l'agent, les configs et logs seront supprimes.`nLes Results sont conserves.",
    "PitLane Uninstaller",
    "YesNo",
    "Warning"
)

if ($answer -ne "Yes") {
    Add-Info "Annule par utilisateur."
    exit 0
}

Add-Info "=== PitLane uninstaller ==="

$AcEvoPath = Find-AcEvoServer
$AgentPath = if ($AcEvoPath) { Join-Path $AcEvoPath "pitlane-agent" } else { Join-Path $RepoRoot "agent" }

Add-Info "AC EVO : $(if ($AcEvoPath) { $AcEvoPath } else { 'introuvable' })"
Add-Info "Agent  : $AgentPath"

Add-Info "Arret/suppression service PitLaneAgent si present..."
$service = Get-Service -Name "PitLaneAgent" -ErrorAction SilentlyContinue
if ($service) {
    Stop-Service -Name "PitLaneAgent" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    $serviceScript = Join-Path $AgentPath "service.py"
    if (Test-Path $serviceScript) {
        Push-Location $AgentPath
        try {
            python $serviceScript remove
        } finally {
            Pop-Location
        }
    } else {
        sc.exe delete PitLaneAgent | Out-Null
    }
} else {
    Add-Info "Aucun service PitLaneAgent trouve."
}

Add-Info "Arret/suppression tache planifiee PitLaneAgent si presente..."
Stop-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false -ErrorAction SilentlyContinue

Add-Info "Arret des process python PitLane..."
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue |
Where-Object {
    $_.CommandLine -like "*pitlane-agent*" -or
    $_.CommandLine -like "*app.py*" -or
    $_.CommandLine -like "*service.py*"
} |
ForEach-Object {
    Add-Info "Stop process python PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Add-Info "Suppression regles firewall PitLane..."
Get-NetFirewallRule -DisplayName "PitLane*" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

if ($AcEvoPath) {
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ConfigBackupPath = Join-Path $DesktopPath "PitLane AC EVO config backup"

    if (Test-Path "$AcEvoPath\configs") {
        Add-Info "Backup configs -> $ConfigBackupPath"
        New-Item -ItemType Directory -Path $ConfigBackupPath -Force | Out-Null
        Copy-Item -Path "$AcEvoPath\configs\*" -Destination $ConfigBackupPath -Recurse -Force -ErrorAction SilentlyContinue
    }

    Remove-PathSafe "$AcEvoPath\configs"
    Remove-PathSafe "$AcEvoPath\logs"
    Remove-PathSafe "$AcEvoPath\pitlane-agent"
} else {
    Add-Info "AC EVO introuvable, suppression du dossier agent local si present."
    Remove-PathSafe $AgentPath
}

Add-Info "Results conserve volontairement."
Add-Info "Desinstallation terminee."

[System.Windows.Forms.MessageBox]::Show(
    "PitLane Agent a ete desinstalle.`nLes Results sont conserves.",
    "Desinstallation terminee",
    "OK",
    "Information"
) | Out-Null
