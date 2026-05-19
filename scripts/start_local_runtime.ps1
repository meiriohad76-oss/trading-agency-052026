param(
    [int]$Port = 8000,
    [switch]$SeedDemo
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Set-Location $RepoRoot
$env:PYTHONPATH = "$RepoRoot\src;$RepoRoot\research\src"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

if (-not (Test-Path $Python)) {
    py -3.14 -m venv .venv
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -e ".[dev]"
}

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
    if ($health.status -eq "ok") {
        Write-Host "Local runtime is already running at http://127.0.0.1:$Port/"
        exit 0
    }
    throw "Port $Port responded, but the trading-agency health endpoint did not report ok."
}

& $Python -m uvicorn agency.app:app --host 127.0.0.1 --port $Port
