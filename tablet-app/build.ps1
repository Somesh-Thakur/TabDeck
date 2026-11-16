# Builds and signs the Command Center tablet app (no Android Studio / Gradle needed).
# Usage: .\build.ps1 [-Install]
param([switch]$Install)
$ErrorActionPreference = 'Continue'   # native tools print notes on stderr; failures are caught via $LASTEXITCODE
$root  = $PSScriptRoot
$sdk   = Join-Path $root '..\tools\android-sdk' | Resolve-Path
$bt    = "$sdk\build-tools\35.0.1"
$jar   = "$sdk\platforms\android-35\android.jar"
$adb   = Join-Path $root '..\tools\platform-tools\adb.exe'
if (-not $env:JAVA_HOME) {   # find a JDK (17+) if JAVA_HOME isn't set
    $javac = (Get-Command javac -ErrorAction SilentlyContinue).Source
    $jdk = Get-ChildItem 'C:\Program Files\Java', 'C:\Program Files\Eclipse Adoptium', 'C:\Program Files\Microsoft' -Directory -ErrorAction SilentlyContinue |
           Where-Object Name -match 'jdk' | Sort-Object Name -Descending | Select-Object -First 1
    $env:JAVA_HOME = if ($jdk) { $jdk.FullName } elseif ($javac) { Split-Path (Split-Path (Resolve-Path $javac)) } else { throw 'JDK 17+ not found' }
}
$out   = "$root\build"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$out\res", "$out\classes", "$out\dex" | Out-Null

# 1. resources + manifest
& "$bt\aapt2.exe" compile --dir "$root\res" -o "$out\res.zip"
& "$bt\aapt2.exe" link -o "$out\base.apk" -I $jar --manifest "$root\AndroidManifest.xml" "$out\res.zip" --min-sdk-version 30 --target-sdk-version 30
if ($LASTEXITCODE) { throw 'aapt2 link failed' }

# 2. java -> class -> dex
$src = Get-ChildItem "$root\src" -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& "$env:JAVA_HOME\bin\javac.exe" -nowarn -XDsuppressNotes --release 11 -cp $jar -d "$out\classes" @src
if ($LASTEXITCODE) { throw 'javac failed' }
$classes = Get-ChildItem "$out\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName }
& "$bt\d8.bat" --release --min-api 30 --lib $jar --output "$out\dex" @classes
if ($LASTEXITCODE) { throw 'd8 failed' }

# 3. add dex, align, sign
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open("$out\base.apk", 'Update')
[System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, "$out\dex\classes.dex", 'classes.dex') | Out-Null
$zip.Dispose()
& "$bt\zipalign.exe" -f -p 4 "$out\base.apk" "$out\aligned.apk"
$ks = "$root\signing.keystore"
if (-not (Test-Path $ks)) {
  & "$env:JAVA_HOME\bin\keytool.exe" -genkeypair -keystore $ks -storepass commandcenter -keypass commandcenter `
    -alias cc -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Command Center' 2>$null
}
& "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:commandcenter --key-pass pass:commandcenter --out "$root\CommandCenter.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw 'apksigner failed' }
"Built: $root\CommandCenter.apk  ({0:N0} KB)" -f ((Get-Item "$root\CommandCenter.apk").Length / 1KB)

if ($Install) { & $adb install -r "$root\CommandCenter.apk" }
