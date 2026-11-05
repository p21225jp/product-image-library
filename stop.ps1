param([ValidateRange(1,65535)][int]$Port = 8750)
$ErrorActionPreference = 'Stop'
$expectedScript = Join-Path $PSScriptRoot 'serve.py'
$expectedPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
function Test-OwnedServer($process) {
    if (-not $process -or -not $process.CommandLine) { return $false }
    if ($process.CommandLine.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    # Older launchers used a relative serve.py; confirm the project-specific venv launcher too.
    if ($process.CommandLine -notmatch '(?:^|\s)serve\.py(?:\s|$)') { return $false }
    if ($process.ExecutablePath -and $process.ExecutablePath.Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ParentProcessId)" -ErrorAction SilentlyContinue
    return [bool]($parent -and $parent.ExecutablePath -and
        $parent.ExecutablePath.Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase) -and
        $parent.CommandLine -match '(?:^|\s)serve\.py(?:\s|$)')
}
$listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if (-not $listeners) { Write-Host "No server is listening on port $Port."; exit 0 }
$stopped = 0
foreach ($serviceId in ($listeners.OwningProcess | Select-Object -Unique)) {
    # Inspect every listening process, not only the first: a leftover process must block the stop.
    $serviceProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId" -ErrorAction SilentlyContinue
    if (-not (Test-OwnedServer $serviceProcess)) {
        throw "Port $Port also belongs to another process (PID $serviceId). No process was stopped."
    }
}
foreach ($serviceId in ($listeners.OwningProcess | Select-Object -Unique)) {
    Stop-Process -Id $serviceId -Force
    $stopped++
    Write-Host "Stopped product image library (PID $serviceId)."
}
Write-Host "Server on port $Port is no longer listening ($stopped process stopped)."
