param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
Set-Location -LiteralPath $root

$pythonExe = Join-Path $root '.venv311\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    throw '未找到 .venv311\Scripts\python.exe，请先创建虚拟环境。'
}

Write-Output '启动后端中...'
& $pythonExe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
