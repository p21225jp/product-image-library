param([ValidateRange(1,65535)][int]$Port = 8750, [switch]$LocalOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required.' }
    & $pythonPath -m pip install -r (Join-Path $projectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
# start.ps1 reads these before launching, so changing them later has no effect; report data and origin settings to screen.
if ($env:ASSET_DATA_DIR) { Write-Host "Data:  $env:ASSET_DATA_DIR" } else { Write-Host "Data:  $(Join-Path $projectRoot 'data')" }
foreach ($variable in 'ASSET_ALLOWED_HOSTS', 'ASSET_PUBLIC_ORIGIN', 'ASSET_COOKIE_SECURE', 'ASSET_TRUSTED_PROXIES', 'ASSET_DISABLE_SETUP') {
    $current = [Environment]::GetEnvironmentVariable($variable)
    if ($current) { Write-Host "${variable}: $current" }
}
$listenAddress = if ($LocalOnly) { '127.0.0.1' } else { '0.0.0.0' }
Write-Host "Local: http://127.0.0.1:$Port"
if (-not $LocalOnly) {
    # Only addresses of connected adapters that are actually in use; Wi-Fi left behind must not be listed.
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.AddressState -eq 'Preferred' } |
        Where-Object { (Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue).Status -eq 'Up' } |
        ForEach-Object { Write-Host "LAN:   http://$($_.IPAddress):$Port" }
}
Write-Host 'Initialize the administrator account on this computer first. Ctrl+C or close this window to stop.'
$existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) { throw "Port $Port is already in use. Stop the existing server first." }
Push-Location -LiteralPath $projectRoot
$service = $null
try {
    $service = Start-Process -FilePath $pythonPath -ArgumentList @(('"' + (Join-Path $projectRoot 'serve.py') + '"'), '--host', $listenAddress, '--port', $Port) -NoNewWindow -PassThru
    # Waiting on the child lets Ctrl+C and a closed window reach this script and stop the server with it.
    $service.WaitForExit()
    if ($service.ExitCode -ne 0) { Write-Host "The server stopped with exit code $($service.ExitCode). See the messages above." }
}
finally {
    if ($service -and -not $service.HasExited) {
        & (Join-Path $projectRoot 'stop.ps1') -Port $Port
    }
    Pop-Location
}
