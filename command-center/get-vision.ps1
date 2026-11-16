# Downloads Google's MediaPipe (Tasks Vision 0.10.14) and three small models into web\vision\
# for the camera features (study-mode phone watch, away lock). ~22 MB, one time.
# Everything is checked against fixed hashes; the files run on the tablet, not the PC.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$dest = Join-Path $PSScriptRoot 'web\vision'
New-Item -ItemType Directory -Force $dest | Out-Null
$tmp = Join-Path $env:TEMP ('tabdeck-vision-' + [guid]::NewGuid())
New-Item -ItemType Directory -Force $tmp | Out-Null

function Get-Checked($url, $file, $algo, $hash) {
    if ((Test-Path $file) -and (Get-FileHash $file -Algorithm $algo).Hash -eq $hash) { return }
    Invoke-WebRequest $url -OutFile $file -UseBasicParsing
    if ((Get-FileHash $file -Algorithm $algo).Hash -ne $hash) { Remove-Item $file; throw "Checksum mismatch: $url" }
}

try {
    # 1. MediaPipe Tasks Vision from the official npm registry (sha512 = the registry's own integrity value)
    $tgz = Join-Path $tmp 'tasks-vision.tgz'
    Get-Checked 'https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-0.10.14.tgz' $tgz 'SHA512' `
        'BCE89F8198649DD8326DDBE84484F346422E7965928822AE1145D72BA43815A26C16F449BB0820FBEBEA1543252F4528C7AD94E5A1171611F196157B25AE5EDD'
    & "$env:SystemRoot\System32\tar.exe" -xzf $tgz -C $tmp
    Copy-Item "$tmp\package\vision_bundle.mjs" $dest -Force
    Copy-Item "$tmp\package\wasm\vision_wasm_internal.js", "$tmp\package\wasm\vision_wasm_internal.wasm" $dest -Force
    Copy-Item "$tmp\package\LICENSE" $dest -Force -ErrorAction SilentlyContinue

    # 2. Models from Google's MediaPipe model storage
    $m = 'https://storage.googleapis.com/mediapipe-models'
    Get-Checked "$m/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" "$dest\hand_landmarker.task" 'SHA256' `
        'FBC2A30080C3C557093B5DDFC334698132EB341044CCEE322CCF8BCF3607CDE1'
    Get-Checked "$m/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite" "$dest\blaze_face_short_range.tflite" 'SHA256' `
        'B4578F35940BF5A1A655214A1CCE5CAB13EBA73C1297CD78E1A04C2380B0152F'
    Get-Checked "$m/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite" "$dest\efficientdet_lite0.tflite" 'SHA256' `
        '0720BF247BD76E6594EA28FA9C6F7C5242BE774818997DBBEFFC4DA460C723BB'
    Write-Host "Camera AI files ready in $dest"
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
