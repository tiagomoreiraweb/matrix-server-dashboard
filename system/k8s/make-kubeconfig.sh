#!/usr/bin/env bash
# Writes a kubeconfig for the dashboard's ServiceAccount (see matrix-dashboard-rbac.yaml).
#   sudo ./system/k8s/make-kubeconfig.sh [user] [server]
# Default user: the one who ran sudo. Default server: https://127.0.0.1:6443 (k3s on this host).
set -euo pipefail
RUN_USER="${1:-${SUDO_USER:-$USER}}"
SERVER="${2:-https://127.0.0.1:6443}"
KUBECTL="kubectl"
command -v kubectl >/dev/null 2>&1 || KUBECTL="k3s kubectl"
[ -r /etc/rancher/k3s/k3s.yaml ] && export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

DIR="$(cd "$(dirname "$0")" && pwd)"
$KUBECTL apply -f "$DIR/matrix-dashboard-rbac.yaml" >/dev/null
for _ in $(seq 1 20); do
  TOKEN="$($KUBECTL -n kube-system get secret matrix-dashboard-token -o jsonpath='{.data.token}' 2>/dev/null | base64 -d)"
  [ -n "$TOKEN" ] && break
  sleep 0.5
done
[ -n "${TOKEN:-}" ] || { echo "token da ServiceAccount não apareceu"; exit 1; }
CA="$($KUBECTL -n kube-system get secret matrix-dashboard-token -o jsonpath='{.data.ca\.crt}')"

HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"
OUT="$HOME_DIR/.kube/matrix-dashboard.yaml"
install -d -m 700 -o "$RUN_USER" "$HOME_DIR/.kube"
umask 077
cat > "$OUT" <<YAML
apiVersion: v1
kind: Config
clusters:
- name: local
  cluster:
    server: $SERVER
    certificate-authority-data: $CA
users:
- name: matrix-dashboard
  user:
    token: $TOKEN
contexts:
- name: matrix-dashboard
  context:
    cluster: local
    user: matrix-dashboard
current-context: matrix-dashboard
YAML
chown "$RUN_USER" "$OUT"
echo "OK: $OUT"
