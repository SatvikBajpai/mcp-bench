# MCP Bench

Benchmark suite for evaluating MCP (Model Context Protocol) tool-use accuracy across LLMs. Tests how well LLMs interact with the MoSPI government statistics API through a 4-step tool chain.

## Structure

```
mcp-bench/
├── testers/
│   ├── chatgpt_tester.py          # Playwright automation for ChatGPT
│   └── claude_tester.py           # Playwright automation for Claude.ai
├── queries/
│   ├── chatgpt/
│   │   └── multiple_indicator/    # Multi-indicator query CSVs
│   └── claude/
│       ├── single_indicator/      # Single-indicator query CSVs
│       └── multiple_indicator/    # Multi-indicator query CSVs
├── scripts/
│   ├── run_chatgpt.sh             # Run all datasets on ChatGPT
│   └── run_claude.sh              # Run all/custom datasets on Claude
├── responses/
│   └── benchmark_results/         # ChatGPT benchmark + judge CSVs
├── responses_claude/
│   └── benchmark_results/         # Claude benchmark + judge CSVs
├── parse_results.py               # Parse JSON responses into benchmark CSV
├── judge.py                       # LLM-as-Judge evaluation using Gemini
└── requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

### 1. Save Auth (one-time per platform)

```bash
python testers/chatgpt_tester.py --save-auth
python testers/claude_tester.py --save-auth
```

Opens a browser — log in, connect your MCP server, then close the window.

### 2. Run Tests

**All datasets:**
```bash
./scripts/run_chatgpt.sh
./scripts/run_claude.sh
```

**Custom datasets (Claude):**
```bash
./scripts/run_claude.sh single_indicator CPI IIP ENERGY
./scripts/run_claude.sh multiple_indicator PLFS NAS
```

**Single dataset with options:**
```bash
python testers/claude_tester.py \
    --dataset PLFS \
    --csv queries/claude/single_indicator/claude_queries_PLFS.csv \
    --server-log /tmp/mospi_telemetry.log \
    --delay 60 \
    --retries 3 \
    --only "2,5,10"    # Re-run specific query numbers only
```

### 3. Parse Results

```bash
# Parse all JSONs in a directory (deduplicates automatically)
python parse_results.py --dir responses_claude/benchmark_results

# Parse specific files
python parse_results.py --dir responses_claude/benchmark_results responses_claude/benchmark_results/claude_*_single_*.json
```

Output: `benchmark_results.csv` in the specified directory.

### 4. Judge Results

```bash
export GEMINI_API_KEY='your_key'

# Judge all queries
python judge.py \
    --csv responses_claude/benchmark_results/benchmark_results_single_indicator.csv \
    --dir responses_claude/benchmark_results

# Re-judge specific queries only (merges into existing judge CSV)
python judge.py \
    --csv responses_claude/benchmark_results/benchmark_results_multiple_indicators.csv \
    --dir responses_claude/benchmark_results \
    --only "ASI:1,CPI:2,NAS:10"
```

Output: `judge_results.csv` in the specified directory.

## Evaluation Rubric

The judge scores 6 dimensions (0 or 1 each, max 6/6):

| # | Dimension | Auto/LLM | What it checks |
|---|-----------|----------|----------------|
| 1 | **Routing** | Auto | Routed to the correct dataset? |
| 2 | **Ordering** | Auto | Tools called in 1→2→3→4 order? |
| 3 | **Filter Accuracy** | LLM | Correct filter codes passed to get_data? |
| 4 | **Data Retrieval** | LLM | Did get_data return actual data? |
| 5 | **Response Quality** | LLM | Numbers in response match API output? |
| 6 | **Behavior Compliance** | LLM | No web search, no fabrication? |

## Datasets

7 MoSPI datasets, 15 queries each: **PLFS**, **CPI**, **IIP**, **ASI**, **NAS**, **WPI**, **ENERGY**

Two test modes:
- **Single indicator** — one indicator per query
- **Multiple indicator** — compare/analyze multiple indicators per query

## Environment Variables

```bash
export GEMINI_API_KEY=your_key    # Required for judge.py (Gemini 2.5 Pro)
```
