# TabDeck installer - turns an Android tablet into a touch command center for your Windows PC.
# Run from the repo folder:   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'
$Repo  = 'Somesh-Thakur/TabDeck'         # GitHub repo the tablet app (APK) is downloaded from
$Root  = $PSScriptRoot
$CC    = Join-Path $Root 'command-center'
$Tools = Join-Path $Root 'tools'
New-Item -ItemType Directory -Force $Tools | Out-Null

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Ask($q)  { (Read-Host "$q [y/N]") -match '^(y|yes)$' }
function Fetch($url, $out) { Invoke-WebRequest $url -OutFile $out -UseBasicParsing -Headers @{ 'User-Agent' = 'TabDeck-installer' } }

# ------------------------------------------------------------------ 1. Python
Step 'Checking Python (3.10 or newer)'
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
$pyOk = if ($py) { & python -c "import sys; print(sys.version_info >= (3, 10))" 2>$null } else { 'False' }
if ($pyOk -ne 'True') {
    Write-Host 'Python 3.10+ is required. Install it from https://www.python.org/downloads/ (tick "Add to PATH"), then run this again.' -ForegroundColor Yellow
    exit 1
}
$exe  = & python -c "import sys; print(sys.executable)"
$pyw  = Join-Path (Split-Path $exe) 'pythonw.exe'; if (-not (Test-Path $pyw)) { $pyw = $exe }
Write-Host "Using $exe"
& python -m pip install --user --quiet -r (Join-Path $CC 'requirements.txt')

# ------------------------------------------------------------------ 2. adb (Google platform-tools)
Step 'Android platform-tools (adb) from Google'
if (-not (Test-Path "$Tools\platform-tools\adb.exe")) {
    $zip = "$Tools\platform-tools.zip"
    Fetch 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' $zip
    Expand-Archive $zip $Tools -Force; Remove-Item $zip
}
$adb = "$Tools\platform-tools\adb.exe"
Write-Host 'OK'

# ------------------------------------------------------------------ 3. ffmpeg (second-screen mode)
Step 'ffmpeg (needed for second-screen mode)'
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Ask 'ffmpeg not found. Install it with winget (Gyan.FFmpeg.Essentials)?') {
        winget install --id Gyan.FFmpeg.Essentials -e --source winget
        Write-Host 'Open a NEW terminal after this installer finishes so ffmpeg is on PATH.' -ForegroundColor Yellow
    } else { Write-Host 'Skipped - second-screen mode will not work until ffmpeg is installed.' }
} else { Write-Host 'OK' }

# ------------------------------------------------------------------ 4. scrcpy (optional: tablet microphone)
Step 'Tablet microphone (optional)'
if (-not (Test-Path "$Tools\scrcpy\scrcpy.exe") -and (Ask 'Use the tablet as a microphone? (downloads scrcpy from GitHub)')) {
    $rel = Invoke-RestMethod 'https://api.github.com/repos/Genymobile/scrcpy/releases/latest' -Headers @{ 'User-Agent' = 'TabDeck-installer' }
    $a = $rel.assets | Where-Object name -like 'scrcpy-win64-*.zip' | Select-Object -First 1
    $zip = "$Tools\scrcpy.zip"; Fetch $a.browser_download_url $zip
    if ($a.digest -and ('sha256:' + (Get-FileHash $zip).Hash.ToLower()) -ne $a.digest) { throw 'scrcpy checksum mismatch' }
    Expand-Archive $zip "$Tools\_scrcpy" -Force; Remove-Item $zip
    Move-Item (Get-ChildItem "$Tools\_scrcpy" -Directory | Select-Object -First 1).FullName "$Tools\scrcpy"; Remove-Item "$Tools\_scrcpy" -Recurse
    Write-Host 'To use it as a Windows mic you also need VB-CABLE (free): https://vb-audio.com/Cable/' -ForegroundColor Yellow
}

# ------------------------------------------------------------------ 5. the tablet app
Step 'Tablet app'
Write-Host 'On the tablet: Settings > About tablet > tap "Build number" 7 times, then'
Write-Host 'Settings > System > Developer options > turn on "USB debugging" and "Stay awake".'
Write-Host 'Plug the tablet in and tap "Allow" on the USB debugging prompt (tick "Always allow").'
& $adb start-server | Out-Null
Write-Host 'Waiting for the tablet...'
& $adb wait-for-device
$apk = Join-Path $Root 'tablet-app\CommandCenter.apk'
if (-not (Test-Path $apk)) {
    $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ 'User-Agent' = 'TabDeck-installer' }
    $a = $rel.assets | Where-Object name -like '*.apk' | Select-Object -First 1
    $apk = "$Tools\TabDeck.apk"; Fetch $a.browser_download_url $apk
}
& $adb install -r $apk
if (Ask 'Make TabDeck the tablet''s home screen (it boots straight into the dashboard)?') {
    & $adb shell cmd package set-home-activity dev.somesh.commandcenter/.MainActivity
}

# ------------------------------------------------------------------ 6. shortcuts + start with Windows
Step 'Shortcuts and auto-start'
$ws = New-Object -ComObject WScript.Shell
foreach ($lnk in "$([Environment]::GetFolderPath('Desktop'))\TabDeck.lnk", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\TabDeck.lnk") {
    $s = $ws.CreateShortcut($lnk); $s.TargetPath = $pyw; $s.Arguments = "`"$CC\open-settings.pyw`""
    $s.WorkingDirectory = $CC; $s.IconLocation = "$CC\command-center.ico,0"; $s.Description = 'TabDeck settings'; $s.Save()
}
$s = $ws.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\TabDeck.lnk")
$s.TargetPath = $pyw; $s.Arguments = "`"$CC\server.py`""; $s.WorkingDirectory = $CC; $s.WindowStyle = 7; $s.Save()
Write-Host 'Desktop + Start menu shortcut "TabDeck" created; the server starts with Windows.'

# ------------------------------------------------------------------ 7. Claude Code (optional)
if (Test-Path "$env:USERPROFILE\.claude") {
    Step 'Claude Code integration (optional)'
    if (Ask 'Show Claude Code alerts and Allow/Deny prompts on the tablet? (adds hooks to ~/.claude/settings.json)') {
        & python (Join-Path $CC 'install_claude_hooks.py')
    }
}

# ------------------------------------------------------------------ 8. go
Step 'Starting TabDeck'
Start-Process $pyw -ArgumentList "`"$CC\server.py`"" -WorkingDirectory $CC -WindowStyle Hidden
Write-Host @"

Done! The tablet should show the dashboard in a few seconds.
Open "TabDeck" from the Start menu to customise it.

Optional extras:
  * Second screen as a real extended monitor: install the Parsec Virtual Display Driver
    https://builds.parsec.app/vdd/parsec-vdd-0.45.0.0.exe   (without it, second screen mirrors your main screen)
  * Tablet as a microphone: VB-CABLE  https://vb-audio.com/Cable/
"@ -ForegroundColor Green
