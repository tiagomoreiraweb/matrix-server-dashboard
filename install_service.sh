#!/usr/bin/env bash
# Runs the dashboard on the server's own monitor (tty1) at boot, as a systemd service.
#   sudo ./install_service.sh [user] [folder]
# Undo with: sudo ./uninstall.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com: sudo $0"; exit 1
fi

RUN_USER="${1:-${SUDO_USER:-}}"
DIR="${2:-$(cd "$(dirname "$0")" && pwd)}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = root ] || ! id "$RUN_USER" >/dev/null 2>&1; then
  echo "Informe o usuário (não root): sudo $0 <usuario>"; exit 1
fi
[ -f "$DIR/run.sh" ] || { echo "run.sh não encontrado em $DIR"; exit 1; }
chmod +x "$DIR/run.sh"

UNIT=/etc/systemd/system/matrix-dashboard.service
cat > "$UNIT" <<EOF
[Unit]
Description=Matrix Server Dashboard (tty1)
After=network-online.target docker.service
Wants=network-online.target
# The dashboard takes over the first console instead of the login prompt.
Conflicts=getty@tty1.service
After=getty@tty1.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$DIR
ExecStart=$DIR/run.sh
StandardInput=tty-force
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
Environment=TERM=linux
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# The user needs the tty group to draw on the console and docker to read containers.
usermod -aG tty "$RUN_USER" || true
getent group docker >/dev/null && usermod -aG docker "$RUN_USER" || true

systemctl daemon-reload
systemctl enable --now matrix-dashboard.service
echo "OK: painel ativo no tty1 (Alt+F2 dá outro console com login)."
echo "Ver o estado: systemctl status matrix-dashboard"
