#Requires -RunAsAdministrator

param(
    [string]$AgentPath = (Resolve-Path (Join-Path $PSScriptRoot "..\agent")).Path
)

$ErrorActionPreference = "Continue"

$serviceScript = Join-Path $AgentPath "service.py"

if (Get-Service -Name "PitLaneAgent" -ErrorAction SilentlyContinue) {
    Write-Host "Arret du service PitLaneAgent..."
    Stop-Service -Name "PitLaneAgent" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    if (Test-Path $serviceScript) {
        Write-Host "Suppression du service via pywin32..."
        Push-Location $AgentPath
        try {
            python $serviceScript remove
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "service.py introuvable, suppression via sc.exe..."
        sc.exe delete PitLaneAgent | Out-Null
    }
} else {
    Write-Host "Aucun service PitLaneAgent trouve."
}
