#!/bin/bash
# Re-run all failed Claude queries (single + multiple indicator)
# Usage: ./rerun_claude_failures.sh

set -e
cd "$(dirname "$0")"

DELAY=45
RETRIES=3

echo "============================================"
echo "SINGLE INDICATOR RE-RUNS (20 queries)"
echo "============================================"

echo ""
echo ">>> CPI single (Q2,10,11,12)"
python testers/claude_tester.py --dataset CPI \
  --csv queries/claude/single_indicator/claude_queries_CPI.csv \
  --only "2,10,11,12" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> IIP single (Q3,4,5,6)"
python testers/claude_tester.py --dataset IIP \
  --csv queries/claude/single_indicator/claude_queries_IIP.csv \
  --only "3,4,5,6" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> ASI single (Q3)"
python testers/claude_tester.py --dataset ASI \
  --csv queries/claude/single_indicator/claude_queries_ASI.csv \
  --only "3" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> NAS single (Q1,2,7,10)"
python testers/claude_tester.py --dataset NAS \
  --csv queries/claude/single_indicator/claude_queries_NAS.csv \
  --only "1,2,7,10" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> WPI single (Q4,5)"
python testers/claude_tester.py --dataset WPI \
  --csv queries/claude/single_indicator/claude_queries_WPI.csv \
  --only "4,5" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> ENERGY single (Q7,8,9,14,15)"
python testers/claude_tester.py --dataset ENERGY \
  --csv queries/claude/single_indicator/claude_queries_ENERGY.csv \
  --only "7,8,9,14,15" --delay $DELAY --retries $RETRIES

echo ""
echo "============================================"
echo "MULTIPLE INDICATOR RE-RUNS (33 queries)"
echo "============================================"

echo ""
echo ">>> ASI multiple (Q1,3,4,8,9,15)"
python testers/claude_tester.py --dataset ASI \
  --csv queries/claude/multiple_indicator/claude_queries_ASI.csv \
  --only "1,3,4,8,9,15" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> CPI multiple (Q2,4,7,11,12,14)"
python testers/claude_tester.py --dataset CPI \
  --csv queries/claude/multiple_indicator/claude_queries_CPI.csv \
  --only "2,4,7,11,12,14" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> ENERGY multiple (Q2,4,8,13)"
python testers/claude_tester.py --dataset ENERGY \
  --csv queries/claude/multiple_indicator/claude_queries_ENERGY.csv \
  --only "2,4,8,13" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> IIP multiple (Q4,9,10,12)"
python testers/claude_tester.py --dataset IIP \
  --csv queries/claude/multiple_indicator/claude_queries_IIP.csv \
  --only "4,9,10,12" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> NAS multiple (Q1,2,9,10,14)"
python testers/claude_tester.py --dataset NAS \
  --csv queries/claude/multiple_indicator/claude_queries_NAS.csv \
  --only "1,2,9,10,14" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> PLFS multiple (Q9,13,15)"
python testers/claude_tester.py --dataset PLFS \
  --csv queries/claude/multiple_indicator/claude_queries_PLFS.csv \
  --only "9,13,15" --delay $DELAY --retries $RETRIES

echo ""
echo ">>> WPI multiple (Q1,8,10,13,14)"
python testers/claude_tester.py --dataset WPI \
  --csv queries/claude/multiple_indicator/claude_queries_WPI.csv \
  --only "1,8,10,13,14" --delay $DELAY --retries $RETRIES

echo ""
echo "============================================"
echo "ALL RE-RUNS COMPLETE!"
echo "============================================"
echo ""
echo "Next steps:"
echo "1. Check responses_claude/ for new JSON files"
echo "2. Run: python parse_results.py --dir responses_claude/"
echo "3. Run: python judge.py --dir responses_claude/"
