param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
Set-Location -LiteralPath $root

$statePath = Join-Path $root '.dev-processes.json'
$backendPort = 8000
$frontendPort = 5173

function Stop-ProcessSafely {
    param([int]$ProcessId)

    if ($ProcessId -gt 0) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-PortListeners {
    param([int]$Port)

    try {
        $connections = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
    } catch {
        return
    }

    foreach ($conn in $connections) {
        try {
            $process = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
            Write-Host ('停止端口 {0} 对应进程: {1} ({2})' -f $Port, $process.ProcessName, $conn.OwningProcess) -ForegroundColor Yellow
        } catch {
            Write-Host ('停止端口 {0} 对应进程: {1}' -f $Port, $conn.OwningProcess) -ForegroundColor Yellow
        }
        Stop-ProcessSafely -ProcessId $conn.OwningProcess
    }
}

Write-Host '正在停止开发环境...' -ForegroundColor Green

if (Test-Path $statePath) {
    try {
        $state = Get-Content -Encoding UTF8 -LiteralPath $statePath | ConvertFrom-Json
        Stop-ProcessSafely -ProcessId ([int]$state.backendShellId)
        Stop-ProcessSafely -ProcessId ([int]$state.frontendShellId)
    } catch {
    }
}

Stop-PortListeners -Port $backendPort
Stop-PortListeners -Port $frontendPort

if (Test-Path $statePath) {
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}

Write-Host '开发环境已停止。' -ForegroundColor Green
