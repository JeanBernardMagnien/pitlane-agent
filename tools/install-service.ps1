#Requires -RunAsAdministrator

param(
    [string]$AgentPath = (Resolve-Path (Join-Path $PSScriptRoot "..\agent")).Path
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $AgentPath)) {
    throw "AgentPath introuvable : $AgentPath"
}

$serviceScript = Join-Path $AgentPath "service.py"
if (-not (Test-Path $serviceScript)) {
    throw "service.py introuvable : $serviceScript"
}

Write-Host "Installation des dependances Python..."
python -m pip install -r (Join-Path $AgentPath "requirements.txt")
python -m pip install pywin32
Write-Host "Verification SQLite standard..."
python -c "import sqlite3; db = sqlite3.connect(':memory:'); db.execute('SELECT 1'); db.close()"
if ($LASTEXITCODE -ne 0) {
    throw "Le module SQLite standard de Python est indisponible."
}

Write-Host "Suppression de l'ancienne tache planifiee si elle existe..."
Stop-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "Suppression de l'ancien service si necessaire..."
$existingService = Get-Service -Name "PitLaneAgent" -ErrorAction SilentlyContinue
if ($existingService) {
    if ($existingService.Status -ne "Stopped") {
        Stop-Service -Name "PitLaneAgent" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    python $serviceScript remove
}

Write-Host "Installation du service Windows PitLaneAgent..."
Push-Location $AgentPath
try {
    python $serviceScript install --startup auto
    python $serviceScript start
} finally {
    Pop-Location
}

Write-Host "Service installe et demarre."
Write-Host "Commandes utiles :"
Write-Host "  Get-Service PitLaneAgent"
Write-Host "  Restart-Service PitLaneAgent"
Write-Host "  Stop-Service PitLaneAgent"
