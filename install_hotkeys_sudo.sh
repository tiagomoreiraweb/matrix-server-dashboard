#!/usr/bin/env bash
# Grants the dashboard user the few root actions it needs from the keyboard, and nothing else:
#   - power off (D) and reboot (R)
#   - apply network settings from the settings menu (C), through the
#     root-owned helper /usr/local/sbin/matrix-netcfg, which validates its input
#     (Ubuntu / netplan only)
# Run once with: sudo ./install_hotkeys_sudo.sh [user]
# Undo with:     sudo rm /etc/sudoers.d/matrix-dashboard /usr/local/sbin/matrix-netcfg
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com: sudo $0"
  exit 1
fi

RUN_USER="${1:-${SUDO_USER:-}}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = root ] || ! id "$RUN_USER" >/dev/null 2>&1; then
  echo "Informe o usuário do painel: sudo $0 <usuario>"; exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
HELPER=/usr/local/sbin/matrix-netcfg
TARGET=/etc/sudoers.d/matrix-dashboard
SYSTEMCTL="$(command -v systemctl)"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

RULE="$SYSTEMCTL poweroff, $SYSTEMCTL reboot"
if [ -d /etc/netplan ] && command -v netplan >/dev/null 2>&1; then
  if ! /usr/bin/python3 -c 'import yaml' 2>/dev/null; then
    command -v apt-get >/dev/null && apt-get install -y python3-yaml
  fi
  install -m 0755 -o root -g root "$HERE/system/matrix-netcfg" "$HELPER"
  echo "OK: $HELPER instalado"
  RULE="$RULE, $HELPER"
else
  echo "netplan não encontrado: só D e R serão liberados (rede fica somente leitura)."
fi

cat > "$TMP" <<EOF
# Matrix dashboard: power off (D), reboot (R) and network settings (C) from the keyboard.
$RUN_USER ALL=(root) NOPASSWD: $RULE
EOF

visudo -cf "$TMP"
install -m 0440 -o root -g root "$TMP" "$TARGET"
echo "OK: $TARGET instalado para $RUN_USER. Teste com: sudo -n -l"
