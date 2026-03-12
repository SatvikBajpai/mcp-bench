#!/bin/bash
# ============================================================
#  MoSPI MCP Benchmark - Full Regression Run (Linux/Mac)
# ============================================================
#  Usage:
#    ./scripts/run_regression.sh              (run all 200 queries)
#    ./scripts/run_regression.sh --start 47   (resume from query 47)
# ============================================================

set -e
cd "$(dirname "$0")/.."

LOG="/tmp/mospi_telemetry.log"
CSV="queries/regression_test_queries.csv"
DELAY=30
START="${2:-}"

# Use xvfb-run on headless Linux
if command -v xvfb-run &>/dev/null && [ -z "${DISPLAY:-}" ]; then
    RUNNER="xvfb-run --auto-servernum --server-args='-screen 0 1440x900x24'"
else
    RUNNER=""
fi

echo "============================================================"
echo " MoSPI Regression Benchmark"
echo " Queries: $CSV"
echo " Log:     $LOG"
echo " Delay:   ${DELAY}s between queries"
echo "============================================================"
echo

# Step 1: Run benchmark
echo "[1/3] Running benchmark queries..."
if [ -z "$START" ]; then
    $RUNNER python testers/chatgpt_tester.py --dataset REGRESSION --csv "$CSV" --server-log "$LOG" --delay $DELAY
else
    $RUNNER python testers/chatgpt_tester.py --dataset REGRESSION --csv "$CSV" --server-log "$LOG" --delay $DELAY --start "$START"
fi

# Step 2: Parse results
echo
echo "[2/3] Parsing results..."
python parse_results.py

# Step 3: Judge
echo
echo "[3/3] Running judge..."
python judge.py

echo
echo "============================================================"
echo " DONE! Results saved in responses/$(date +%Y-%m-%d)/"
echo " - benchmark_results.csv"
echo " - judge_results.csv"
echo "============================================================"
