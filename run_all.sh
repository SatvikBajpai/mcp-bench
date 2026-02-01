#!/bin/bash
set -e
cd "$(dirname "$0")"
LOG="/tmp/mospi_telemetry.log"
> "$LOG"
rm -f responses/*.json responses/*.csv

for ds in PLFS CPI IIP ASI NAS WPI ENERGY; do
    echo ">>> $ds at $(date)"
    python tester.py --dataset "$ds" --csv "queries/test_queries_${ds}.csv" --server-log "$LOG" --delay 60
done

python parse_results.py
python judge.py
