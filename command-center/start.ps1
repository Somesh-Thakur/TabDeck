# Starts the Command Center server (hidden). The server itself notices the tablet over USB,
# sets up the tunnel and opens the dashboard on it - no polling, nothing else to run.
$root = $PSScriptRoot
$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match 'command-center\\server.py' }
if (-not $running) {
    # use the real pythonw.exe, not the Store launcher stub (which stays resident as a 2nd process)
    $exe = & python -c "import sys; print(sys.executable)"
    $py = Join-Path (Split-Path $exe) 'pythonw.exe'
    if (-not (Test-Path $py)) { $py = $exe }
    Start-Process $py -ArgumentList "`"$root\server.py`"" -WorkingDirectory $root -WindowStyle Hidden
}
