param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
Set-Location -LiteralPath $root

try {
    $Host.UI.RawUI.WindowTitle = 'KOP Backend Dev Server'
} catch {
}

$pythonExe = Join-Path $root '.venv311\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python virtual environment was not found: .venv311\Scripts\python.exe. Please create .venv311 with Python 3.11 first.'
}

Write-Host 'Starting backend...' -ForegroundColor Green
Write-Host 'Backend URL: http://127.0.0.1:8000' -ForegroundColor Cyan
Write-Host 'Press Ctrl + C to stop the backend server.' -ForegroundColor DarkGray
Write-Host ''

& $pythonExe -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
