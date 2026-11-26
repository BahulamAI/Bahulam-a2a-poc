#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Virtual environment not found. Run ./scripts/setup.sh first." >&2
  exit 1
fi
mkdir -p state
nohup .venv/bin/python -m bahulam_poc.agents.setup_server > state/setup-agent.log 2>&1 &
echo $! > state/setup-agent.pid
sleep 2
nohup .venv/bin/python -m bahulam_poc.agents.builder_server > state/builder-agent.log 2>&1 &
echo $! > state/builder-agent.pid
echo "Started Setup Agent (9101) and Builder Agent (9102)."
echo "Check: .venv/bin/python -m bahulam_poc.health_check"
