#!/usr/bin/env bash
# ME4-YouTube — Linux/macOS-Start
set -e
cd "$(dirname "$0")"

# .env laden
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# venv
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

python main.py "$@"
