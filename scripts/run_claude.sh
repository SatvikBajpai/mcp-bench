#!/bin/bash
set -e
cd "$(dirname "$0")/.."
LOG="/tmp/mospi_telemetry.log"
> "$LOG"
rm -f responses_claude/*.json responses_claude/*.csv

for ds in PLFS CPI IIP ASI NAS WPI ENERGY; do
    echo ">>> $ds at $(date)"
    python testers/claude_tester.py --dataset "$ds" --csv "queries/claude/claude_queries_${ds}.csv" --server-log "$LOG" --delay 60
done

echo "Done! Results in responses_claude/"
