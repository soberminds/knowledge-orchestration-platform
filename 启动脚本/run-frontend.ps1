param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$frontendDir = Join-Path $root 'frontend'
Set-Location -LiteralPath $frontendDir

try {
    $Host.UI.RawUI.WindowTitle = 'KOP 前端开发服务'
} catch {
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw '未找到 npm，请先安装 Node.js。'
}

Write-Host '前端启动中...' -ForegroundColor Green
Write-Host '访问地址: http://127.0.0.1:5173' -ForegroundColor Cyan
Write-Host '按 Ctrl + C 可以停止前端服务。' -ForegroundColor DarkGray
Write-Host ''

npm run dev -- --host 127.0.0.1 --port 5173
