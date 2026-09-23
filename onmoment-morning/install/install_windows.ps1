# 온순간 아침 창 — Windows 설치
# 매일 06:00 (컴퓨터가 꺼져 있었다면 켜진 직후) + 로그인할 때마다 실행합니다.
# 사용법 (PowerShell):  powershell -ExecutionPolicy Bypass -File install\install_windows.ps1
# 제거:                  powershell -ExecutionPolicy Bypass -File install\install_windows.ps1 -Uninstall
param([switch]$Uninstall, [string]$Time = "06:00")

$TaskName = "OnMomentMorning"
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "제거했습니다. (~\OnMoment\morning 의 기록은 남겨 두었습니다)"
    exit 0
}

$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "onmoment_morning.py"

# pythonw.exe (콘솔 창 없이 실행) 찾기
$py = $null
try { $py = (& py -3 -c "import sys; print(sys.executable)") 2>$null } catch {}
if (-not $py) { $cmd = Get-Command python -ErrorAction SilentlyContinue; if ($cmd) { $py = $cmd.Source } }
if (-not $py) { Write-Error "Python 3가 필요합니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요."; exit 1 }
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Warning "claude CLI를 찾지 못했습니다. 설치 전까지는 오프라인 조언으로 열립니다. (또는 ANTHROPIC_API_KEY 설정)"
}

$config = Join-Path $Root "config.json"
if (-not (Test-Path $config)) { Copy-Item (Join-Path $Root "config.example.json") $config }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$Script`"" -WorkingDirectory $Root
$daily = New-ScheduledTaskTrigger -Daily -At $Time
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT1M"   # 로그인 1분 뒤 (네트워크 연결 대기)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($daily, $logon) -Settings $settings `
    -Principal $principal -Description "온순간 아침 창: 매일 아침 대화 기록 기반 조언 대시보드" -Force | Out-Null

Write-Host ""
Write-Host "설치 완료: 매일 $Time, 그리고 로그인할 때마다 온순간 아침 창이 열립니다."
Write-Host "지금 한 번 열어 봅니다..."
Start-ScheduledTask -TaskName $TaskName
