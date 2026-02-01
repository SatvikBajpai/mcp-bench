#!/bin/bash
set -e
cd "$(dirname "$0")/.."
LOG="/tmp/mospi_telemetry.log"

# Default to single_indicator, can override with argument
MODE="${1:-single_indicator}"

if [[ "$MODE" != "single_indicator" && "$MODE" != "multiple_indicator" ]]; then
    echo "Usage: $0 [single_indicator|multiple_indicator]"
    exit 1
fi

echo "Running Claude tests: $MODE"
# NOTE: Don't truncate LOG here - server is writing to it. Truncate before starting server.
rm -f responses_claude/*.json responses_claude/*.csv

for ds in PLFS CPI IIP ASI NAS WPI ENERGY; do
    echo ">>> $ds at $(date)"
    python testers/claude_tester.py --dataset "$ds" --csv "queries/claude/${MODE}/claude_queries_${ds}.csv" --server-log "$LOG" --delay 60
done

echo "Done! Results in responses_claude/"
