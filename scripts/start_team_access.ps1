# 同事访问：一键启动服务（需保持本窗口/电脑开机）
# 管理员运行可自动放行防火墙 8787

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

# 防火墙（需管理员）
$rule = Get-NetFirewallRule -DisplayName "BLUETTI Workflow 8787" -ErrorAction SilentlyContinue
if (-not $rule) {
  try {
    New-NetFirewallRule -DisplayName "BLUETTI Workflow 8787" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8787 | Out-Null
    Write-Host "已放行防火墙 TCP 8787"
  } catch {
    Write-Host "提示: 请以管理员运行本脚本以放行防火墙，或手动放行 8787"
  }
}

$p = (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1
if ($p) { Stop-Process -Id $p -Force; Start-Sleep 1 }

$py = Join-Path $Root ".venv\Scripts\python.exe"
Start-Process -FilePath $py -ArgumentList "scripts/run_batch.py","serve","--host","0.0.0.0","--port","8787" -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep 3

$lan = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" } | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " 同事访问（同一局域网）: http://${lan}:8787"
Write-Host " 本机访问: http://127.0.0.1:8787"
Write-Host "========================================" -ForegroundColor Green
Write-Host "保持此电脑开机；关机后同事无法访问。"
