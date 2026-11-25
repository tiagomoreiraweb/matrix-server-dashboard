#!/usr/bin/env bash
# Matrix Server Dashboard - installer
#
#   ./install.sh          asks a few questions (name, photo, web access) and installs
#   ./install.sh --yes    same, with the defaults and no questions
#
# Installs only inside this folder (Python venv in .venv). Disks, services,
# containers and network are detected automatically every time the dashboard
# starts, so there is nothing else to configure. Root is needed only for the
# optional steps at the end (auto-start on the monitor, power/network keys).
set -euo pipefail

cd "$(dirname "$0")"
HERE="$(pwd)"
USER="${USER:-$(id -un)}"
# Uploads through the GitHub web page drop the executable bit.
chmod +x ./*.sh system/matrix-netcfg 2>/dev/null || true
YES=0
case "${1:-}" in --yes|-y) YES=1 ;; esac

green() { printf '\033[32m%s\033[0m\n' "$*"; }
warn()  { printf '\033[33m%s\033[0m\n' "$*"; }
ask() {  # ask VAR "question" default
  local __var=$1 __q=$2 __def=${3:-} __ans=""
  if [ "$YES" -eq 0 ] && [ -t 0 ]; then
    read -r -p "$__q [${__def}]: " __ans || true
  fi
  printf -v "$__var" '%s' "${__ans:-$__def}"
}
yesno() {  # yesno "question" default(s/n) -> exit 0 = yes
  local ans
  ask ans "$1 (s/n)" "$2"
  [[ "$ans" =~ ^[sSyY] ]]
}

green "== Matrix Server Dashboard =="

# 1. Python ------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
  warn "Python 3 com venv não encontrado."
  if command -v apt-get >/dev/null 2>&1 && yesno "Instalar agora com sudo apt (python3 python3-venv)?" s; then
    sudo apt-get update -q && sudo apt-get install -y python3 python3-venv python3-pip
  else
    echo "Instale python3 e python3-venv e rode de novo."; exit 1
  fi
fi

green "[1/4] ambiente Python (.venv)"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# 2. Basic info --------------------------------------------------------------
green "[2/4] configuração básica"
if [ -f config.json ]; then
  echo "config.json já existe: mantido (apague-o para refazer as perguntas)."
else
  ask OPERATOR "Seu nome (aparece no boot do painel)" "${USER:-operator}"
  ask TITLE "Título do painel (vazio = nome do servidor)" ""
  ask PHOTO "Caminho de uma foto para o retrato ASCII (vazio = nome do servidor em letras grandes)" ""
  IMAGE="assets/portrait.png"
  mkdir -p assets
  if [ -n "$PHOTO" ]; then
    PHOTO="${PHOTO/#\~/$HOME}"
    if [ -f "$PHOTO" ]; then
      ext="${PHOTO##*.}"; ext="${ext,,}"
      IMAGE="assets/portrait.$ext"
      cp "$PHOTO" "$IMAGE"
      echo "foto copiada para $IMAGE"
    else
      warn "arquivo $PHOTO não encontrado: usando o nome do servidor"
    fi
  fi
  WEB=false; CONTROL=false; TERMINAL=false; PORT=8095
  if yesno "Ativar o painel no navegador (só rede local e Tailscale)?" s; then
    WEB=true
    ask PORT "Porta" "8095"
    if yesno "Permitir controlar o painel pela página (teclas, reiniciar etc.)?" n; then
      CONTROL=true
      warn "ATENÇÃO: o terminal web abre um shell SEM SENHA para quem acessar a página."
      yesno "Ativar o terminal web mesmo assim?" n && TERMINAL=true
    fi
  fi
  OPERATOR="$OPERATOR" TITLE="$TITLE" IMAGE="$IMAGE" WEB="$WEB" PORT="$PORT" CONTROL="$CONTROL" TERMINAL="$TERMINAL" \
  .venv/bin/python - <<'EOF'
import json, os
env = os.environ
cfg = json.load(open("config.example.json", encoding="utf-8"))
cfg["operator"] = env["OPERATOR"]
cfg["title"] = env["TITLE"]
cfg["image"] = env["IMAGE"]
cfg["web"].update({"enabled": env["WEB"] == "true", "port": int(env["PORT"] or 8095),
                   "control": env["CONTROL"] == "true", "terminal": env["TERMINAL"] == "true"})
with open("config.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
EOF
  echo "config.json criado."
fi

# 3. Detection ---------------------------------------------------------------
green "[3/4] o que foi encontrado neste servidor"
.venv/bin/python matrix_dashboard.py --config config.json --detect | sed 's/^/  /'
if ! docker ps >/dev/null 2>&1 && command -v docker >/dev/null 2>&1; then
  warn "  Docker existe mas seu usuário não tem acesso: sudo usermod -aG docker $USER (e entre de novo)"
fi

# 4. Optional root steps -----------------------------------------------------
green "[4/4] opcionais (pedem sudo)"
if [ "$YES" -eq 1 ] || [ ! -t 0 ]; then
  echo "  modo automático: rode depois, se quiser:"
  echo "    sudo ./install_service.sh $USER    # painel no monitor (tty1) ao ligar"
  echo "    sudo ./install_hotkeys_sudo.sh     # teclas D/R e rede no menu C"
elif yesno "Abrir o painel sozinho no monitor do servidor (tty1) ao ligar?" s; then
  sudo bash ./install_service.sh "$USER" "$HERE"
fi
if yesno "Liberar as teclas D (desligar), R (reiniciar) e a edição de rede no menu C?" n; then
  sudo bash ./install_hotkeys_sudo.sh "$USER"
fi

echo
green "Pronto."
echo "  testar agora (Ctrl+C sai):  ./run.sh"
echo "  um quadro só, via SSH:      ./run.sh --once"
echo "  ver a detecção de novo:     ./run.sh --detect"
grep -q '"enabled": true' config.json 2>/dev/null && \
  echo "  no navegador:               http://<ip-do-servidor>:$(.venv/bin/python -c 'import json;print(json.load(open("config.json"))["web"]["port"])')"
exit 0
