#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Utility functions

function Find-AcEvoServer {
    param([string]$SearchRoot)

    $root = if ($SearchRoot) { $SearchRoot } else { $null }

    if ($root) {
        $found = Get-ChildItem -Path $root -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 6 -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($found) { return $found.DirectoryName }
        return $null
    }

    # Recherche globale sur tous les disques
    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 6 -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($found) { return $found.DirectoryName }
    }

    return $null
}

function Get-AppManifestPath {
    param([string]$SteamCmdDir)
    return Join-Path $SteamCmdDir "steamapps\appmanifest_4564210.acf"
}

function Find-SteamCmd {
    Add-Log "Recherche steamcmd.exe dans les chemins connus..."

    $knownPaths = @(
        "C:\SteamCMD\steamcmd.exe",
        "D:\SteamCMD\steamcmd.exe",
        "C:\steamcmd\steamcmd.exe",
        "D:\steamcmd\steamcmd.exe"
    )

    foreach ($path in $knownPaths) {
        if (Test-Path $path) {
            Add-Log "steamcmd.exe trouve : $path"
            return $path
        }
    }

    Add-Log "steamcmd.exe non trouve dans les chemins connus."
    Add-Log "Recherche sur les disques, cela peut prendre quelques secondes..."

    $drives = (Get-PSDrive -PSProvider FileSystem).Root

    foreach ($drive in $drives) {
        Add-Log "Recherche steamcmd.exe sur $drive ..."

        $found = Get-ChildItem -Path $drive -Filter "steamcmd.exe" `
            -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($found) {
            Add-Log "steamcmd.exe trouve : $($found.FullName)"
            return $found.FullName
        }
    }

    Add-Log "Aucun steamcmd.exe trouve."
    return $null
}

function Download-Agent {
    param($DestinationPath)

    $url = "https://dl.pitlane-evo.fr/latest/agent.zip"
    $zip = "$env:TEMP\pitlane-agent.zip"

    if (Test-Path $DestinationPath) {
        Remove-Item -Path $DestinationPath -Recurse -Force -ErrorAction SilentlyContinue
    }

    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null

    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $DestinationPath -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}

function Install-AgentUpdater {
    param([string]$AgentPath)

    $url = "https://dl.pitlane-evo.fr/latest/updater.exe"
    $toolsPath = Join-Path $AgentPath "tools"
    $updaterPath = Join-Path $toolsPath "PitLaneAgentUpdater.exe"

    New-Item -ItemType Directory -Path $toolsPath -Force | Out-Null

    Invoke-WebRequest `
        -Uri $url `
        -OutFile $updaterPath `
        -UseBasicParsing
}


function Invoke-LoggedPython {
    param([string[]]$Arguments)

    $out = & python @Arguments 2>&1
    $text = ($out | Out-String).Trim()
    if (-not [string]::IsNullOrWhiteSpace($text)) {
        Add-Log $text
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Commande python echouee ($LASTEXITCODE): python $($Arguments -join ' ')"
    }
}

function Install-AgentService {
    param([string]$AgentPath)

    $serviceScript = Join-Path $AgentPath "service.py"
    if (-not (Test-Path $serviceScript)) {
        throw "service.py introuvable dans l'agent telecharge : $serviceScript"
    }

    Add-Log "Suppression ancienne tache planifiee PitLaneAgent si presente"
    Stop-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false -ErrorAction SilentlyContinue

    $existingService = Get-Service -Name "PitLaneAgent" -ErrorAction SilentlyContinue
    if ($existingService) {
        Add-Log "Suppression ancien service PitLaneAgent"
        if ($existingService.Status -ne "Stopped") {
            Stop-Service -Name "PitLaneAgent" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }

        Push-Location $AgentPath
        try {
            Invoke-LoggedPython -Arguments @($serviceScript, "remove")
        } catch {
            Add-Log "Suppression via service.py echouee, fallback sc.exe delete"
            sc.exe delete PitLaneAgent | Out-Null
        } finally {
            Pop-Location
        }
    }

    Add-Log "pip install pywin32"
    Invoke-LoggedPython -Arguments @("-m", "pip", "install", "pywin32", "--quiet")

    Add-Log "Installation service Windows PitLaneAgent"
    Push-Location $AgentPath
    try {
        Invoke-LoggedPython -Arguments @($serviceScript, "install", "--startup", "auto")
        Invoke-LoggedPython -Arguments @($serviceScript, "start")
    } finally {
        Pop-Location
    }

    Add-Log "Service PitLaneAgent installe et demarre"
}

function New-JwtSecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Get-PublicIp {
    try {
        $ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).Content.Trim()

        if ([string]::IsNullOrWhiteSpace($ip)) {
            return "IP_A_REMPLACER"
        }

        return $ip
    } catch {
        return "IP_A_REMPLACER"
    }
}

