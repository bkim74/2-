#!/bin/bash
# 온순간 아침 창 — Linux 설치 (systemd user timer + 데스크톱 자동 시작)
# 사용법: bash install/install_linux.sh        제거: bash install/install_linux.sh --uninstall
set -euo pipefail
UNIT="onmoment-morning"
SD="$HOME/.config/systemd/user"
AUTO="$HOME/.config/autostart/$UNIT.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now "$UNIT.timer" 2>/dev/null || true
  rm -f "$SD/$UNIT.service" "$SD/$UNIT.timer" "$AUTO"
  systemctl --user daemon-reload || true
  echo "제거했습니다."; exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
CLAUDE_DIR="$(dirname "$(command -v claude 2>/dev/null || echo /usr/local/bin/claude)")"
[[ -f "$ROOT/config.json" ]] || cp "$ROOT/config.example.json" "$ROOT/config.json"
mkdir -p "$SD" "$(dirname "$AUTO")"

cat > "$SD/$UNIT.service" <<U
[Unit]
Description=OnMoment morning window
[Service]
Type=oneshot
WorkingDirectory=$ROOT
Environment=PATH=$CLAUDE_DIR:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
PassEnvironment=DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS
ExecStart=$PY $ROOT/onmoment_morning.py
U
cat > "$SD/$UNIT.timer" <<U
[Unit]
Description=OnMoment morning window at 06:00
[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true
[Install]
WantedBy=timers.target
U
cat > "$AUTO" <<U
[Desktop Entry]
Type=Application
Name=온순간 아침 창
Exec=sh -c "sleep 45; $PY $ROOT/onmoment_morning.py"
X-GNOME-Autostart-enabled=true
U
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT.timer"
echo "설치 완료: 매일 06:00 (꺼져 있었다면 켜진 뒤), 그리고 로그인할 때마다 열립니다."
