<#
.SYNOPSIS
    Start just the FastAPI backend.

.DESCRIPTION
    Windows/PowerShell counterpart to backend.sh. For both the backend and the
    frontend dev server together, use .\dev.ps1 instead.
#>

$ErrorActionPreference = 'Stop'

$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv    = Join-Path $Root '.venv'
$ApiHost = if ($env:AGENT_KIT_HOST) { $env:AGENT_KIT_HOST } else { '127.0.0.1' }
$ApiPort = if ($env:AGENT_KIT_PORT) { $env:AGENT_KIT_PORT } else { '8000' }

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

then run .\backend.ps1 again.
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

# --- run ---------------------------------------------------------------------

Write-Host "agent-kit backend  http://${ApiHost}:${ApiPort}" -ForegroundColor Green

Set-Location $Root
& $VenvPython -m uvicorn agent_kit.playground.app:app --host $ApiHost --port $ApiPort --reload
