param(
    [int]$Port = 8000,
    [switch]$SkipSeed
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Set-Location $RepoRoot

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

if (-not $SkipSeed) {
    & $Python scripts\seed_demo_runtime.py
}

& $Python -m uvicorn agency.app:app --host 127.0.0.1 --port $Port
