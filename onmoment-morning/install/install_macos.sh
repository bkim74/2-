#!/bin/bash
# 온순간 아침 창 — macOS 설치
# 매일 06:00 (잠자기 중이었다면 깨어난 직후) + 로그인할 때마다 실행합니다.
# 사용법: bash install/install_macos.sh        제거: bash install/install_macos.sh --uninstall
set -euo pipefail
LABEL="kr.onmoment.morning"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "제거했습니다. (~/OnMoment/morning 의 기록은 남겨 두었습니다)"
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || true)"
[[ -z "$PY" ]] && { echo "python3가 필요합니다 (xcode-select --install 또는 brew install python)"; exit 1; }
CLAUDE_DIR="$(dirname "$(command -v claude 2>/dev/null || echo /usr/local/bin/claude)")"
command -v claude >/dev/null || echo "⚠ claude CLI를 찾지 못했습니다. 설치 전까지는 오프라인 조언으로 열립니다."
[[ -f "$ROOT/config.json" ]] || cp "$ROOT/config.example.json" "$ROOT/config.json"
HOUR="${HOUR:-6}"; MINUTE="${MINUTE:-0}"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/OnMoment/morning"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$ROOT/onmoment_morning.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$CLAUDE_DIR:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME/OnMoment/morning/launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/OnMoment/morning/launchd.log</string>
</dict></plist>
PL

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "설치 완료: 매일 $(printf %02d:%02d "$HOUR" "$MINUTE"), 그리고 로그인할 때마다 온순간 아침 창이 열립니다."
echo "(지금 한 번 열립니다)"
