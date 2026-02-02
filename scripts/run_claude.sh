#!/bin/bash
set -e
cd "$(dirname "$0")/.."

LOG="/tmp/mospi_telemetry.log"
ALL_DATASETS="PLFS CPI IIP ASI NAS WPI ENERGY"

# Parse arguments
MODE="${1:-single_indicator}"
shift 2>/dev/null || true

if [[ "$MODE" != "single_indicator" && "$MODE" != "multiple_indicator" ]]; then
    echo "Usage: $0 <single_indicator|multiple_indicator> [DATASET1 DATASET2 ...]"
    echo ""
    echo "Examples:"
    echo "  $0 single_indicator              # Run all datasets"
    echo "  $0 multiple_indicator CPI IIP    # Run only CPI and IIP"
    echo "  $0 single_indicator PLFS         # Run only PLFS"
    echo ""
    echo "Available datasets: $ALL_DATASETS"
    exit 1
fi

# Use provided datasets or default to all
DATASETS="${*:-$ALL_DATASETS}"

echo "Running Claude tests: $MODE"
echo "Datasets: $DATASETS"
echo ""

for ds in $DATASETS; do
    CSV="queries/claude/${MODE}/claude_queries_${ds}.csv"
    if [[ ! -f "$CSV" ]]; then
        echo "WARNING: $CSV not found, skipping $ds"
        continue
    fi
    echo ">>> $ds at $(date)"
    python testers/claude_tester.py --dataset "$ds" --csv "$CSV" --server-log "$LOG" --delay 60
done

echo ""
echo "Done! Results in responses_claude/"
