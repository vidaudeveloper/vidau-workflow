# 异地同事公网访问 — 启动本机服务 + Pinggy 隧道（无需部署服务器）
# 保持本窗口不要关；免费隧道约 60 分钟有效，到期重新运行本脚本

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$p = (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1
if ($p) { Stop-Process -Id $p -Force; Start-Sleep 1 }

$py = Join-Path $Root ".venv\Scripts\python.exe"
Start-Process -FilePath $py -ArgumentList "scripts/run_batch.py","serve","--host","0.0.0.0","--port","8787" -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep 3

Write-Host ""
Write-Host "正在建立公网隧道（Pinggy）…" -ForegroundColor Cyan
Write-Host "出现 https://*.pinggy.net 或 *.pinggy-free.link 地址后，发给异地同事即可。" -ForegroundColor Yellow
Write-Host "本窗口请保持打开；关闭或 60 分钟后隧道失效。" -ForegroundColor Yellow
Write-Host ""

ssh -o StrictHostKeyChecking=no -p 443 -R0:127.0.0.1:8787 a.pinggy.io
