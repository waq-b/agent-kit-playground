<#
.SYNOPSIS
    Start the FastAPI backend and the React dev server together.

.DESCRIPTION
    Windows/PowerShell counterpart to dev.sh. Output from both processes is
    prefixed and colour-coded; Ctrl-C stops both. Manual equivalents are in the
    README if you'd rather run them separately.
#>

$ErrorActionPreference = 'Stop'

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv     = Join-Path $Root '.venv'
$Frontend = Join-Path $Root 'frontend'
$ApiHost  = if ($env:AGENT_KIT_HOST) { $env:AGENT_KIT_HOST } else { '127.0.0.1' }
$ApiPort  = if ($env:AGENT_KIT_PORT) { $env:AGENT_KIT_PORT } else { '8000' }

function Stop-WithMessage([string]$Message) {
    Write-Host $Message -ForegroundColor Red
    exit 1
}

# On Windows a venv puts executables in Scripts\; honour both layouts so this
# also works under PowerShell on macOS/Linux.
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) { $VenvPython = Join-Path $Venv 'bin/python' }

# --- preflight ---------------------------------------------------------------

if (-not (Test-Path $Venv)) {
    Stop-WithMessage @"
No Python virtualenv found at .venv\

The backend runs from this project's own virtualenv. Create it with:

    python -m venv .venv
    .venv\Scripts\pip install -e ".[dev]"

then run .\dev.ps1 again.
"@
}

if (-not (Test-Path $VenvPython)) {
    Stop-WithMessage @"
'.venv' exists but has no usable Python interpreter inside it.

It may be a partially created or non-standard virtualenv. Remove it and rebuild:

    Remove-Item -Recurse -Force .venv
    python -m venv .venv
    .venv\Scripts\pip install -e ".[dev]"
"@
}

& $VenvPython -c 'import uvicorn, fastapi' 2>$null
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage @"
The virtualenv is missing the backend's dependencies (fastapi/uvicorn).

Install the project into it with:

    .venv\Scripts\pip install -e ".[dev]"
"@
}

if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Stop-WithMessage @"
Frontend dependencies are not installed.

Install them with:

    cd frontend; npm install

then run .\dev.ps1 again.
"@
}

# --- run ---------------------------------------------------------------------

Write-Host 'agent-kit playground' -ForegroundColor Green
Write-Host "  api  http://${ApiHost}:${ApiPort}" -ForegroundColor Cyan
Write-Host '  web  http://localhost:5173' -ForegroundColor Magenta
Write-Host ''

$jobs = @()

$jobs += Start-Job -Name 'api' -ScriptBlock {
    param($Root, $Python, $ApiHost, $ApiPort)
    Set-Location $Root
    & $Python -m uvicorn agent_kit.playground.app:app --host $ApiHost --port $ApiPort --reload 2>&1
} -ArgumentList $Root, $VenvPython, $ApiHost, $ApiPort

$jobs += Start-Job -Name 'web' -ScriptBlock {
    param($Frontend, $ApiHost, $ApiPort)
    Set-Location $Frontend
    $env:AGENT_KIT_API = "http://${ApiHost}:${ApiPort}"
    npm run dev --silent 2>&1
} -ArgumentList $Frontend, $ApiHost, $ApiPort

try {
    while ($true) {
        foreach ($job in $jobs) {
            $colour = if ($job.Name -eq 'api') { 'Cyan' } else { 'Magenta' }
            foreach ($line in (Receive-Job -Job $job)) {
                Write-Host "[$($job.Name)] " -ForegroundColor $colour -NoNewline
                Write-Host $line
            }
        }
        if ($jobs | Where-Object { $_.State -eq 'Completed' -or $_.State -eq 'Failed' }) {
            Write-Host 'One process exited — shutting the other down.' -ForegroundColor Red
            break
        }
        Start-Sleep -Milliseconds 200
    }
}
finally {
    $jobs | Stop-Job -ErrorAction SilentlyContinue
    $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host 'Both processes stopped.' -ForegroundColor Green
}