function Add-LogSafe {
    param(
        [System.Windows.Forms.TextBox]$LogBox,
        [string]$Message
    )

    if (-not $Message) { return }
    $LogBox.AppendText("$Message`r`n")
    $LogBox.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

# Main UI

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane - Installation complete"
$form.Size = New-Object System.Drawing.Size(680, 790)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$form.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "Installation complete - steamcmd + AC EVO + Agent"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$titleLabel.Location = New-Object System.Drawing.Point(20, 14)
$titleLabel.Size = New-Object System.Drawing.Size(630, 26)
$form.Controls.Add($titleLabel)

$stepsPanel = New-Object System.Windows.Forms.Panel
$stepsPanel.Location = New-Object System.Drawing.Point(20, 50)
$stepsPanel.Size = New-Object System.Drawing.Size(630, 395)
$stepsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$stepsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($stepsPanel)

$steps = @(
    "[1] Detection SteamCMD",
    "[2] Installation SteamCMD si absent",
    "[3] Dossier AC EVO",
    "[4] Saisie credentials Steam",
    "[5] Telechargement AC EVO",
    "[6] Installation agent",
    "[7] Verification Python",
    "[8] Installation dependances",
    "[9] Generation config.yml",
    "[10] Service Windows natif",
    "[11] Regle firewall API agent",
    "[12] Termine"
)

$stepLabels = @()
for ($i = 0; $i -lt $steps.Count; $i++) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "WAIT " + $steps[$i]
    $lbl.Location = New-Object System.Drawing.Point(10, (4 + $i * 32))
    $lbl.Size = New-Object System.Drawing.Size(610, 26)
    $lbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $stepsPanel.Controls.Add($lbl)
    $stepLabels += $lbl
}

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 453)
$progressBar.Size = New-Object System.Drawing.Size(630, 16)
$progressBar.Maximum = $steps.Count
$form.Controls.Add($progressBar)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 478)
$logBox.Size = New-Object System.Drawing.Size(630, 145)
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$logBox.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
$logBox.Font = New-Object System.Drawing.Font("Consolas", 8)
$form.Controls.Add($logBox)

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
    Add-LogSafe -LogBox $logBox -Message $msg
}

$closeBtn = New-Object System.Windows.Forms.Button
$closeBtn.Text = "Fermer"
$closeBtn.Location = New-Object System.Drawing.Point(540, 730)
$closeBtn.Size = New-Object System.Drawing.Size(110, 28)
$closeBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$closeBtn.ForeColor = [System.Drawing.Color]::Black
$closeBtn.FlatStyle = "Flat"
$closeBtn.Visible = $false
$closeBtn.Add_Click({ $form.Close() })
$form.Controls.Add($closeBtn)

# Installation

