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
echo "Parsing results..."
python parse_results.py --dir responses_claude/

echo ""
echo "============================================"
echo "JUDGING ONLY RE-RUN QUERIES"
echo "============================================"

# Single indicator failures
SINGLE_ONLY="CPI:2,CPI:10,CPI:11,CPI:12,IIP:3,IIP:4,IIP:5,IIP:6,ASI:3,NAS:1,NAS:2,NAS:7,NAS:10,WPI:4,WPI:5,ENERGY:7,ENERGY:8,ENERGY:9,ENERGY:14,ENERGY:15"

# Multiple indicator failures
MULTI_ONLY="ASI:1,ASI:3,ASI:4,ASI:8,ASI:9,ASI:15,CPI:2,CPI:4,CPI:7,CPI:11,CPI:12,CPI:14,ENERGY:2,ENERGY:4,ENERGY:8,ENERGY:13,IIP:4,IIP:9,IIP:10,IIP:12,NAS:1,NAS:2,NAS:9,NAS:10,NAS:14,PLFS:9,PLFS:13,PLFS:15,WPI:1,WPI:8,WPI:10,WPI:13,WPI:14"

echo ""
echo "Judging single indicator re-runs..."
python judge.py --dir responses_claude/ --only "$SINGLE_ONLY"

echo ""
echo "Judging multiple indicator re-runs..."
python judge.py --dir responses_claude/ --only "$MULTI_ONLY"

echo ""
echo "============================================"
echo "DONE!"
echo "============================================"
