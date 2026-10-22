# Windows PowerShell 5.1 / PowerShell 7 local development launcher.
[CmdletBinding()]
param(
    [ValidateSet('weapp', 'h5')]
    [string]$Target = 'weapp',
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$Target = $Target.ToLowerInvariant()
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$pythonPath = Join-Path $backendRoot '.venv/Scripts/python.exe'
$taroPath = Join-Path $frontendRoot 'node_modules/@tarojs/cli/bin/taro'
$ownedProcesses = @()
$optionalWorkerId = 0

function Test-LocalPort([int]$Port) {
    $connection = New-Object System.Net.Sockets.TcpClient
    try { return $connection.ConnectAsync('127.0.0.1', $Port).Wait(500) }
    catch { return $false }
    finally { $connection.Dispose() }
}

function Test-LevelUpBackend {
    try {
        $spec = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/openapi.json' -TimeoutSec 2
        $routes = $spec.paths.PSObject.Properties.Name
        return $spec.info.title -eq 'LevelUp API' -and
            $routes -contains '/api/v1/knowledge-map' -and
            $routes -contains '/api/v1/analytics' -and
            $routes -contains '/api/v1/materials/document' -and
            $routes -contains '/api/v1/knowledge/capabilities'
    } catch { return $false }
}

function Start-LoggedProcess([string]$File, [string[]]$Arguments, [string]$Directory, [string]$LogPrefix, [switch]$Wait) {
    Write-Host "Log: $LogPrefix.log"
    Write-Host "Errors: $LogPrefix.error.log"
    return Start-Process -FilePath $File -ArgumentList $Arguments -WorkingDirectory $Directory `
        -WindowStyle Hidden -RedirectStandardOutput "$LogPrefix.log" `
        -RedirectStandardError "$LogPrefix.error.log" -Wait:$Wait -PassThru
}

function Stop-OwnedProcess($Process) {
    $Process.Refresh()
    if (-not $Process.HasExited) {
        # Stop only the process trees started by this invocation, including reload workers.
        try { & taskkill.exe /PID $Process.Id /T /F *> $null } catch {}
    }
}

function Get-RunningDevelopmentProcesses([object[]]$Children, [int]$OptionalWorkerId) {
    foreach ($child in $Children) {
        $child.Refresh()
        if ($child.HasExited) {
            if ($child.Id -eq $OptionalWorkerId) {
                Write-Warning 'The optional knowledge executor stopped. Core learning and the frontend remain running; check backend/logs/start-knowledge.error.log.'
                continue
            }
            throw "A development process stopped (exit $($child.ExitCode)). Check backend/logs and frontend/logs."
        }
        $child
    }
}

function Get-KnowledgeWorkerPlan {
    $output = & $pythonPath -m app.knowledge.worker --check
    if ($LASTEXITCODE -ne 0) { throw 'Unable to check optional knowledge worker configuration.' }
    return $output | ConvertFrom-Json
}

foreach ($requiredPath in @($pythonPath, $taroPath, (Join-Path $backendRoot '.env'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Missing $requiredPath. Run scripts/setup.ps1 and configure backend/.env first."
    }
}
$nodePath = (Get-Command node.exe -ErrorAction Stop).Source
$reuseBackend = Test-LocalPort 8000
if ($reuseBackend -and -not (Test-LevelUpBackend)) {
    throw 'Port 8000 is occupied by an outdated or unrelated service. Stop that service and run this script again.'
}
if ($Target -eq 'h5' -and (Test-LocalPort 10086)) {
    throw 'Port 10086 is occupied. Stop the existing H5 preview before starting another one.'
}
if ($Check) {
    Write-Host 'Dependencies and backend/.env found; required ports checked.'
    Write-Host "Frontend target: $Target"
    Write-Host "Reuse existing compatible backend: $reuseBackend"
    Push-Location -LiteralPath $backendRoot
    try { Get-KnowledgeWorkerPlan | ConvertTo-Json -Compress } finally { Pop-Location }
    return
}

$backendLogRoot = Join-Path $backendRoot 'logs'
$frontendLogRoot = Join-Path $frontendRoot 'logs'
New-Item -ItemType Directory -Path $backendLogRoot, $frontendLogRoot -Force | Out-Null

try {
        Write-Host 'Applying database migrations...'
        # PowerShell 5.1 can lose ExitCode when redirected processes are only polled.
        # Wait here so both zero and nonzero migration exits remain distinguishable.
        $migrationProcess = Start-LoggedProcess $pythonPath @('-m', 'app.migrate') $backendRoot (Join-Path $backendLogRoot 'start-migrate') -Wait
        $ownedProcesses += $migrationProcess
        if ($null -eq $migrationProcess.ExitCode) {
            throw "Unable to read the migration process exit code. Read $backendLogRoot/start-migrate.log and start-migrate.error.log."
        }
        if ($migrationProcess.ExitCode -ne 0) {
            throw "Database migration failed (exit $($migrationProcess.ExitCode)). Check MySQL and backend/.env. Details: $backendLogRoot/start-migrate.error.log"
        }
        $ownedProcesses = @($ownedProcesses | Where-Object { $_.Id -ne $migrationProcess.Id })
    if ($reuseBackend) {
        Write-Host 'Using the existing compatible LevelUp backend on port 8000.'
    } else {
        $backendProcess = Start-LoggedProcess $pythonPath @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload', '--reload-dir', 'app') $backendRoot (Join-Path $backendLogRoot 'start-backend')
        $ownedProcesses += $backendProcess
        $deadline = (Get-Date).AddSeconds(45)
        while (-not (Test-LevelUpBackend)) {
            $backendProcess.Refresh()
            if ($backendProcess.HasExited -or (Get-Date) -ge $deadline) {
                throw "Backend did not start. Read $backendLogRoot/start-backend.error.log."
            }
            Start-Sleep -Milliseconds 500
        }
    }

    Push-Location -LiteralPath $backendRoot
    try { $knowledgePlan = Get-KnowledgeWorkerPlan } finally { Pop-Location }
    if ($knowledgePlan.start_worker) {
        $workerState = $null
        Push-Location -LiteralPath $backendRoot
        try {
            $stateOutput = & $pythonPath -m app.knowledge.worker --status
            if ($LASTEXITCODE -eq 0) { $workerState = $stateOutput | ConvertFrom-Json }
        } finally { Pop-Location }
        if ($workerState -and $workerState.worker_running) {
            Write-Host 'Using the existing knowledge executor; this launcher will not stop it.'
        } else {
            $knowledgeProcess = Start-LoggedProcess $pythonPath @('-m','app.knowledge.worker') $backendRoot (Join-Path $backendLogRoot 'start-knowledge')
            $ownedProcesses += $knowledgeProcess
            $optionalWorkerId = $knowledgeProcess.Id
            Write-Host 'Knowledge executor started; activity is recorded in backend/logs/start-knowledge.error.log.'
        }
    } else {
        Write-Host "Knowledge executor inactive: $($knowledgePlan.reason_code)"
    }

    $frontendProcess = Start-LoggedProcess $nodePath @("`"$taroPath`"", 'build', '--type', $Target, '--watch') $frontendRoot (Join-Path $frontendLogRoot "start-$Target")
    $ownedProcesses += $frontendProcess
    Write-Host ''
    Write-Host 'API documentation: http://127.0.0.1:8000/docs'
    if ($Target -eq 'weapp') {
        Write-Host "WeChat compilation is starting. Import $frontendRoot into WeChat DevTools."
    } else {
        Write-Host 'H5 preview (available after compilation): http://127.0.0.1:10086'
    }
    Write-Host 'Keep this terminal open. Press Ctrl+C to stop the processes started here.'

    while ($true) {
        $ownedProcesses = @(Get-RunningDevelopmentProcesses $ownedProcesses $optionalWorkerId)
        Start-Sleep -Milliseconds 500
    }
} finally {
    for ($index = $ownedProcesses.Count - 1; $index -ge 0; $index--) { Stop-OwnedProcess $ownedProcesses[$index] }
    Write-Host 'Stopped processes started by this launcher.'
}
