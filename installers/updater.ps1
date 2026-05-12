#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$RepoOwner = "JeanBernardMagnien"
$RepoName = "pitlane-agent"
$ReleaseZipUrl = "https://github.com/$RepoOwner/$RepoName/releases/latest/download/agent.zip"
$LatestReleaseApiUrl = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/latest"
$TaskName = "PitLaneAgent"

function Find-AcEvoServer {
    $knownServerPaths = @(
        "C:\SteamCMD\steamapps\common\Assetto Corsa EVO Dedicated Server",
        "D:\SteamCMD\steamapps\common\Assetto Corsa EVO Dedicated Server",
        "C:\steamcmd\steamapps\common\Assetto Corsa EVO Dedicated Server",
        "D:\steamcmd\steamapps\common\Assetto Corsa EVO Dedicated Server",
        "C:\Program Files (x86)\Steam\steamapps\common\Assetto Corsa EVO Dedicated Server",
        "D:\Program Files (x86)\Steam\steamapps\common\Assetto Corsa EVO Dedicated Server"
    )

    foreach ($path in $knownServerPaths) {
        $serverExe = Join-Path $path "AssettoCorsaEVOServer.exe"
        $agentPath = Join-Path $path "pitlane-agent"

        if ((Test-Path $serverExe) -and ((Test-Path (Join-Path $agentPath "app.py")) -or (Test-Path (Join-Path $agentPath "config.yml")))) {
            Add-Log "AC EVO detecte dans chemin connu : $path"
            return $path
        }
    }

    $drives = (Get-PSDrive -PSProvider FileSystem).Root

    foreach ($drive in $drives) {
        Add-Log "Recherche AssettoCorsaEVOServer.exe sur $drive ..."

        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 10 -ErrorAction SilentlyContinue |
            Where-Object {
                $serverPath = $_.DirectoryName
                $agentPath = Join-Path $serverPath "pitlane-agent"

                (Test-Path (Join-Path $agentPath "app.py")) -or
                (Test-Path (Join-Path $agentPath "config.yml"))
            } |
            Select-Object -First 1

        if ($found) {
            Add-Log "AC EVO detecte : $($found.DirectoryName)"
            return $found.DirectoryName
        }
    }

    return $null
}

function Get-AgentPath {
    $knownPaths = @(
        "C:\PitLaneAgent\pitlane-agent",
        "C:\pitlane-agent",
        "C:\Program Files\PitLaneAgent\pitlane-agent",
        "C:\ProgramData\PitLaneAgent\pitlane-agent"
    )

    foreach ($path in $knownPaths) {
        if ((Test-Path (Join-Path $path "app.py")) -or (Test-Path (Join-Path $path "config.yml"))) {
            return $path
        }
    }

    $acEvoPath = Find-AcEvoServer
    if ($acEvoPath) {
        $agentPath = Join-Path $acEvoPath "pitlane-agent"
        if ((Test-Path (Join-Path $agentPath "app.py")) -or (Test-Path (Join-Path $agentPath "config.yml"))) {
            return $agentPath
        }
    }

    return $null
}

function Copy-DirectoryContent {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    Copy-Item -Path (Join-Path $Source "*") -Destination $Destination -Recurse -Force
}

function Backup-LocalFiles {
    param(
        [string]$AgentPath,
        [string]$BackupPath
    )

    foreach ($item in @("config.yml", ".env", "instance_id.txt", "version.json")) {
        $source = Join-Path $AgentPath $item
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination (Join-Path $BackupPath $item) -Force
        }
    }
}

function Restore-LocalFiles {
    param(
        [string]$AgentPath,
        [string]$BackupPath
    )

    foreach ($item in @("config.yml", ".env", "instance_id.txt")) {
        $source = Join-Path $BackupPath $item
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination (Join-Path $AgentPath $item) -Force
        }
    }
}

function Remove-AgentContent {
    param([string]$AgentPath)

    $preserve = @(
        "config.yml",
        ".env",
        "instance_id.txt",
        "version.json",
        "logs",
        "Results",
        "configs",
        "tools"
    )

    Get-ChildItem -Path $AgentPath -Force -ErrorAction SilentlyContinue | ForEach-Object {
        if ($preserve -contains $_.Name) {
            return
        }

        Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction Stop
    }
}

function Stop-AgentTask {
    param([string]$TaskName)

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Add-Log "Tache planifiee $TaskName introuvable, arret ignore"
        return $false
    }

    Add-Log "Arret de la tache planifiee $TaskName"
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    return $true
}

function Start-AgentTask {
    param([string]$TaskName)

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        throw "Tache planifiee $TaskName introuvable, impossible de relancer l'agent."
    }

    Add-Log "Relance de la tache planifiee $TaskName"
    Start-ScheduledTask -TaskName $TaskName
}

