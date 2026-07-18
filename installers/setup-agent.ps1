#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$RepoOwner = "JeanBernardMagnien"
$RepoName = "pitlane-agent"
$ReleaseZipUrl = "https://github.com/$RepoOwner/$RepoName/releases/latest/download/agent.zip"
$LatestReleaseApiUrl = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/latest"

# Utility functions

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

function Find-SteamRoot {
    Add-Log "Recherche Steam client dans le registre..."

    $path = (Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam" `
        -ErrorAction SilentlyContinue).InstallPath

    if (-not $path) {
        $path = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Valve\Steam" `
            -ErrorAction SilentlyContinue).InstallPath
    }

    if ($path) {
        Add-Log "Steam client trouve : $path"
    } else {
        Add-Log "Steam client non trouve."
    }

    return $path
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

function Get-RealPython {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    if ($cmd.Source -like "*\WindowsApps\python.exe") { return $null }

    try {
        & python --version *> $null
        if ($LASTEXITCODE -ne 0) { return $null }
    } catch {
        return $null
    }

    return $cmd
}

function Find-PythonExe {
    $searchRoots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $searchRoots) {
        $found = Get-ChildItem -Path $root -Filter "python.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match "Python3" } |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Install-PythonFromOfficial {
    $pyVersion = "3.12.7"
    $installerUrl = "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-amd64.exe"
    $installerPath = "$env:TEMP\python-$pyVersion-amd64.exe"

    Add-Log "Telechargement de Python $pyVersion depuis python.org"
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Add-Log "Installation silencieuse de Python $pyVersion (pour tous les utilisateurs, ajout au PATH)"
    $proc = Start-Process -FilePath $installerPath `
        -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" `
        -Wait -PassThru
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

    Add-Log "Installateur python.org termine (code retour $($proc.ExitCode))"
}

function Wait-ForPython {
    param([scriptblock]$RefreshPath, [int]$MaxRetries = 10)

    & $RefreshPath
    $found = Get-RealPython
    $retries = 0
    while (-not $found -and $retries -lt $MaxRetries) {
        Start-Sleep -Seconds 2
        & $RefreshPath
        $found = Get-RealPython
        $retries++
    }
    return $found
}

function Get-AppManifestPath {
    param([string]$AcEvoPath)

    if ([string]::IsNullOrWhiteSpace($AcEvoPath)) {
        throw "Impossible de deduire appmanifest_path : AcEvoPath est vide"
    }

    # L'agent met a jour via "+force_install_dir <AcEvoPath>", qui cree son propre
    # sous-dossier steamapps dans AcEvoPath. Le manifest a surveiller est donc toujours ici,
    # pas dans la bibliotheque SteamCMD principale.
    return Join-Path $AcEvoPath "steamapps\appmanifest_4564210.acf"
}

function Download-Agent {
    param($DestinationPath)

    $zip = "$env:TEMP\pitlane-agent.zip"

    if (Test-Path $DestinationPath) {
        Remove-Item -Path $DestinationPath -Recurse -Force -ErrorAction SilentlyContinue
    }

    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null

    Invoke-WebRequest -Uri $ReleaseZipUrl -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $DestinationPath -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}


function Get-LatestReleaseInfo {
    try {
        return Invoke-RestMethod -Uri $LatestReleaseApiUrl -UseBasicParsing -Headers @{ "User-Agent" = "PitLaneAgentInstaller" }
    } catch {
        Add-Log "Impossible de recuperer les infos de release GitHub : $_"
        return $null
    }
}

