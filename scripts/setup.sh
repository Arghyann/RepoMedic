#!/usr/bin/env bash
# One-shot setup on macOS/Linux:  bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e .
if command -v ollama >/dev/null; then
  ollama pull "${REPOMEDIC_MODEL:-gemma4:e4b}"
else
  echo "Ollama not found: curl -fsSL https://ollama.com/install.sh | sh"
fi
.venv/bin/python -m pytest -q -p no:cacheprovider tests
echo -e "\nReady. Try:\n  .venv/bin/repomedic scan bench/buggy_shop\n  .venv/bin/repomedic serve"
