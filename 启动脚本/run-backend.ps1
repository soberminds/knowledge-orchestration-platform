param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
Set-Location -LiteralPath $root

try {
    $Host.UI.RawUI.WindowTitle = 'KOP 后端开发服务'
} catch {
}

$pythonExe = Join-Path $root '.venv311\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    throw '未找到 .venv311\Scripts\python.exe，请先创建虚拟环境。'
}

Write-Host '后端启动中...' -ForegroundColor Green
Write-Host '访问地址: http://127.0.0.1:8000' -ForegroundColor Cyan
Write-Host '按 Ctrl + C 可以停止后端服务。' -ForegroundColor DarkGray
Write-Host ''

& $pythonExe -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
