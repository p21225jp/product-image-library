# Copy to run-windows.ps1 and replace both values before using on the company server.
# IT can run the edited script at startup with Task Scheduler under a dedicated account.
$ErrorActionPreference = 'Stop'
$companyOrigin = 'https://assets.company.example'
$companyDataDirectory = 'D:\AssetLibrary\data'
if ($companyOrigin -eq 'https://assets.company.example') {
    throw 'Replace the example domain and data directory before starting the service.'
}
$companyUri = [Uri]$companyOrigin
if (-not $companyUri.IsAbsoluteUri -or $companyUri.Scheme -ne 'https' -or
    $companyUri.UserInfo -or $companyUri.Query -or $companyUri.Fragment -or $companyUri.AbsolutePath -ne '/') {
    throw 'The company origin must be an HTTPS origin without credentials, query or path.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Install Python dependencies in the project .venv first.' }
if (-not (Test-Path -LiteralPath (Join-Path $companyDataDirectory 'library.sqlite3'))) {
    throw 'Restore the completed backup or initialize the administrator locally before enabling this launcher.'
}
$env:ASSET_DATA_DIR = $companyDataDirectory
$env:ASSET_ALLOWED_HOSTS = $companyUri.DnsSafeHost
$env:ASSET_PUBLIC_ORIGIN = $companyOrigin.TrimEnd('/')
$env:ASSET_COOKIE_SECURE = '1'
$env:ASSET_TRUSTED_PROXIES = '127.0.0.1'
$env:ASSET_DISABLE_SETUP = '1'
$env:PYTHONUNBUFFERED = '1'
Set-Location -LiteralPath $projectRoot
# Keep Python attached to the task; no detached process and no interactive window needed.
& $pythonPath (Join-Path $projectRoot 'serve.py') --host 127.0.0.1 --port 8750
exit $LASTEXITCODE
