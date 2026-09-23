# 온순간 아침 창 — Windows 설치
# 가장 쉬운 방법: 도구 폴더의 "설치하기.bat" 을 더블클릭하세요.
# 직접 실행: powershell -ExecutionPolicy Bypass -File install\install_windows.ps1 [-Time 06:00] [-Uninstall]
param([switch]$Uninstall, [string]$Time = "06:00")

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$TaskName = "OnMomentMorning"
$Root     = Split-Path -Parent $PSScriptRoot
$Script   = Join-Path $Root "onmoment_morning.py"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "OnMoment Morning.lnk"
$DataDir  = Join-Path $env:USERPROFILE "OnMoment\morning"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
try { Start-Transcript -Path (Join-Path $DataDir "install.log") -Append | Out-Null } catch {}

function Step($n, $msg) { Write-Host ""; Write-Host "[$n] $msg" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    !!  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "    XX  $m" -ForegroundColor Red }
function Finish($code) { try { Stop-Transcript | Out-Null } catch {}; exit $code }

function Remove-Old {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $Shortcut -ErrorAction SilentlyContinue
}

if ($Uninstall) {
    Remove-Old
    Write-Host "제거했습니다. ($DataDir 의 기록은 남겨 두었습니다)"
    Finish 0
}

Write-Host "온순간 아침 창 설치를 시작합니다." -ForegroundColor White
Write-Host "도구 폴더: $Root"

# ------------------------------------------------------------------ 1. Python
Step 1 "Python 확인"
function Find-Python {
    $cands = @()
    try {
        $p = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { $cands += "$p".Trim() }
    } catch {}
    foreach ($n in "python", "python3") {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        # WindowsApps 안의 python.exe 는 Microsoft Store로 보내는 가짜 실행 파일이라 제외
        if ($c -and $c.Source -notlike "*WindowsApps*") { $cands += $c.Source }
    }
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" `
        -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    foreach ($c in $cands) {
        if ($c -and (Test-Path $c)) {
            $ok = & $c -c "import sys; print(sys.version_info >= (3, 9))" 2>$null
            if ("$ok".Trim() -eq "True") { return $c }
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Warn "Python 3.9 이상을 찾지 못했습니다."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "    winget으로 Python 3.12를 설치합니다 (1~2분)..."
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $py = Find-Python
    }
}
if (-not $py) {
    Fail "Python을 설치하지 못했습니다. 열리는 페이지에서 Python을 설치하고 (첫 화면의 'Add python.exe to PATH' 체크),"
    Fail "설치하기.bat 을 다시 실행해 주세요."
    Start-Process "https://www.python.org/downloads/windows/"
    Finish 1
}
Ok $py
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

# ------------------------------------------------------------------ 2. 파일
Step 2 "도구 파일 확인"
$missing = @("onmoment_morning.py", "template.html", "config.example.json", "fallback\brief.json") |
    Where-Object { -not (Test-Path (Join-Path $Root $_)) }
if ($missing) {
    Fail "다음 파일이 없습니다: $($missing -join ', ')"
    Fail "zip 압축을 끝까지 풀었는지, 설치하기.bat 이 onmoment_morning.py 와 같은 폴더에 있는지 확인해 주세요."
    Finish 1
}
# 인터넷에서 받은 zip의 '차단됨' 표시 해제
Get-ChildItem -Path $Root -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
if (-not (Test-Path (Join-Path $Root "config.json"))) {
    Copy-Item (Join-Path $Root "config.example.json") (Join-Path $Root "config.json")
}
Ok "파일 이상 없음"

# ------------------------------------------------------------------ 3. Claude Code
Step 3 "Claude Code 확인"
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    foreach ($c in "$env:USERPROFILE\.local\bin\claude.exe", "$env:APPDATA\npm\claude.cmd") { if (Test-Path $c) { $claude = $c } }
}
if ($claude) {
    Ok "claude CLI 발견. 응답을 시험합니다 (최대 90초)..."
    Push-Location $Root
    & $py $Script --diagnose
    Pop-Location
} else {
    Warn "claude CLI를 찾지 못했습니다. 지금은 오프라인 내장 조언으로 열립니다."
    Warn "Claude Code 설치: PowerShell에서  irm https://claude.ai/install.ps1 | iex  실행 후, claude 를 한 번 실행해 로그인하세요."
}

# ------------------------------------------------------------------ 4. 첫 실행
Step 4 "오늘의 창을 엽니다 (내장 조언이 먼저 뜨고, Claude의 조언이 1~3분 뒤 자동으로 바뀝니다)"
Push-Location $Root
& $py $Script
$runCode = $LASTEXITCODE
Pop-Location
if ($runCode -ne 0) {
    Fail "실행 중 오류가 났습니다. 아래 로그 마지막 부분을 Claude에게 보여 주세요:"
    Get-Content (Join-Path $DataDir "morning.log") -Tail 25 -ErrorAction SilentlyContinue
    Finish 1
}
Ok "창을 열었습니다"

# ------------------------------------------------------------------ 5. 매일 06:00
Step 5 "매일 $Time 자동 실행 예약"
Remove-Old
try {
    $action   = New-ScheduledTaskAction -Execute $pyw -Argument "`"$Script`"" -WorkingDirectory $Root
    $trigger  = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "온순간 아침 창: 매일 아침 대화 기록 기반 조언 대시보드" -Force -ErrorAction Stop | Out-Null
    Ok "작업 스케줄러에 '$TaskName' 등록 (6시에 꺼져 있었다면 켜진 직후 실행)"
} catch {
    Warn "작업 스케줄러 등록 실패: $($_.Exception.Message)"
    Warn "로그인 시 자동 실행(다음 단계)은 그대로 동작합니다."
}

# ------------------------------------------------------------------ 6. 로그인 시
Step 6 "컴퓨터를 켜고 로그인할 때 자동 실행"
try {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($Shortcut)
    $lnk.TargetPath = $pyw
    $lnk.Arguments = "`"$Script`""
    $lnk.WorkingDirectory = $Root
    $lnk.Description = "온순간 아침 창"
    $lnk.Save()
    Ok "시작프로그램에 등록"
} catch {
    Warn "시작프로그램 등록 실패: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "설치 완료. 매일 $Time, 그리고 로그인할 때마다 온순간 아침 창이 열립니다." -ForegroundColor Green
Write-Host "  지금 다시 열기: 지금열기.bat  |  상태 점검: 점검하기.bat  |  제거: 제거하기.bat"
Write-Host "  일정 날짜 입력: $Root\config.json 의 milestones"
Finish 0
