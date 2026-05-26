param(
    [int]$Port = 8000,
    [switch]$SeedDemo
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Set-Location $RepoRoot
$env:PYTHONPATH = "$RepoRoot\src;$RepoRoot\research\src"

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
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            (($_.CommandLine -match $appPattern -and $_.CommandLine -match $portPattern) -or ($_.CommandLine -match $factoryPattern -and $_.CommandLine -match $portPattern) -or $_.CommandLine -match $legacyPattern) -and
            ($_.CommandLine -match $repoPattern -or $_.CommandLine -match "\\.venv\\Scripts\\python")
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

if (-not (Test-Path $Python)) {
    py -3.14 -m venv .venv
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -e ".[dev]"
}

Stop-ExistingTradingAgencyServers -Port $Port

docker compose -f docker\docker-compose.yml up -d postgres

for ($i = 0; $i -lt 24; $i++) {
    $status = docker inspect --format "{{.State.Health.Status}}" trading-agency-postgres
    if ($status -eq "healthy") {
        break
    }
    Start-Sleep -Seconds 5
}

if ($status -ne "healthy") {
    throw "Postgres did not become healthy."
}

& $Python -m alembic upgrade head

if ($SeedDemo) {
    & $Python scripts\seed_demo_runtime.py
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

& $Python -m uvicorn agency.app:app --host 127.0.0.1 --port $Port
