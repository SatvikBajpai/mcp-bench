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

echo "Running ChatGPT tests: $MODE"
# NOTE: Don't truncate LOG here - server is writing to it. Truncate before starting server.
rm -f responses/*.json responses/*.csv

for ds in PLFS CPI IIP ASI NAS WPI ENERGY; do
    echo ">>> $ds at $(date)"
    python testers/chatgpt_tester.py --dataset "$ds" --csv "queries/chatgpt/${MODE}/test_queries_${ds}.csv" --server-log "$LOG" --delay 60
done

python parse_results.py
python judge.py