$form.Add_Shown({
    $form.Activate()

    # [0] Pre-check AC EVO
    Add-Log "Verification presence AC EVO..."
    $existing = Find-AcEvoServer

    if ($existing) {
        Set-StepStatus 0 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "AC EVO Dedicated Server deja detecte ($existing).`nLance setup-agent.ps1 pour installer uniquement l'agent.",
            "Erreur", "OK", "Error"
        )
        return
    }

    Add-Log "AC EVO absent, installation complete possible."

    # [1] Detection SteamCMD
    Set-StepStatus 0 "running"
    $SteamCmdExe = Find-SteamCmd

    if ($SteamCmdExe) {
        $SteamCmdDir = Split-Path $SteamCmdExe
        Add-Log "SteamCMD reutilise : $SteamCmdExe"
        Set-StepStatus 0 "ok"
        Set-StepStatus 1 "skip"
    } else {
        Add-Log "steamcmd.exe absent - installation automatique requise"
        Set-StepStatus 0 "ok"

        # [2] Installation SteamCMD si absent
        Set-StepStatus 1 "running"
        $SteamCmdDir = "C:\SteamCMD"
        $SteamCmdExe = Join-Path $SteamCmdDir "steamcmd.exe"

        try {
            Add-Log "Installation steamcmd dans $SteamCmdDir"
            New-Item -ItemType Directory -Path $SteamCmdDir -Force | Out-Null
            $zip = "$env:TEMP\steamcmd.zip"

            Invoke-WebRequest -Uri "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" `
                -OutFile $zip -UseBasicParsing

            Expand-Archive -Path $zip -DestinationPath $SteamCmdDir -Force
            Remove-Item $zip -Force -ErrorAction SilentlyContinue

            if (-not (Test-Path $SteamCmdExe)) {
                throw "steamcmd.exe introuvable apres extraction : $SteamCmdExe"
            }

            Add-Log "steamcmd installe : $SteamCmdExe"
            Set-StepStatus 1 "ok"
        } catch {
            Set-StepStatus 1 "error"
            [System.Windows.Forms.MessageBox]::Show(
                "Erreur installation steamcmd : $_",
                "Erreur", "OK", "Error"
            )
            return
        }
    }

    # [3] Dossier AC EVO - sera resolu dynamiquement apres telechargement
    Set-StepStatus 2 "running"
    Add-Log "Dossier AC EVO sera resolu apres telechargement SteamCMD."
    Set-StepStatus 2 "ok"

    # [4] Saisie credentials Steam
    Set-StepStatus 3 "running"
    $credForm = New-Object System.Windows.Forms.Form
    $credForm.Text = "Credentials Steam"
    $credForm.Size = New-Object System.Drawing.Size(400, 220)
    $credForm.StartPosition = "CenterScreen"
    $credForm.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
    $credForm.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
    $credForm.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $credForm.FormBorderStyle = "FixedDialog"
    $credForm.MaximizeBox = $false

    $noteLbl = New-Object System.Windows.Forms.Label
    $noteLbl.Text = "Ces identifiants sont utilises une seule fois et ne sont jamais stockes."
    $noteLbl.Location = New-Object System.Drawing.Point(12, 12)
    $noteLbl.Size = New-Object System.Drawing.Size(365, 32)
    $noteLbl.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
    $credForm.Controls.Add($noteLbl)

    $userLbl = New-Object System.Windows.Forms.Label
    $userLbl.Text = "Nom d'utilisateur Steam :"
    $userLbl.Location = New-Object System.Drawing.Point(12, 54)
    $userLbl.Size = New-Object System.Drawing.Size(170, 20)
    $credForm.Controls.Add($userLbl)

    $userTxt = New-Object System.Windows.Forms.TextBox
    $userTxt.Location = New-Object System.Drawing.Point(185, 52)
    $userTxt.Size = New-Object System.Drawing.Size(185, 22)
    $userTxt.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
    $userTxt.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
    $userTxt.BorderStyle = "FixedSingle"
    $credForm.Controls.Add($userTxt)

    $passLbl = New-Object System.Windows.Forms.Label
    $passLbl.Text = "Mot de passe Steam :"
    $passLbl.Location = New-Object System.Drawing.Point(12, 100)
    $passLbl.Size = New-Object System.Drawing.Size(170, 20)
    $credForm.Controls.Add($passLbl)

    $passTxt = New-Object System.Windows.Forms.TextBox
    $passTxt.Location = New-Object System.Drawing.Point(185, 98)
    $passTxt.Size = New-Object System.Drawing.Size(185, 22)
    $passTxt.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
    $passTxt.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
    $passTxt.BorderStyle = "FixedSingle"
    $passTxt.PasswordChar = '*'
    $credForm.Controls.Add($passTxt)

    $okBtn = New-Object System.Windows.Forms.Button
    $okBtn.Text = "Continuer"
    $okBtn.DialogResult = "OK"
    $okBtn.Location = New-Object System.Drawing.Point(270, 148)
    $okBtn.Size = New-Object System.Drawing.Size(100, 28)
    $okBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
    $okBtn.ForeColor = [System.Drawing.Color]::Black
    $okBtn.FlatStyle = "Flat"
    $credForm.Controls.Add($okBtn)
    $credForm.AcceptButton = $okBtn

    if ($credForm.ShowDialog() -ne "OK") { $form.Close(); return }

    $steamUser = $userTxt.Text
    $steamPass = $passTxt.Text
    $passTxt.Text = ""
    Add-Log "Credentials saisis"
    Set-StepStatus 3 "ok"

    # [5] Telechargement AC EVO via steamcmd
    Set-StepStatus 4 "running"
    Add-Log "Lancement steamcmd +app_update 4564210 validate"
    Add-Log "Une fenetre SteamCMD va s'ouvrir - validez le Steam Guard sur votre telephone si demande, puis attendez la fin du telechargement."

    $steamArgs = "+login `"$steamUser`" `"$steamPass`" +app_update 4564210 validate +quit"
    $steamUser = $null
    $steamPass = $null

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName        = $SteamCmdExe
    $psi.Arguments       = $steamArgs
    $psi.UseShellExecute = $true   # fenetre visible = Steam Guard peut interagir
    $psi.CreateNoWindow  = $false

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()

    # Attendre la fin sans bloquer le form
    while (-not $proc.HasExited) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 500
    }

    $proc.WaitForExit()

    # Chercher d'abord dans SteamCMD (cas nominal)
    $AcEvoPath = Find-AcEvoServer -SearchRoot $SteamCmdDir

    # Si pas trouvé, fallback recherche globale (cas Steam client ou install ailleurs)
    if (-not $AcEvoPath) {
        Add-Log "AC EVO non trouve dans SteamCMD, recherche globale..."
        $AcEvoPath = Find-AcEvoServer -SearchRoot $null
    }

    if (-not $AcEvoPath) {
        Set-StepStatus 4 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "SteamCMD a echoue (code $($proc.ExitCode)). Verifie les credentials Steam ou Steam Guard.",
            "Erreur SteamCMD", "OK", "Error"
        )
        return
    }

    $AgentPath = Join-Path $AcEvoPath "pitlane-agent"
    Add-Log "Dossier AC EVO resolu : $AcEvoPath"
    Set-StepStatus 4 "ok"

    # [6] Installation agent
    Set-StepStatus 5 "running"
    try {
        Download-Agent -DestinationPath $AgentPath
        Install-AgentUpdater -AgentPath $AgentPath
        Add-Log "Agent installe : $AgentPath"
        Set-StepStatus 5 "ok"
    } catch {
        Set-StepStatus 5 "error"
        [System.Windows.Forms.MessageBox]::Show("Erreur agent : $_", "Erreur", "OK", "Error")
        return
    }

    # [7] Verification Python
    Set-StepStatus 6 "running"
    $python = Get-Command python -ErrorAction SilentlyContinue

    if (-not $python) {
        Add-Log "Python absent - installation via winget"
        winget install Python.Python.3 --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Add-Log "Python trouve : $($python.Source)"
    }

    Set-StepStatus 6 "ok"

    # [8] Installation dependances
    Set-StepStatus 7 "running"
    Add-Log "pip install requirements"
    Invoke-LoggedPython -Arguments @("-m", "pip", "install", "-r", "$AgentPath\requirements.txt", "--quiet")
    Set-StepStatus 7 "ok"

    # [9] Generation config.yml
    Set-StepStatus 8 "running"
    $JwtSecret       = New-JwtSecret
    $publicIp        = Get-PublicIp
    $BaseUrl         = "http://$publicIp"
    $AgentUrl        = "http://$publicIp`:8181"
    $AppManifestPath = Get-AppManifestPath -SteamCmdDir $SteamCmdDir

    $configContent = Get-Content "$AgentPath\config.template.yml" -Raw
    $configContent = $configContent.Replace("__BASE_URL__",         $BaseUrl)
    $configContent = $configContent.Replace("__INSTALL_PATH__",     $AcEvoPath)
    $configContent = $configContent.Replace("__CONFIGS_PATH__",     "$AcEvoPath\configs")
    $configContent = $configContent.Replace("__RESULTS_PATH__",     "$AcEvoPath\Results")
    $configContent = $configContent.Replace("__LOGS_PATH__",        "$AcEvoPath\logs")
    $configContent = $configContent.Replace("__STEAMCMD_PATH__",    $SteamCmdExe)
    $configContent = $configContent.Replace("__APPMANIFEST_PATH__", $AppManifestPath)
    $configContent = $configContent.Replace("__JWT_SECRET__",       $JwtSecret)
    Set-Content -Path "$AgentPath\config.yml" -Value $configContent -Encoding UTF8
    Remove-Item "$AgentPath\config.template.yml" -Force -ErrorAction SilentlyContinue

    foreach ($dir in @("$AcEvoPath\configs", "$AcEvoPath\Results", "$AcEvoPath\logs")) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir | Out-Null
        }
    }

    Add-Log "config.yml genere"
    Add-Log "config.template.yml supprime"
    Set-StepStatus 8 "ok"

    # [10] Service Windows natif
    Set-StepStatus 9 "running"
    try {
        Install-AgentService -AgentPath $AgentPath
        Set-StepStatus 9 "ok"
    } catch {
        Set-StepStatus 9 "error"
        [System.Windows.Forms.MessageBox]::Show("Erreur installation service : $_", "Erreur", "OK", "Error")
        return
    }

    # [11] Regle firewall API agent
    Set-StepStatus 10 "running"

    Get-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue

    New-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -Direction Inbound `
        -Protocol TCP -LocalPort 8181 -Action Allow `
        -ErrorAction SilentlyContinue | Out-Null
    Add-Log "Firewall : TCP/8181 ouvert (PitLane - Agent API 8181)"
    Add-Log "Les ports d'instances seront geres par le hub lors de la creation/modification/suppression."

    Set-StepStatus 10 "ok"

    # [12] Resume
    Set-StepStatus 11 "ok"

    $summaryBox = New-Object System.Windows.Forms.Panel
    $summaryBox.Location = New-Object System.Drawing.Point(20, 635)
    $summaryBox.Size = New-Object System.Drawing.Size(630, 72)
    $summaryBox.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
    $summaryBox.BorderStyle = "FixedSingle"
    $form.Controls.Add($summaryBox)

    foreach ($row in @(
        @{ Label = "Agent URL : $AgentUrl"; CopyText = $AgentUrl; BtnText = "Copier URL"; Y = 8 },
        @{ Label = "JWT Secret : $($JwtSecret.Substring(0,20))..."; CopyText = $JwtSecret; BtnText = "Copier JWT"; Y = 38 }
    )) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $row.Label
        $lbl.Location = New-Object System.Drawing.Point(10, $row.Y)
        $lbl.Size = New-Object System.Drawing.Size(440, 20)
        $lbl.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $summaryBox.Controls.Add($lbl)

        $ct = $row.CopyText
        $btn = New-Object System.Windows.Forms.Button
        $btn.Text = $row.BtnText
        $btn.Location = New-Object System.Drawing.Point(460, ($row.Y - 2))
        $btn.Size = New-Object System.Drawing.Size(110, 24)
        $btn.FlatStyle = "Flat"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
        $btn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $btn.Add_Click({ [System.Windows.Forms.Clipboard]::SetText($ct) }.GetNewClosure())
        $summaryBox.Controls.Add($btn)
    }

    $msgLbl = New-Object System.Windows.Forms.Label
    $msgLbl.Text = "Rends-toi dans le hub PitLane pour ajouter ce serveur."
    $msgLbl.Location = New-Object System.Drawing.Point(20, 718)
    $msgLbl.Size = New-Object System.Drawing.Size(490, 20)
    $msgLbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $form.Controls.Add($msgLbl)

    $closeBtn.Location = New-Object System.Drawing.Point(540, 715)
    $closeBtn.Visible = $true
    [System.Windows.Forms.Application]::DoEvents()
})

[System.Windows.Forms.Application]::Run($form)