function Write-VersionFile {
    param(
        [string]$AgentPath,
        $ReleaseInfo
    )

    $versionPath = Join-Path $AgentPath "version.json"

    $data = [ordered]@{
        installed_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        source = "github_release"
        asset = "agent.zip"
        release_url = $ReleaseZipUrl
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

function Install-AgentUpdater {
    param([string]$AgentPath)

    $url = "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/updater.exe"
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
        Invoke-LoggedPython -Arguments @($serviceScript, "install")
        sc.exe config PitLaneAgent start= auto | Out-Null
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

# AcEvoPath sera resolu dans Add_Shown pour ne pas bloquer avant l'apparition du formulaire
$AcEvoPath = $null

# Main UI

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane Agent - Installation"
$form.Size = New-Object System.Drawing.Size(620, 760)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$form.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "Installation de PitLane Agent"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$titleLabel.Location = New-Object System.Drawing.Point(20, 14)
$titleLabel.Size = New-Object System.Drawing.Size(560, 28)
$form.Controls.Add($titleLabel)

$stepsPanel = New-Object System.Windows.Forms.Panel
$stepsPanel.Location = New-Object System.Drawing.Point(20, 50)
$stepsPanel.Size = New-Object System.Drawing.Size(560, 345)
$stepsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$stepsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($stepsPanel)

$steps = @(
    "[1] Detection AC EVO",
    "[2] Detection Steam / steamcmd",
    "[3] Synchronisation appmanifest",
    "[4] Telechargement agent",
    "[5] Verification Python",
    "[6] Installation dependances",
    "[7] Generation config.yml",
    "[8] Service Windows natif",
    "[9] Regle firewall API agent",
    "[10] Termine"
)

$stepLabels = @()
for ($i = 0; $i -lt $steps.Count; $i++) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "WAIT " + $steps[$i]
    $lbl.Location = New-Object System.Drawing.Point(10, (6 + $i * 33))
    $lbl.Size = New-Object System.Drawing.Size(535, 26)
    $lbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $stepsPanel.Controls.Add($lbl)
    $stepLabels += $lbl
}

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 405)
$progressBar.Size = New-Object System.Drawing.Size(560, 16)
$progressBar.Maximum = $steps.Count
$form.Controls.Add($progressBar)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 430)
$logBox.Size = New-Object System.Drawing.Size(560, 140)
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

    $logBox.AppendText("$msg`r`n")
    $logBox.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

