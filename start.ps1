#requires -version 5.1
<#
.SYNOPSIS
    MineAgent 一键启动脚本。

.DESCRIPTION
    自动完成：Python 虚拟环境 → 后端依赖 → 前端依赖 → 前端构建 → 启动服务 → 打开浏览器。

.PARAMETER Port
    服务端口，默认 8000。

.PARAMETER Dev
    开发模式：后端 8000 + 前端 Vite 5173 双进程热更新。

.PARAMETER Rebuild
    强制重新构建前端。

.PARAMETER NoBrowser
    不自动打开浏览器。

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Port 8080 -Dev
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Dev,
    [switch]$Rebuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$Frontend = Join-Path $Root 'frontend'
$Backend = Join-Path $Root 'backend'
$Task = Join-Path $Root 'tools\mock_llm.py'

function Info($m) { Write-Host "  $m" -ForegroundColor Gray }
function Step($m) { Write-Host "`n▶ $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "  ✔ $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Die($m) {
    Write-Host "`n✘ $m" -ForegroundColor Red
    exit 1
}

Write-Host @"

  ╔══════════════════════════════════════╗
  ║   MineAgent · Agent 编排画布         ║
  ╚══════════════════════════════════════╝

"@ -ForegroundColor Magenta

# ---------------------------------------------------------------- 1. Python
Step '检查 Python 环境'
$pyCmd = $null
$pyArgs = @()
foreach ($cand in @(@('python'), @('py', '-3'))) {
    try {
        $ver = & $cand[0] $cand[1..($cand.Length - 1)] --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$ver" -match 'Python 3\.(\d+)') {
            if ([int]$Matches[1] -lt 9) { continue }
            $pyCmd = $cand[0]
            $pyArgs = $cand[1..($cand.Length - 1)]
            break
        }
    } catch { }
}
if (-not $pyCmd) { Die '没有找到 Python 3.9+，请先安装：https://www.python.org/downloads/' }
Ok "$(& $pyCmd $pyArgs --version 2>&1)"

# ---------------------------------------------------------------- 2. venv
Step '准备 Python 虚拟环境'
if (-not (Test-Path $VenvPy)) {
    Info '首次运行，创建 .venv …'
    & $pyCmd $pyArgs -m venv $Venv
    if (-not (Test-Path $VenvPy)) { Die '创建虚拟环境失败' }
}
Ok ".venv 就绪"

Step '检查后端依赖'
& $VenvPy -c "import fastapi, uvicorn, pydantic" 2>$null
if ($LASTEXITCODE -ne 0) {
    Info '安装 backend/requirements.txt …'
    & $VenvPy -m pip install --upgrade pip --quiet
    & $VenvPy -m pip install -r (Join-Path $Backend 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Die '后端依赖安装失败，请检查网络或换用国内镜像源' }
}
Ok '后端依赖就绪'

# ---------------------------------------------------------------- 3. 前端
if ($Dev) {
    Step '开发模式：准备前端依赖'
    if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
        Info 'npm install …'
        Push-Location $Frontend
        npm install --no-audit --no-fund
        Pop-Location
    }
    Ok '前端依赖就绪'

    Step '启动开发服务'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', 'npm run dev' -WorkingDirectory $Frontend
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/k', "`"$VenvPy`" -m uvicorn app.main:app --reload --host 0.0.0.0 --port $Port" `
        -WorkingDirectory $Backend
    if (-not $NoBrowser) {
        Start-Sleep -Seconds 3
        Start-Process 'http://127.0.0.1:5173'
    }
    Write-Host "`n  开发模式已启动：前端 http://127.0.0.1:5173 ，后端 http://127.0.0.1:$Port`n" -ForegroundColor Green
    exit 0
}

Step '准备前端'
$nodeOk = $false
try { $null = node --version; $nodeOk = $true } catch { }
if (-not $nodeOk) {
    Warn '没有检测到 Node.js，跳过前端构建（已有 dist 的话仍可运行）'
} else {
    if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
        Info '首次运行，npm install（约 1-2 分钟）…'
        Push-Location $Frontend
        npm install --no-audit --no-fund
        Pop-Location
        if ($LASTEXITCODE -ne 0) { Die 'npm install 失败' }
    }
    $distIndex = Join-Path $Frontend 'dist\index.html'
    $needBuild = $Rebuild -or (-not (Test-Path $distIndex))
    if (-not $needBuild) {
        $distTime = (Get-Item $distIndex).LastWriteTime
        $srcDir = Join-Path $Frontend 'src'
        $newer = Get-ChildItem $srcDir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -gt $distTime } | Select-Object -First 1
        if ($newer) { $needBuild = $true }
    }
    if ($needBuild) {
        Info '构建前端 …'
        Push-Location $Frontend
        npm run build
        Pop-Location
        if ($LASTEXITCODE -ne 0) { Die '前端构建失败' }
    }
    Ok '前端就绪'
}

# ---------------------------------------------------------------- 4. 启动
$url = "http://127.0.0.1:$Port"
$lanIps = @()
try {
    $lanIps = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
        Where-Object { $_.AddressFamily -eq 'InterNetwork' -and $_.ToString() -notlike '127.*' } |
        ForEach-Object { $_.ToString() }
} catch { }

Step '启动 MineAgent'
Write-Host ""
Write-Host "  本机访问： $url" -ForegroundColor Green
foreach ($ip in $lanIps) {
    Write-Host "  局域网：   http://${ip}:$Port" -ForegroundColor DarkGray
}
Write-Host "  没有 API Key？另开一个窗口运行：" -ForegroundColor DarkGray
Write-Host "      .\.venv\Scripts\python.exe tools\mock_llm.py --port 8012" -ForegroundColor DarkGray
Write-Host "  然后在「用户中心」把 Base URL 填 http://127.0.0.1:8012/v1" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  按 Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    try {
        Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden `
            -ArgumentList '-NoProfile', '-Command', "Start-Sleep -Seconds 2; Start-Process '$url'"
    } catch { }
}

Set-Location $Backend
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
& $VenvPy -m uvicorn app.main:app --host 0.0.0.0 --port $Port
