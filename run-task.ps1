# run-task.ps1 — 带自动重试的 opencode 任务包装
#
# 用途：上游（cheapai）存在间歇性断流。本脚本把「等一会、重试、换模型」自动化，
#       避免断一次就要人肉重跑整个任务 —— 那是最烧钱也最磨人的事。
#
# 用法：
#   .\run-task.ps1 "你的任务提示词"
#   .\run-task.ps1 "你的任务提示词" -Model cheapai/grok-4.6
#
# 重试策略（见 docs/5-工作协议.md 第 3 节）：
#   第 1 次：grok-4.7
#   第 2 次：等 10 秒，grok-4.7
#   第 3 次：等 30 秒，grok-4.7
#   第 4 次：换 grok-4.6
#   全失败 → 退出码 1，提示写 QUESTIONS.md

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Prompt,

    [string]$Model = "cheapai/grok-4.7",
    [string]$FallbackModel = "cheapai/grok-4.6",
    [int[]]$WaitSeconds = @(0, 10, 30)
)

$ErrorActionPreference = "Continue"
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "task-$stamp.log"

# 上游不可用的特征串（实测见 docs/5-工作协议.md 第 3 节）
$UPSTREAM_DOWN = @("模型服务暂时不可用", "请稍后重试", "AI_APICallError", "502", "503", "504")

function Test-UpstreamDown([string]$output) {
    foreach ($pat in $UPSTREAM_DOWN) {
        if ($output -match [regex]::Escape($pat)) { return $true }
    }
    return $false
}

$attempts = @()
foreach ($w in $WaitSeconds) { $attempts += @{ Model = $Model; Wait = $w } }
$attempts += @{ Model = $FallbackModel; Wait = 0 }

$total = $attempts.Count
$i = 0

foreach ($a in $attempts) {
    $i++
    if ($a.Wait -gt 0) {
        Write-Host "[等 $($a.Wait)s] 上游可能抖动，稍后重试..." -ForegroundColor Yellow
        Start-Sleep -Seconds $a.Wait
    }

    Write-Host ""
    Write-Host "===== 第 $i/$total 次尝试 | 模型 $($a.Model) =====" -ForegroundColor Cyan

    $out = & opencode run $Prompt --model $a.Model 2>&1 | Tee-Object -FilePath $logFile -Append
    $text = ($out | Out-String)

    if (-not (Test-UpstreamDown $text)) {
        Write-Host ""
        Write-Host "[OK] 任务完成（第 $i 次尝试，模型 $($a.Model)）" -ForegroundColor Green
        Write-Host "[日志] $logFile" -ForegroundColor DarkGray
        exit 0
    }

    Write-Host "[FAIL] 本次疑似上游不可用" -ForegroundColor Red
}

Write-Host ""
Write-Host "[全部失败] $total 次尝试均未成功，上游持续不可用。" -ForegroundColor Red
Write-Host "请按 docs/5-工作协议.md 第 6 节，把情况写进 QUESTIONS.md 后停下等人。" -ForegroundColor Red
Write-Host "[日志] $logFile" -ForegroundColor DarkGray
exit 1
