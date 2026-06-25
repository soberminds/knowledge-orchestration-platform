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
#找到项目虚拟环境的命令目录。
$venvScripts = Join-Path $root '.venv311\Scripts'
#告诉子进程：当前虚拟环境是 .venv311。
$env:VIRTUAL_ENV = Join-Path $root '.venv311'
#把 .venv311\Scripts 放到命令搜索优先级第一位。
$env:PATH = "$venvScripts;$env:PATH"

Write-Host 'Starting backend...' -ForegroundColor Green
Write-Host 'Backend URL: http://127.0.0.1:8000' -ForegroundColor Cyan
Write-Host 'Press Ctrl + C to stop the backend server.' -ForegroundColor DarkGray
Write-Host ''

& $pythonExe -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