$closeBtn = New-Object System.Windows.Forms.Button
$closeBtn.Text = "Fermer"
$closeBtn.Location = New-Object System.Drawing.Point(470, 630)
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
    $JwtSecret = $null
    $SteamCmdExe = $null
    $AppManifestPath = ""

    # [1] Detection AC EVO
    Set-StepStatus 0 "running"
    $AcEvoPath = Find-AcEvoServer
    if (-not $AcEvoPath) {
        Set-StepStatus 0 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "AC EVO Dedicated Server introuvable. Lance setup-full.ps1 pour une installation complete.",
            "Erreur", "OK", "Error"
        )
        $form.Close()
        return
    }
    $AgentPath = "$AcEvoPath\pitlane-agent"
    Add-Log "AC EVO detecte : $AcEvoPath"
    Set-StepStatus 0 "ok"

    # [2] Detection Steam / steamcmd
    Set-StepStatus 1 "running"
    $SteamRoot = Find-SteamRoot
    $SteamCmdExe = Find-SteamCmd

    if (-not $SteamCmdExe) {
        $cmdDir = "C:\SteamCMD"
        $SteamCmdExe = Join-Path $cmdDir "steamcmd.exe"

        Add-Log "steamcmd.exe introuvable - installation automatique dans $cmdDir (necessaire pour les mises a jour a distance depuis le hub)"

        try {
            New-Item -ItemType Directory -Path $cmdDir -Force | Out-Null

            $zip = "$env:TEMP\steamcmd.zip"

            Invoke-WebRequest -Uri "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" `
                -OutFile $zip -UseBasicParsing

            Expand-Archive -Path $zip -DestinationPath $cmdDir -Force
            Remove-Item $zip -Force -ErrorAction SilentlyContinue

            if (-not (Test-Path $SteamCmdExe)) {
                throw "steamcmd.exe introuvable apres extraction : $SteamCmdExe"
            }

            Add-Log "steamcmd installe : $SteamCmdExe"
        } catch {
            Add-Log "Erreur installation steamcmd : $_ - poursuite sans steamcmd"
            $SteamCmdExe = $null
        }
    } else {
        Add-Log "steamcmd trouve : $SteamCmdExe"
    }

    Set-StepStatus 1 "ok"

    # [3] Synchronisation appmanifest
    Set-StepStatus 2 "running"

    $AppManifestPath = Get-AppManifestPath -AcEvoPath $AcEvoPath

    if ($SteamCmdExe -and (Test-Path $SteamCmdExe)) {
        Add-Log "Synchronisation du manifest Steam (necessaire avant la 1ere mise a jour via le hub)"

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
        $noteLbl.Text = "Requis pour synchroniser le manifest de version AC EVO. Annuler pour ignorer (sera fait au 1er update via le hub)."
        $noteLbl.Location = New-Object System.Drawing.Point(12, 12)
        $noteLbl.Size = New-Object System.Drawing.Size(365, 40)
        $noteLbl.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
        $credForm.Controls.Add($noteLbl)

        $userLbl = New-Object System.Windows.Forms.Label
        $userLbl.Text = "Nom d'utilisateur Steam :"
        $userLbl.Location = New-Object System.Drawing.Point(12, 62)
        $userLbl.Size = New-Object System.Drawing.Size(170, 20)
        $credForm.Controls.Add($userLbl)

        $userTxt = New-Object System.Windows.Forms.TextBox
        $userTxt.Location = New-Object System.Drawing.Point(185, 60)
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
        $okBtn.Text = "Synchroniser"
        $okBtn.DialogResult = "OK"
        $okBtn.Location = New-Object System.Drawing.Point(255, 148)
        $okBtn.Size = New-Object System.Drawing.Size(115, 28)
        $okBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
        $okBtn.ForeColor = [System.Drawing.Color]::Black
        $okBtn.FlatStyle = "Flat"
        $credForm.Controls.Add($okBtn)
        $credForm.AcceptButton = $okBtn

        $cancelBtn = New-Object System.Windows.Forms.Button
        $cancelBtn.Text = "Ignorer"
        $cancelBtn.DialogResult = "Cancel"
        $cancelBtn.Location = New-Object System.Drawing.Point(140, 148)
        $cancelBtn.Size = New-Object System.Drawing.Size(105, 28)
        $cancelBtn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
        $cancelBtn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $cancelBtn.FlatStyle = "Flat"
        $credForm.Controls.Add($cancelBtn)

        if ($credForm.ShowDialog() -ne "OK") {
            Add-Log "Synchronisation ignoree - le manifest sera cree au 1er update lance depuis le hub"
        } else {
            $steamUser = $userTxt.Text
            $steamPass = $passTxt.Text
            $passTxt.Text = ""

            Add-Log "Lancement steamcmd +force_install_dir `"$AcEvoPath`" +app_update 4564210 validate"
            Add-Log "Une fenetre SteamCMD va s'ouvrir - validez le Steam Guard sur votre telephone si demande."

            $steamArgs = "+force_install_dir `"$AcEvoPath`" +login `"$steamUser`" `"$steamPass`" +app_update 4564210 validate +quit"
            $steamUser = $null
            $steamPass = $null

            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName        = $SteamCmdExe
            $psi.Arguments       = $steamArgs
            $psi.UseShellExecute = $true
            $psi.CreateNoWindow  = $false

            $proc = New-Object System.Diagnostics.Process
            $proc.StartInfo = $psi
            [void]$proc.Start()

            while (-not $proc.HasExited) {
                [System.Windows.Forms.Application]::DoEvents()
                Start-Sleep -Milliseconds 500
            }
            $proc.WaitForExit()

            if (Test-Path $AppManifestPath) {
                Add-Log "Manifest synchronise : $AppManifestPath"
            } else {
                Add-Log "ATTENTION : manifest toujours introuvable (code retour steamcmd $($proc.ExitCode)). Sera cree au 1er update lance depuis le hub."
            }
        }
    } else {
        Add-Log "steamcmd indisponible, synchronisation ignoree - le manifest sera cree au 1er update lance depuis le hub"
    }

    Add-Log "appmanifest_path : $AppManifestPath"
    Set-StepStatus 2 "ok"

    # [4] Telechargement agent
    Set-StepStatus 3 "running"
    try {
        Add-Log "Telechargement agent vers $AgentPath"
        Download-Agent -DestinationPath $AgentPath
        Install-AgentUpdater -AgentPath $AgentPath
        Set-StepStatus 3 "ok"
    } catch {
        Set-StepStatus 3 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "Echec du telechargement de l'agent : $_", "Erreur", "OK", "Error")
        return
    }

    # [5] Verification Python
    Set-StepStatus 4 "running"
    $python = Get-RealPython

    $refreshPath = {
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
    }

    if (-not $python) {
        Add-Log "Python absent (ou alias Microsoft Store detecte)"

        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetCmd) {
            Add-Log "Tentative d'installation via winget"
            $wingetOutput = & winget install Python.Python.3 --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-String
            Add-Log "winget install Python.Python.3 (code retour $LASTEXITCODE) :"
            Add-Log $wingetOutput.Trim()
            $python = Wait-ForPython -RefreshPath $refreshPath
        } else {
            Add-Log "winget introuvable sur ce systeme (courant sur Windows Server, App Installer n'est pas preinstalle)"
        }

        if (-not $python) {
            Add-Log "Tentative d'installation via l'installateur officiel python.org"
            try {
                Install-PythonFromOfficial
                $python = Wait-ForPython -RefreshPath $refreshPath -MaxRetries 5
            } catch {
                Add-Log "Echec installateur python.org : $_"
            }
        }

        if (-not $python) {
            Add-Log "Toujours introuvable via PATH - recherche directe de python.exe sur le disque"
            $pythonExe = Find-PythonExe
            if ($pythonExe) {
                $pythonDir = Split-Path $pythonExe
                Add-Log "python.exe trouve : $pythonExe - ajout temporaire au PATH de cette session"
                $env:Path = "$pythonDir;$env:Path"
                $python = Get-RealPython
            }
        }

        if (-not $python) {
            Set-StepStatus 4 "error"
            [System.Windows.Forms.MessageBox]::Show(
                "Python introuvable et les installations automatiques (winget puis python.org) ont echoue (voir le detail dans le log). " +
                "Installe Python manuellement depuis https://www.python.org/downloads/ (coche 'Add python.exe to PATH' pendant l'installation), puis relance l'installeur.",
                "Erreur", "OK", "Error")
            return
        }
    }

    Add-Log "Python trouve : $($python.Source)"
    Add-Log "Verification SQLite standard"
    Invoke-LoggedPython -Arguments @("-c", "import sqlite3; db = sqlite3.connect(':memory:'); db.execute('SELECT 1'); db.close()")
    Set-StepStatus 4 "ok"

    # [6] Installation dependances
    Set-StepStatus 5 "running"
    Add-Log "pip install requirements"
    Invoke-LoggedPython -Arguments @("-m", "pip", "install", "-r", "$AgentPath\requirements.txt", "--quiet")
    Set-StepStatus 5 "ok"

    # [7] Generation config.yml
    Set-StepStatus 6 "running"
    $JwtSecret = New-JwtSecret
    $publicIp = Get-PublicIp
    $BaseUrl = "http://$publicIp"
    $AgentUrl = "http://$publicIp`:8181"

    $configContent = Get-Content "$AgentPath\config.template.yml" -Raw
    $configContent = $configContent.Replace("__BASE_URL__", $BaseUrl)
    $configContent = $configContent.Replace("__INSTALL_PATH__", $AcEvoPath)
    $configContent = $configContent.Replace("__CONFIGS_PATH__", "$AcEvoPath\configs")
    $configContent = $configContent.Replace("__RESULTS_PATH__", "$AcEvoPath\Results")
    $configContent = $configContent.Replace("__LOGS_PATH__", "$AcEvoPath\logs")
    $configContent = $configContent.Replace("__STEAMCMD_PATH__", $SteamCmdExe)
    $configContent = $configContent.Replace("__APPMANIFEST_PATH__", $AppManifestPath)
    $configContent = $configContent.Replace("__JWT_SECRET__", $JwtSecret)
    Set-Content -Path "$AgentPath\config.yml" -Value $configContent -Encoding UTF8
    Remove-Item "$AgentPath\config.template.yml" -Force -ErrorAction SilentlyContinue

    foreach ($dir in @("$AcEvoPath\configs", "$AcEvoPath\Results", "$AcEvoPath\logs")) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir | Out-Null
        }
    }

    Add-Log "config.yml genere"
    Add-Log "config.template.yml supprime"
    Write-VersionFile -AgentPath $AgentPath -ReleaseInfo (Get-LatestReleaseInfo)
    Set-StepStatus 6 "ok"

    # [8] Service Windows natif
    Set-StepStatus 7 "running"
    try {
        Install-AgentService -AgentPath $AgentPath
        Set-StepStatus 7 "ok"
    } catch {
        Set-StepStatus 7 "error"
        [System.Windows.Forms.MessageBox]::Show("Erreur installation service : $_", "Erreur", "OK", "Error")
        return
    }

    # [9] Regle firewall API agent
    Set-StepStatus 8 "running"

    Get-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue

    New-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -Direction Inbound `
        -Protocol TCP -LocalPort 8181 -Action Allow `
        -ErrorAction SilentlyContinue | Out-Null
    Add-Log "Firewall : TCP/8181 ouvert (PitLane - Agent API 8181)"
    Add-Log "Les ports d'instances seront geres par le hub lors de la creation/modification/suppression."

    Set-StepStatus 8 "ok"

    # [10] Resume
    Set-StepStatus 9 "ok"

    $form.Size = New-Object System.Drawing.Size(620, 790)

    $summaryBox = New-Object System.Windows.Forms.Panel
    $summaryBox.Location = New-Object System.Drawing.Point(20, 585)
    $summaryBox.Size = New-Object System.Drawing.Size(560, 72)
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
        $lbl.Size = New-Object System.Drawing.Size(390, 20)
        $lbl.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $summaryBox.Controls.Add($lbl)

        $ct = $row.CopyText
        $btn = New-Object System.Windows.Forms.Button
        $btn.Text = $row.BtnText
        $btn.Location = New-Object System.Drawing.Point(410, ($row.Y - 2))
        $btn.Size = New-Object System.Drawing.Size(90, 24)
        $btn.FlatStyle = "Flat"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
        $btn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $btn.Add_Click({ [System.Windows.Forms.Clipboard]::SetText($ct) }.GetNewClosure())
        $summaryBox.Controls.Add($btn)
    }

    $yNext = 665
    if (-not $SteamCmdExe) {
        $warnLbl = New-Object System.Windows.Forms.Label
        $warnLbl.Text = "WARNING steamcmd non detecte - mise a jour distante desactivee"
        $warnLbl.Location = New-Object System.Drawing.Point(20, $yNext)
        $warnLbl.Size = New-Object System.Drawing.Size(560, 20)
        $warnLbl.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
        $form.Controls.Add($warnLbl)
        $yNext += 28
        $form.Size = New-Object System.Drawing.Size(620, ($yNext + 95))
    }

    $msgLbl = New-Object System.Windows.Forms.Label
    $msgLbl.Text = "Rends-toi dans le hub PitLane pour ajouter ce serveur."
    $msgLbl.Location = New-Object System.Drawing.Point(20, $yNext)
    $msgLbl.Size = New-Object System.Drawing.Size(430, 20)
    $msgLbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $form.Controls.Add($msgLbl)

    $closeBtn.Location = New-Object System.Drawing.Point(470, $yNext)
    $closeBtn.Visible = $true
    [System.Windows.Forms.Application]::DoEvents()
})

[System.Windows.Forms.Application]::Run($form)
