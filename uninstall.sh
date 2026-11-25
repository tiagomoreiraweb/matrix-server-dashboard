#!/usr/bin/env bash
# Removes what the installer put outside this folder (service, sudo rule, network helper).
#   sudo ./uninstall.sh
# Then delete the folder to remove everything.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com: sudo $0"; exit 1
fi

if [ -f /etc/systemd/system/matrix-dashboard.service ]; then
  systemctl disable --now matrix-dashboard.service || true
  rm -f /etc/systemd/system/matrix-dashboard.service
  systemctl daemon-reload
  echo "serviço removido"
fi
rm -f /etc/sudoers.d/matrix-dashboard /etc/sudoers.d/matrix-dashboard-wireguard /usr/local/sbin/matrix-netcfg
echo "regra do sudo e helper de rede removidos"
echo "Se o console tty1 ficou sem login: sudo systemctl enable --now getty@tty1"
