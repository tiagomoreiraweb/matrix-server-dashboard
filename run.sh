#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Ambiente ainda nao instalado. Rode primeiro:"
  echo "  ./install.sh"
  exit 1
fi

exec .venv/bin/python matrix_dashboard.py --config config.json "$@"
