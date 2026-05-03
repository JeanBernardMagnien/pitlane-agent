####################################################################
# PitLane Server Agent — Script d'installation automatique
# Usage : .\install.ps1
####################################################################

$ACEPath     = "C:\ACE"
$AgentPath   = "$ACEPath\pitlane-server-agent"
$ConfigsPath = "$ACEPath\configs"
$ResultsPath = "$ACEPath\Results"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PitLane Server Agent — Installation  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ─── 1. Vérification et mise à jour Python/pip ────────────────────
Write-Host "[1/5] Vérification de Python..." -ForegroundColor Yellow

try {
    $pythonVersion = python --version 2>&1
    Write-Host "      OK : $pythonVersion" -ForegroundColor Green
    Write-Host "      Mise à jour de pip..." -ForegroundColor Yellow
    python -m pip install --upgrade pip --quiet
    Write-Host "      OK : pip à jour" -ForegroundColor Green
} catch {
    Write-Host "      ERREUR : Python introuvable. Installe Python 3.12+ depuis python.org" -ForegroundColor Red
    exit 1
}

# ─── 2. Création des dossiers ─────────────────────────────────────
Write-Host "[2/5] Création des dossiers..." -ForegroundColor Yellow

$folders = @($ConfigsPath, $ResultsPath)
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder | Out-Null
        Write-Host "      Créé : $folder" -ForegroundColor Green
    } else {
        Write-Host "      Déjà existant : $folder" -ForegroundColor Gray
    }
}

# ─── 3. Installation des dépendances Python ───────────────────────
Write-Host "[3/5] Installation des dépendances Python..." -ForegroundColor Yellow

Set-Location $AgentPath
pip install -r requirements.txt --quiet

if ($LASTEXITCODE -eq 0) {
    Write-Host "      OK : dépendances installées" -ForegroundColor Green
} else {
    Write-Host "      ERREUR : pip install a échoué" -ForegroundColor Red
    exit 1
}

# ─── 4. Copie config.example.yml si config.yml absent ─────────────
Write-Host "[4/5] Configuration..." -ForegroundColor Yellow

if (-not (Test-Path "$AgentPath\config.yml")) {
    if (Test-Path "$AgentPath\config.example.yml") {
        Copy-Item "$AgentPath\config.example.yml" "$AgentPath\config.yml"
        Write-Host "      config.yml créé depuis config.example.yml" -ForegroundColor Green
        Write-Host "      /!\ Pense à éditer config.yml (jwt_secret, chemins)" -ForegroundColor Yellow
    } else {
        Write-Host "      ERREUR : config.example.yml introuvable" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "      config.yml déjà présent" -ForegroundColor Gray
}

# ─── 5. Tâche planifiée ───────────────────────────────────────────
Write-Host "[5/5] Installation de la tâche planifiée..." -ForegroundColor Yellow

$taskName = "PitLaneAgent"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "      Ancienne tâche supprimée" -ForegroundColor Gray
}

$action   = New-ScheduledTaskAction -Execute "python" -Argument "$AgentPath\app.py" -WorkingDirectory $AgentPath
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "      OK : tâche '$taskName' créée" -ForegroundColor Green

# ─── 6. Ports firewall Windows ────────────────────────────────────
Write-Host ""
Write-Host "[Bonus] Ouverture des ports firewall Windows..." -ForegroundColor Yellow

# Lit les instances depuis config.yml pour ouvrir les bons ports
$configContent = Get-Content "$AgentPath\config.yml" -Raw
$agentPort = if ($configContent -match 'port:\s*(\d+)') { $matches[1] } else { "8182" }

# Port agent Flask
$ruleName = "PitLane Agent"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $agentPort -Action Allow | Out-Null
    Write-Host "      Port $agentPort (agent Flask) ouvert" -ForegroundColor Green
} else {
    Write-Host "      Port $agentPort déjà ouvert" -ForegroundColor Gray
}

# ─── Résumé ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installation terminée !" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Prochaines étapes :" -ForegroundColor White
Write-Host "  1. Edite config.yml (jwt_secret, chemins)" -ForegroundColor White
Write-Host "  2. Lance : python app.py" -ForegroundColor White
Write-Host "  3. Ajoute ce serveur dans le hub PitLane" -ForegroundColor White
Write-Host ""