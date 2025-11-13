#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT/backend"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r ../requirements.txt
else
  source .venv/bin/activate
fi

exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