function Get-LatestReleaseInfo {
    try {
        return Invoke-RestMethod -Uri $LatestReleaseApiUrl -UseBasicParsing -Headers @{ "User-Agent" = "PitLaneAgentUpdater" }
    } catch {
        Add-Log "Impossible de recuperer les infos de release GitHub : $_"
        return $null
    }
}

function Write-VersionFile {
    param(
        [string]$AgentPath,
        $ReleaseInfo,
        [string]$BackupPath
    )

    $versionPath = Join-Path $AgentPath "version.json"

    $data = [ordered]@{
        installed_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        source = "github_release"
        asset = "agent.zip"
        release_url = $ReleaseZipUrl
        backup_path = $BackupPath
    }

    if ($ReleaseInfo) {
        $data.tag_name = $ReleaseInfo.tag_name
        $data.name = $ReleaseInfo.name
        $data.published_at = $ReleaseInfo.published_at
        $data.html_url = $ReleaseInfo.html_url
    }

    ($data | ConvertTo-Json -Depth 4) | Set-Content -Path $versionPath -Encoding UTF8
    Add-Log "version.json mis a jour"
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane Agent - Mise a jour"
$form.Size = New-Object System.Drawing.Size(620, 610)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$form.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "Mise a jour de PitLane Agent"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$titleLabel.Location = New-Object System.Drawing.Point(20, 14)
$titleLabel.Size = New-Object System.Drawing.Size(560, 28)
$form.Controls.Add($titleLabel)

$stepsPanel = New-Object System.Windows.Forms.Panel
$stepsPanel.Location = New-Object System.Drawing.Point(20, 50)
$stepsPanel.Size = New-Object System.Drawing.Size(560, 250)
$stepsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$stepsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($stepsPanel)

$steps = @(
    "[1] Detection agent installe",
    "[2] Telechargement derniere release",
    "[3] Arret tache PitLaneAgent",
    "[4] Backup agent actuel",
    "[5] Remplacement fichiers agent",
    "[6] Verification dependances Python",
    "[7] Relance tache PitLaneAgent",
    "[8] Termine"
)

$stepLabels = @()
for ($i = 0; $i -lt $steps.Count; $i++) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "WAIT " + $steps[$i]
    $lbl.Location = New-Object System.Drawing.Point(10, (8 + $i * 29))
    $lbl.Size = New-Object System.Drawing.Size(535, 24)
    $lbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $stepsPanel.Controls.Add($lbl)
    $stepLabels += $lbl
}

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 312)
$progressBar.Size = New-Object System.Drawing.Size(560, 16)
$progressBar.Maximum = $steps.Count
$form.Controls.Add($progressBar)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 340)
$logBox.Size = New-Object System.Drawing.Size(560, 155)
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$logBox.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
$logBox.Font = New-Object System.Drawing.Font("Consolas", 8)
$form.Controls.Add($logBox)

$closeBtn = New-Object System.Windows.Forms.Button
$closeBtn.Text = "Fermer"
$closeBtn.Location = New-Object System.Drawing.Point(470, 515)
$closeBtn.Size = New-Object System.Drawing.Size(110, 28)
$closeBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$closeBtn.ForeColor = [System.Drawing.Color]::Black
$closeBtn.FlatStyle = "Flat"
$closeBtn.Visible = $false
$closeBtn.Add_Click({ $form.Close() })
$form.Controls.Add($closeBtn)

function Set-StepStatus {
    param($index, $status)

    $label = $stepLabels[$index]
    $base = $steps[$index]

    switch ($status) {
        "running" { $label.Text = "> $base";     $label.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0) }
        "ok"      { $label.Text = "OK $base";    $label.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136) }
        "error"   { $label.Text = "ERROR $base"; $label.ForeColor = [System.Drawing.Color]::FromArgb(255, 68, 68) }
        "skip"    { $label.Text = "SKIP $base";  $label.ForeColor = [System.Drawing.Color]::FromArgb(110, 118, 129) }
    }

    $progressBar.Value = [Math]::Min($index + 1, $progressBar.Maximum)
    [System.Windows.Forms.Application]::DoEvents()
}

