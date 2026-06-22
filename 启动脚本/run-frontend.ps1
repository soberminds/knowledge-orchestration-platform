param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$frontendDir = Join-Path $root 'frontend'
Set-Location -LiteralPath $frontendDir

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw '未找到 npm，请先安装 Node.js。'
}

Write-Output '启动前端中...'
npm run dev -- --host 127.0.0.1 --port 5173
