<#
  FinSight AI - one-command local start (Windows)

  Usage (from the repo root):
      powershell -ExecutionPolicy Bypass -File .\start_app.ps1            # start everything
      powershell -ExecutionPolicy Bypass -File .\start_app.ps1 -SkipInstall
      powershell -ExecutionPolicy Bypass -File .\start_app.ps1 -Stop      # stop databases

  Starts: Postgres/TimescaleDB, Redis, ChromaDB (Docker) + FastAPI, Celery worker,
  Celery beat and the Vite frontend, each in its own PowerShell window.
#>
param(
    [switch]$SkipInstall,
    [switch]$Stop
)

# Continue (not Stop): docker/pip write progress to stderr, which PS 5.1 would treat as fatal.
# Failures are detected through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# docker compose v2, fall back to docker-compose v1.
# Deliberately a simple function using $args: an advanced function (param block with
# [Parameter()]) would swallow "-d" as the common -Debug switch.
function Compose {
    $composeArgs = $args
    docker compose version *> $null
    if ($LASTEXITCODE -eq 0) { docker compose @composeArgs } else { docker-compose @composeArgs }
}

if ($Stop) {
    Step "Stopping databases"
    Compose stop db redis chromadb
    Write-Host "Close the FinSight PowerShell windows to stop the app processes."
    exit 0
}

# ---------------------------------------------------------------- 1. .env
Step "Checking .env"
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") { Copy-Item ".env.example" ".env" }
    Fail ".env was missing - created one from .env.example. Fill in OPENROUTER_API_KEY and run again."
}
$envVars = @{}
Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $k, $v = $line.Split("=", 2)
        $envVars[$k.Trim()] = $v.Trim().Trim('"')
    }
}
if (-not $envVars["OPENROUTER_API_KEY"]) { Fail "OPENROUTER_API_KEY is empty in .env" }
$model = if ($envVars["LLM_MODEL"]) { $envVars["LLM_MODEL"] } else { "openai/gpt-4o-mini" }
Write-Host "LLM: $model via OpenRouter"

# ---------------------------------------------------------------- 2. Docker services
Step "Starting Postgres, Redis and ChromaDB in Docker"
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker is not running. Start Docker Desktop and try again." }
Compose up --detach db redis chromadb
if ($LASTEXITCODE -ne 0) { Fail "docker compose failed to start the databases." }

Write-Host "Waiting for Postgres to accept connections..." -NoNewline
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    docker exec finsight_db pg_isready -U postgres *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 2
}
Write-Host ""
if (-not $ready) { Fail "Postgres did not become ready in 60s. Check: docker logs finsight_db" }

# ---------------------------------------------------------------- 3. Python env
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Step "Creating Python virtual environment (.venv)"
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv. Is Python 3.10+ installed and on PATH?" }
}

if (-not $SkipInstall) {
    $req = "backend\requirements.txt"
    $hashFile = ".venv\.requirements.hash"
    $newHash = (Get-FileHash $req).Hash
    $oldHash = if (Test-Path $hashFile) { Get-Content $hashFile } else { "" }
    if ($newHash -ne $oldHash) {
        Step "Installing Python dependencies (first run can take a few minutes)"
        & $py -m pip install --upgrade pip -q
        & $py -m pip install -r $req
        if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }
        Set-Content $hashFile $newHash
    } else {
        Write-Host "Python dependencies up to date."
    }
}

# ---------------------------------------------------------------- 4. Database tables
Step "Creating database tables"
& $py backend\scripts\init_db.py
if ($LASTEXITCODE -ne 0) { Fail "init_db.py failed." }

# ---------------------------------------------------------------- 5. Frontend deps
if (-not $SkipInstall -and -not (Test-Path "frontend\node_modules")) {
    Step "Installing frontend dependencies"
    Push-Location frontend
    npm install
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "npm install failed." }
}

# ---------------------------------------------------------------- 6. Launch services
Step "Launching services in separate windows"
$activate = ".\.venv\Scripts\Activate.ps1"
$services = @(
    @{ Name = "FinSight API";    Cmd = "& '$activate'; uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload" },
    @{ Name = "FinSight Worker"; Cmd = "& '$activate'; celery -A backend.celery_app worker --loglevel=info --pool=solo" },
    @{ Name = "FinSight Beat";   Cmd = "& '$activate'; celery -A backend.celery_app beat --loglevel=info" },
    @{ Name = "FinSight Web";    Cmd = "Set-Location frontend; npm run dev" }
)
foreach ($s in $services) {
    $full = "`$Host.UI.RawUI.WindowTitle = '$($s.Name)'; Set-Location '$Root'; $($s.Cmd)"
    Start-Process powershell -WorkingDirectory $Root -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $full
    Write-Host "  started $($s.Name)"
}

# ---------------------------------------------------------------- 7. Health check
Write-Host "`nWaiting for the API at http://localhost:8001/health ..." -NoNewline
$up = $false
for ($i = 0; $i -lt 45; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:8001/health" -TimeoutSec 2
        if ($r.status -eq "ok") { $up = $true; break }
    } catch { }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 2
}
Write-Host ""
if ($up) {
    Write-Host "API is up." -ForegroundColor Green
    Start-Process "http://localhost:5173"
} else {
    Write-Host "API did not respond in 90s - check the 'FinSight API' window for errors." -ForegroundColor Yellow
}

Write-Host "`nFinSight AI is running:" -ForegroundColor Green
Write-Host "  App:      http://localhost:5173"
Write-Host "  API docs: http://localhost:8001/docs"
Write-Host "  Stop DBs: .\start_app.ps1 -Stop   (close the 4 service windows to stop the app)"
