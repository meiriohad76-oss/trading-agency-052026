param(
    [int]$Port = 8000,
    [switch]$SkipMigrations,
    [switch]$Kiosk,
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Set-Location $RepoRoot
$StartPath = "/"
if ($Kiosk) {
    $StartPath = "/cockpit"
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

function Get-TradingAgencyServerProcesses {
    param([int]$Port)

    $repoPattern = [regex]::Escape($RepoRoot)
    $appPattern = "uvicorn\s+agency\.app:(app|create_app)"
    $factoryPattern = "agency\.app:create_app.*--factory"
    $legacyPattern = "run_local_app\.py"
    $portPattern = "--port\s+$Port(\s|$)"
    try {
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.CommandLine -and
                (($_.CommandLine -match $appPattern -and $_.CommandLine -match $portPattern) -or ($_.CommandLine -match $factoryPattern -and $_.CommandLine -match $portPattern) -or $_.CommandLine -match $legacyPattern) -and
                ($_.CommandLine -match $repoPattern -or $_.CommandLine -match "\\.venv\\Scripts\\python")
            }
        return
    } catch {
        Write-Warning "CIM process inspection failed: $($_.Exception.Message). Falling back to the listener on port $Port."
        $connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($connection in $connections) {
            [pscustomobject]@{
                ProcessId = $connection.OwningProcess
                ParentProcessId = 0
                CommandLine = "port $Port listener"
            }
        }
    }
}

function Stop-ExistingTradingAgencyServers {
    param([int]$Port)

    $processes = @(Get-TradingAgencyServerProcesses -Port $Port)
    if (-not $processes) {
        return
    }

    foreach ($process in ($processes | Sort-Object ParentProcessId -Descending)) {
        Write-Host "Existing Trading Agency server process $($process.ProcessId) will be stopped before start."
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    py -3.14 -m venv .venv
}

Write-Host "DATABASE_URL is loaded by the application from .env when present."

$cfgPath = "research\config\live-refresh.local.json"
if (Test-Path $cfgPath) {
    Write-Host "Using live refresh config at $cfgPath. Lane dates are derived by the scheduler."
}

Stop-ExistingTradingAgencyServers -Port $Port

if ($InstallDeps) {
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -e ".[dev]"
}

if (-not $env:ALPACA_API_KEY -or -not $env:ALPACA_SECRET_KEY) {
    Write-Warning "ALPACA_API_KEY and ALPACA_SECRET_KEY are not set in this shell. Add your paper account keys before submitting paper orders."
}

if (-not $SkipMigrations) {
    .\.venv\Scripts\python -m alembic upgrade head
}

$health = $null
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
} catch {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($null -ne $connection) {
        throw "Port $Port is already in use, but the trading-agency health endpoint did not respond."
    }
}

if ($null -ne $health) {
    throw "Port $Port still responds after existing Trading Agency servers were stopped. Close that server before starting this one."
}

Write-Host "Starting Trading Agency dev server at http://127.0.0.1:$Port$StartPath"
.\.venv\Scripts\python -m uvicorn agency.app:app --host 127.0.0.1 --port $Port
