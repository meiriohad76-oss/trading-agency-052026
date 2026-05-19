param(
    [int]$Port = 8000,
    [switch]$SkipMigrations
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
}

$env:PYTHONPATH = "$RepoRoot\src;$RepoRoot\research\src"

if (-not $env:DATABASE_URL -or -not $env:DATABASE_URL.Trim()) {
    $env:DATABASE_URL = "sqlite+aiosqlite:///./agency_local.db"
} elseif ($env:DATABASE_URL.Trim().ToLowerInvariant().StartsWith("sqlite:///")) {
    $env:DATABASE_URL = $env:DATABASE_URL -replace "^sqlite:///", "sqlite+aiosqlite:///"
}

$env:AGENCY_PAPER_TRADE_PROMOTION_ENABLED = "true"
$env:AGENCY_PAPER_TRADE_MIN_CONVICTION = "0.62"
$env:AGENCY_BROKER_SUBMIT_ENABLED = "true"
$env:AGENCY_ALPACA_BROKER_ENABLED = "true"

& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev]"

if (-not $env:ALPACA_API_KEY -or -not $env:ALPACA_SECRET_KEY) {
    Write-Warning "ALPACA_API_KEY and ALPACA_SECRET_KEY are not set in this shell. Add your paper account keys before submitting paper orders."
}

if (-not $SkipMigrations) {
    & $Python -m alembic upgrade head
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
        Write-Host "Trading Agency is already running at http://127.0.0.1:$Port/"
        exit 0
    }
    throw "Port $Port responded, but the trading-agency health endpoint did not report ok."
}

Write-Host "Starting Trading Agency dev server at http://127.0.0.1:$Port/"
Write-Host "DATABASE_URL is configured for local persistence."
& $Python -m uvicorn agency.app:app --host 127.0.0.1 --port $Port