function Add-Log {
    param($msg)

    $logBox.AppendText("$msg`r`n")
    $logBox.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

$form.Add_Shown({
    $form.Activate()

    $agentPath = $null
    $workDir = Join-Path $env:TEMP ("pitlane-agent-update-" + [Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $workDir "agent.zip"
    $extractPath = Join-Path $workDir "extract"
    $localBackupPath = Join-Path $workDir "local-backup"
    $backupRoot = $null
    $releaseInfo = $null

    try {
        Set-StepStatus 0 "running"
        $agentPath = Get-AgentPath

        if (-not $agentPath) {
            throw "Agent PitLane introuvable. Verifie que l'agent est deja installe."
        }

        Add-Log "Agent detecte : $agentPath"
        Set-StepStatus 0 "ok"

        Set-StepStatus 1 "running"
        New-Item -ItemType Directory -Path $workDir -Force | Out-Null
        New-Item -ItemType Directory -Path $extractPath -Force | Out-Null
        New-Item -ItemType Directory -Path $localBackupPath -Force | Out-Null

        $releaseInfo = Get-LatestReleaseInfo
        if ($releaseInfo) {
            Add-Log "Derniere release : $($releaseInfo.tag_name)"
        }

        Add-Log "Telechargement : $ReleaseZipUrl"
        Invoke-WebRequest -Uri $ReleaseZipUrl -OutFile $zipPath -UseBasicParsing
        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

        if (-not (Test-Path (Join-Path $extractPath "requirements.txt")) -and -not (Test-Path (Join-Path $extractPath "app.py"))) {
            throw "Le zip telecharge ne ressemble pas a un agent PitLane valide."
        }

        Set-StepStatus 1 "ok"

        Set-StepStatus 2 "running"
        Stop-AgentTask -TaskName $TaskName | Out-Null
        Set-StepStatus 2 "ok"

        Set-StepStatus 3 "running"
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

        $agentParent = Split-Path $agentPath -Parent
        $backupRoot = Join-Path $agentParent "pitlane-agent-backups\backup-$timestamp"

        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

        Add-Log "Backup vers : $backupRoot"

        Get-ChildItem -Path $agentPath -Force -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Name -eq "backups") {
                return
            }

            Copy-Item -Path $_.FullName -Destination $backupRoot -Recurse -Force
        }

        Backup-LocalFiles -AgentPath $agentPath -BackupPath $localBackupPath
        Set-StepStatus 3 "ok"

        Set-StepStatus 4 "running"
        Add-Log "Suppression fichiers applicatifs existants"
        Remove-AgentContent -AgentPath $agentPath

        Add-Log "Copie nouvelle version"
        Copy-DirectoryContent -Source $extractPath -Destination $agentPath

        Add-Log "Restauration fichiers locaux"
        Restore-LocalFiles -AgentPath $agentPath -BackupPath $localBackupPath
        Write-VersionFile -AgentPath $agentPath -ReleaseInfo $releaseInfo -BackupPath $backupRoot
        Set-StepStatus 4 "ok"

        Set-StepStatus 5 "running"
        $requirementsPath = Join-Path $agentPath "requirements.txt"
        if (Test-Path $requirementsPath) {
            Add-Log "pip install requirements"
            $pipOut = & python -m pip install -r $requirementsPath --quiet 2>&1
            $pipText = ($pipOut | Out-String).Trim()
            if (-not [string]::IsNullOrWhiteSpace($pipText)) {
                Add-Log $pipText
            }
        } else {
            Add-Log "requirements.txt absent, verification dependances ignoree"
        }
        Set-StepStatus 5 "ok"

        Set-StepStatus 6 "running"
        Start-AgentTask -TaskName $TaskName
        Set-StepStatus 6 "ok"

        Set-StepStatus 7 "ok"
        Add-Log "Mise a jour terminee."
        Add-Log "Backup conserve : $backupRoot"

        $releaseLabel = "release inconnue"
        if ($releaseInfo) { $releaseLabel = $releaseInfo.tag_name }

        [System.Windows.Forms.MessageBox]::Show(
            "Mise a jour terminee.`n`nVersion installee : $releaseLabel`nBackup : $backupRoot",
            "PitLane Agent", "OK", "Information"
        ) | Out-Null
    } catch {
        Add-Log "ERREUR : $_"

        for ($i = 0; $i -lt $steps.Count; $i++) {
            if ($stepLabels[$i].Text.StartsWith(">")) {
                Set-StepStatus $i "error"
                break
            }
        }

        if ($agentPath) {
            try {
                Add-Log "Tentative de relance de la tache $TaskName apres erreur"
                Start-AgentTask -TaskName $TaskName
            } catch {
                Add-Log "Relance impossible : $_"
            }
        }

        [System.Windows.Forms.MessageBox]::Show(
            "Echec de la mise a jour : $_",
            "Erreur", "OK", "Error"
        ) | Out-Null
    } finally {
        if (Test-Path $workDir) {
            Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue
        }

        $closeBtn.Visible = $true
        [System.Windows.Forms.Application]::DoEvents()
    }
})

[System.Windows.Forms.Application]::Run($form)