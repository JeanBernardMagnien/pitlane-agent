#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Stop"
$ReleaseBaseUrl = "https://dl.pitlane-evo.fr/latest"
$DownloadDir = Join-Path $env:USERPROFILE "Downloads\PitLaneAgent"

function Add-Log {
    param([string]$Message)

    if (-not $Message) { return }
    $logBox.AppendText("$Message`r`n")
    $logBox.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
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

function Find-AgentPath {
    param([string]$AcEvoPath)

    $candidates = @()
    if ($AcEvoPath) {
        $candidates += (Join-Path $AcEvoPath "pitlane-agent")
    }

    $candidates += @(
        "C:\PitLaneAgent\pitlane-agent",
        "C:\Program Files\PitLaneAgent\pitlane-agent",
        "C:\ProgramData\PitLaneAgent\pitlane-agent"
    )

    foreach ($path in $candidates) {
        if ((Test-Path (Join-Path $path "app.py")) -or (Test-Path (Join-Path $path "config.yml"))) {
            return $path
        }
    }

    return $null
}

function Find-SteamCmd {
    $knownPaths = @(
        "C:\SteamCMD\steamcmd.exe",
        "D:\SteamCMD\steamcmd.exe",
        "C:\steamcmd\steamcmd.exe",
        "D:\steamcmd\steamcmd.exe"
    )

    foreach ($path in $knownPaths) {
        if (Test-Path $path) { return $path }
    }

    return $null
}

function Get-InstallerState {
    $acEvoPath = Find-AcEvoServer
    $agentPath = Find-AgentPath -AcEvoPath $acEvoPath
    $steamCmd = Find-SteamCmd
    $service = Get-Service -Name "PitLaneAgent" -ErrorAction SilentlyContinue
    $task = Get-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue

    return [pscustomobject]@{
        AcEvoPath = $acEvoPath
        AgentPath = $agentPath
        SteamCmd = $steamCmd
        ServiceStatus = if ($service) { $service.Status.ToString() } else { "absent" }
        TaskPresent = [bool]$task
    }
}

function Update-StateView {
    $state = Get-InstallerState

    $acLabel.Text = "AC EVO : " + $(if ($state.AcEvoPath) { $state.AcEvoPath } else { "introuvable" })
    $agentLabel.Text = "Agent : " + $(if ($state.AgentPath) { $state.AgentPath } else { "introuvable" })
    $steamLabel.Text = "SteamCMD : " + $(if ($state.SteamCmd) { $state.SteamCmd } else { "introuvable" })
    $serviceLabel.Text = "Service : PitLaneAgent " + $state.ServiceStatus
    $taskLabel.Text = "Tache legacy : " + $(if ($state.TaskPresent) { "presente" } else { "absente" })

    if ($state.AcEvoPath) {
        $setupAgentBtn.Enabled = $true
        $setupAgentBtn.Text = "Installer agent seulement"
        $setupFullBtn.Text = "Installation complete"
    } else {
        $setupAgentBtn.Enabled = $false
        $setupAgentBtn.Text = "Installer agent seulement (AC EVO requis)"
        $setupFullBtn.Text = "Installation complete recommandee"
    }

    $resetBtn.Enabled = [bool]($state.AgentPath -or $state.ServiceStatus -ne "absent" -or $state.TaskPresent)

    Add-Log "Etat detecte. AC EVO=$($state.AcEvoPath); Agent=$($state.AgentPath); Service=$($state.ServiceStatus)"
}

function Get-AssetPath {
    param([string]$FileName)

    $localPath = Join-Path $PSScriptRoot $FileName
    if (Test-Path $localPath) {
        Add-Log "Asset local utilise : $localPath"
        return $localPath
    }

    New-Item -ItemType Directory -Path $DownloadDir -Force | Out-Null
    $downloadPath = Join-Path $DownloadDir $FileName
    $url = "$ReleaseBaseUrl/$FileName"

    Add-Log "Telechargement $FileName depuis la release..."
    Invoke-WebRequest -Uri $url -OutFile $downloadPath -UseBasicParsing
    Unblock-File $downloadPath -ErrorAction SilentlyContinue

    return $downloadPath
}

function Start-Asset {
    param([string]$FileName)

    try {
        $path = Get-AssetPath -FileName $FileName
        Add-Log "Lancement : $path"
        Start-Process $path -Verb RunAs
    } catch {
        Add-Log "ERREUR lancement $FileName : $_"
        [System.Windows.Forms.MessageBox]::Show(
            "Impossible de lancer $FileName.`n`n$_",
            "PitLane Installer",
            "OK",
            "Error"
        ) | Out-Null
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane Agent Installer"
$form.Size = New-Object System.Drawing.Size(640, 560)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$form.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "PitLane Agent Installer"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$titleLabel.Location = New-Object System.Drawing.Point(20, 16)
$titleLabel.Size = New-Object System.Drawing.Size(580, 28)
$form.Controls.Add($titleLabel)

$statePanel = New-Object System.Windows.Forms.Panel
$statePanel.Location = New-Object System.Drawing.Point(20, 58)
$statePanel.Size = New-Object System.Drawing.Size(585, 138)
$statePanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$statePanel.BorderStyle = "FixedSingle"
$form.Controls.Add($statePanel)

$stateLabels = @()
$labelTexts = @("AC EVO :", "Agent :", "SteamCMD :", "Service :", "Tache legacy :")
for ($i = 0; $i -lt $labelTexts.Count; $i++) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $labelTexts[$i]
    $label.Location = New-Object System.Drawing.Point(12, (10 + $i * 25))
    $label.Size = New-Object System.Drawing.Size(560, 20)
    $label.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
    $statePanel.Controls.Add($label)
    $stateLabels += $label
}

$acLabel = $stateLabels[0]
$agentLabel = $stateLabels[1]
$steamLabel = $stateLabels[2]
$serviceLabel = $stateLabels[3]
$taskLabel = $stateLabels[4]

$actionsPanel = New-Object System.Windows.Forms.Panel
$actionsPanel.Location = New-Object System.Drawing.Point(20, 210)
$actionsPanel.Size = New-Object System.Drawing.Size(585, 132)
$actionsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$actionsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($actionsPanel)

$setupAgentBtn = New-Object System.Windows.Forms.Button
$setupAgentBtn.Text = "Installer agent seulement"
$setupAgentBtn.Location = New-Object System.Drawing.Point(14, 16)
$setupAgentBtn.Size = New-Object System.Drawing.Size(175, 44)
$setupAgentBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$setupAgentBtn.ForeColor = [System.Drawing.Color]::Black
$setupAgentBtn.FlatStyle = "Flat"
$setupAgentBtn.Add_Click({ Start-Asset -FileName "setup-agent.exe" })
$actionsPanel.Controls.Add($setupAgentBtn)

$setupFullBtn = New-Object System.Windows.Forms.Button
$setupFullBtn.Text = "Installation complete"
$setupFullBtn.Location = New-Object System.Drawing.Point(205, 16)
$setupFullBtn.Size = New-Object System.Drawing.Size(175, 44)
$setupFullBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$setupFullBtn.ForeColor = [System.Drawing.Color]::Black
$setupFullBtn.FlatStyle = "Flat"
$setupFullBtn.Add_Click({ Start-Asset -FileName "setup-full.exe" })
$actionsPanel.Controls.Add($setupFullBtn)

$resetBtn = New-Object System.Windows.Forms.Button
$resetBtn.Text = "Desinstaller / reset"
$resetBtn.Location = New-Object System.Drawing.Point(396, 16)
$resetBtn.Size = New-Object System.Drawing.Size(175, 44)
$resetBtn.BackColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
$resetBtn.ForeColor = [System.Drawing.Color]::Black
$resetBtn.FlatStyle = "Flat"
$resetBtn.Add_Click({ Start-Asset -FileName "uninstaller.exe" })
$actionsPanel.Controls.Add($resetBtn)

$refreshBtn = New-Object System.Windows.Forms.Button
$refreshBtn.Text = "Rafraichir detection"
$refreshBtn.Location = New-Object System.Drawing.Point(14, 78)
$refreshBtn.Size = New-Object System.Drawing.Size(175, 28)
$refreshBtn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
$refreshBtn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$refreshBtn.FlatStyle = "Flat"
$refreshBtn.Add_Click({ Update-StateView })
$actionsPanel.Controls.Add($refreshBtn)

$openFolderBtn = New-Object System.Windows.Forms.Button
$openFolderBtn.Text = "Ouvrir telechargements"
$openFolderBtn.Location = New-Object System.Drawing.Point(205, 78)
$openFolderBtn.Size = New-Object System.Drawing.Size(175, 28)
$openFolderBtn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
$openFolderBtn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$openFolderBtn.FlatStyle = "Flat"
$openFolderBtn.Add_Click({
    New-Item -ItemType Directory -Path $DownloadDir -Force | Out-Null
    Start-Process explorer.exe $DownloadDir
})
$actionsPanel.Controls.Add($openFolderBtn)

$closeBtn = New-Object System.Windows.Forms.Button
$closeBtn.Text = "Fermer"
$closeBtn.Location = New-Object System.Drawing.Point(396, 78)
$closeBtn.Size = New-Object System.Drawing.Size(175, 28)
$closeBtn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
$closeBtn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$closeBtn.FlatStyle = "Flat"
$closeBtn.Add_Click({ $form.Close() })
$actionsPanel.Controls.Add($closeBtn)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 358)
$logBox.Size = New-Object System.Drawing.Size(585, 140)
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$logBox.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
$logBox.Font = New-Object System.Drawing.Font("Consolas", 8)
$form.Controls.Add($logBox)

$form.Add_Shown({
    $form.Activate()
    Update-StateView
})

[System.Windows.Forms.Application]::Run($form)
