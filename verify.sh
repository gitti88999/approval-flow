#!/usr/bin/env bash
# D5 — single-command verification: brings the stack up, runs the four worked journeys plus
# the anti-cheese guards, prints a pass/fail report, and tears the stack back down.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Building and starting the stack..."
docker compose up -d --build

python3 scripts/verify.py
STATUS=$?

echo "Tearing down the stack..."
docker compose down

exit $STATUS
