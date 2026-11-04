<#
  TriPhoto - lanceur.
  Vérifie Python et les dépendances, démarre le serveur local sans console,
  puis ouvre l'interface dans une fenêtre d'application Edge (ou Chrome).
  Fermer la fenêtre arrête le serveur tout seul (au bout de ~20 s).

  .\TriPhoto.ps1               lancer
  .\TriPhoto.ps1 -NoImport     ne pas vider pCloud au démarrage
  .\TriPhoto.ps1 -Browser      ouvrir dans le navigateur par défaut
  .\TriPhoto.ps1 -Shortcut     créer un raccourci sur le Bureau
#>
param(
    [switch]$NoImport,
    [switch]$Browser,
    [switch]$Shortcut
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$PortFile = Join-Path $Here '.cache\server.json'
$LogFile = Join-Path $Here 'triphoto.log'
try { $Host.UI.RawUI.WindowTitle = 'TriPhoto' } catch {}

function Say($msg, $color = 'Gray') { Write-Host "  $msg" -ForegroundColor $color }

if ($Shortcut) {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'TriPhoto.lnk'
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = Join-Path $Here 'TriPhoto.bat'
    $s.WorkingDirectory = $Here
    $s.WindowStyle = 7          # minimised: the console only lives a second anyway
    $edgeIco = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    if (Test-Path $edgeIco) { $s.IconLocation = "$edgeIco,0" }
    $s.Save()
    Say "Raccourci créé : $lnk" Green
    exit 0
}

function Get-RunningPort {
    if (-not (Test-Path $PortFile)) { return $null }
    try {
        $info = Get-Content $PortFile -Raw | ConvertFrom-Json
        # Connecting to a closed localhost port costs ~2 s on Windows (SYN retries):
        # a dead pid means a stale file, no need to knock.
        if (-not (Get-Process -Id $info.pid -ErrorAction SilentlyContinue)) { return $null }
        $r = Invoke-RestMethod "http://127.0.0.1:$($info.port)/api/ping" -TimeoutSec 2
        if ($r.app -eq 'TriPhoto') { return [int]$info.port }
    } catch {}
    return $null
}

function Find-Python {
    # One interpreter start does both jobs: print the real path (pythonw sits next
    # to it) and tell whether the dependencies import. Returns @(path, depsOk).
    $probe = "import sys; print(sys.executable)`ntry:`n import PIL, pillow_heif, send2trash; print('deps-ok')`nexcept ImportError: pass"
    foreach ($name in @('python', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $pyArgs = @()
        if ($name -eq 'py') { $pyArgs = @('-3') }
        try {
            $out = @(& $cmd.Source @pyArgs -c $probe 2>$null)
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 1) {
                return @($out[0].Trim(), ($out -contains 'deps-ok'))
            }
        } catch {}
    }
    return $null
}

Write-Host ''
Say 'TriPhoto' Magenta

$port = Get-RunningPort
if ($port) {
    Say "Déjà lancé (port $port) : j'ouvre une fenêtre." DarkGray
} else {
    $found = Find-Python
    if (-not $found) {
        Say 'Python 3 introuvable. Installe-le (python.org ou Microsoft Store) puis relance.' Red
        Read-Host '  Entrée pour quitter'
        exit 1
    }
    $py, $depsOk = $found
    if (-not $depsOk) {
        Say 'Installation des dépendances (une seule fois)...' Cyan
        & $py -m pip install --disable-pip-version-check -r (Join-Path $Here 'requirements.txt')
    }
    # pythonw = no console window for the server
    $pyw = Join-Path (Split-Path $py) 'pythonw.exe'
    if (-not (Test-Path $pyw)) { $pyw = $py }
    Remove-Item $PortFile -ErrorAction SilentlyContinue
    $serverArgs = @('-m', 'triphoto')
    if ($NoImport) { $serverArgs += '--no-import' }
    Start-Process -FilePath $pyw -ArgumentList $serverArgs -WorkingDirectory $Here -WindowStyle Hidden
    for ($i = 0; $i -lt 120 -and -not $port; $i++) {
        Start-Sleep -Milliseconds 150
        $port = Get-RunningPort
    }
    if (-not $port) {
        Say 'Le serveur ne répond pas. Dernières lignes du journal :' Red
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 15 | ForEach-Object { Say $_ DarkGray } }
        Read-Host '  Entrée pour quitter'
        exit 1
    }
    Say "Serveur prêt (port $port)" Green
}

$url = "http://127.0.0.1:$port/"
if ($Browser) { Start-Process $url; exit 0 }

$candidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$exe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($exe) {
    # Own profile: a real app window with its own taskbar entry, remembered size and zoom
    $profileDir = Join-Path $env:LOCALAPPDATA 'TriPhoto\AppWindow'
    Start-Process -FilePath $exe -ArgumentList @(
        "--app=$url", "--user-data-dir=`"$profileDir`"", '--window-size=1520,940',
        '--no-first-run', '--no-default-browser-check', '--disable-features=Translate')
} else {
    Start-Process $url
}
