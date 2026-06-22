param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
Set-Location -LiteralPath $root

$backendPort = 8000
$frontendPort = 5173
$backendPython = Join-Path $root '.venv311\Scripts\python.exe'
$requirementsFile = Join-Path $root 'requirements.txt'
$requirementsStamp = Join-Path $root '.venv311\.requirements.stamp'
$frontendDir = Join-Path $root 'frontend'
$frontendNodeModules = Join-Path $frontendDir 'node_modules'
$statePath = Join-Path $root '.dev-processes.json'

function Get-ListeningProcessNames {
    param([int]$Port)

    try {
        $connections = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
    } catch {
        return @()
    }

    $names = New-Object System.Collections.Generic.List[string]
    foreach ($conn in $connections) {
        try {
            $process = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
            if ($process.ProcessName -and -not $names.Contains($process.ProcessName)) {
                $names.Add($process.ProcessName)
            }
        } catch {
        }
    }

    return $names.ToArray()
}

function Ensure-BackendPython {
    if (Test-Path $backendPython) {
        return
    }

    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw '未找到 .venv311，也没有 py 启动器。请先安装 Python 3.11。'
    }

    Write-Host '未检测到 .venv311，正在使用 Python 3.11 创建虚拟环境...' -ForegroundColor Cyan
    & py -3.11 -m venv .venv311

    if (-not (Test-Path $backendPython)) {
        throw '虚拟环境创建失败，请确认已安装 Python 3.11。'
    }
}

function Ensure-BackendDependencies {
    $needInstall = $true

    if ((Test-Path $requirementsFile) -and (Test-Path $requirementsStamp)) {
        $requirementsTime = (Get-Item $requirementsFile).LastWriteTimeUtc
        $stampTime = (Get-Item $requirementsStamp).LastWriteTimeUtc
        if ($stampTime -ge $requirementsTime) {
            $needInstall = $false
        }
    }

    if (-not $needInstall) {
        Write-Host '后端依赖已是最新，跳过安装。' -ForegroundColor DarkGray
        return
    }

    Write-Host '安装/更新后端依赖...' -ForegroundColor Cyan
    & $backendPython -m pip install -U pip
    & $backendPython -m pip install -r $requirementsFile
    New-Item -ItemType File -Path $requirementsStamp -Force | Out-Null
}

function Ensure-FrontendDependencies {
    if (Test-Path $frontendNodeModules) {
        Write-Host '前端依赖已存在，跳过安装。' -ForegroundColor DarkGray
        return
    }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw '未找到 npm，请先安装 Node.js。'
    }

    Write-Host '安装前端依赖...' -ForegroundColor Cyan
    Push-Location $frontendDir
    try {
        npm install
    } finally {
        Pop-Location
    }
}

function Start-VisibleWindow {
    param(
        [string]$WindowTitle,
        [string]$ScriptPath,
        [string]$WorkingDirectory
    )

    $safeWindowTitle = $WindowTitle.Replace("'", "''")
    $safeScriptPath = $ScriptPath.Replace("'", "''")
    $bootstrapCommand = @"
`$Host.UI.RawUI.WindowTitle = '$safeWindowTitle'
& '$safeScriptPath'
"@

    return Start-Process -FilePath 'powershell.exe' -WorkingDirectory $WorkingDirectory -ArgumentList @(
        '-NoExit',
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-Command', $bootstrapCommand
    ) -PassThru
}

Write-Host '准备启动开发环境...' -ForegroundColor Green

$backendShellId = $null
$frontendShellId = $null

try {
    $backendNames = Get-ListeningProcessNames -Port $backendPort
    if ($backendNames.Count -eq 0) {
        Ensure-BackendPython
        Ensure-BackendDependencies
        $backendScript = Join-Path $scriptDir 'run-backend.ps1'
        $backendShell = Start-VisibleWindow -WindowTitle 'KOP 后端开发服务' -ScriptPath $backendScript -WorkingDirectory $root
        $backendShellId = $backendShell.Id
        Write-Host ('后端已在独立窗口中启动，窗口 PID: {0}' -f $backendShellId) -ForegroundColor Green
    } else {
        Write-Host ('端口 {0} 已在监听，跳过后端启动。占用进程：{1}' -f $backendPort, ($backendNames -join ', ')) -ForegroundColor Yellow
    }

    $frontendNames = Get-ListeningProcessNames -Port $frontendPort
    if ($frontendNames.Count -eq 0) {
        Ensure-FrontendDependencies
        $frontendScript = Join-Path $scriptDir 'run-frontend.ps1'
        $frontendShell = Start-VisibleWindow -WindowTitle 'KOP 前端开发服务' -ScriptPath $frontendScript -WorkingDirectory $root
        $frontendShellId = $frontendShell.Id
        Write-Host ('前端已在独立窗口中启动，窗口 PID: {0}' -f $frontendShellId) -ForegroundColor Green
    } else {
        Write-Host ('端口 {0} 已在监听，跳过前端启动。占用进程：{1}' -f $frontendPort, ($frontendNames -join ', ')) -ForegroundColor Yellow
    }

    $state = [ordered]@{
        startedAt = (Get-Date).ToString('o')
        backendShellId = $backendShellId
        frontendShellId = $frontendShellId
        backendPort = $backendPort
        frontendPort = $frontendPort
    }

    $state | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 -LiteralPath $statePath

    Write-Host ''
    Write-Host '开发环境启动完成。' -ForegroundColor Green
    Write-Host ('后端地址: http://127.0.0.1:{0}' -f $backendPort) -ForegroundColor Cyan
    Write-Host ('前端地址: http://127.0.0.1:{0}' -f $frontendPort) -ForegroundColor Cyan
    Write-Host '前后端会在独立 PowerShell 窗口里持续输出实时日志。' -ForegroundColor Cyan
    Write-Host '停止命令: .\启动脚本\stop-dev.cmd' -ForegroundColor Cyan
    Write-Host '如果服务启动失败，对应窗口会保留，方便直接查看报错。' -ForegroundColor DarkGray
} catch {
    Write-Host ''
    Write-Host ('启动失败: {0}' -f $_.Exception.Message) -ForegroundColor Red
    throw
}
