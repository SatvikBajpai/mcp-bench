# MCP Bench

Benchmark suite for testing MCP (Model Context Protocol) tool-use across LLMs.

## Structure

```
mcp-bench/
├── testers/
│   ├── chatgpt_tester.py    # Playwright automation for ChatGPT
│   └── claude_tester.py     # Playwright automation for Claude.ai
├── queries/
│   ├── chatgpt/             # Query CSVs for ChatGPT
│   └── claude/              # Query CSVs for Claude (with artifact suppression)
├── scripts/
│   ├── run_chatgpt.sh       # Run all datasets on ChatGPT
│   └── run_claude.sh        # Run all datasets on Claude
├── parse_results.py         # Parse JSON responses into CSV
├── judge.py                 # LLM-as-judge evaluation using Gemini
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
# ChatGPT
python testers/chatgpt_tester.py --save-auth

# Claude
python testers/claude_tester.py --save-auth
```

This opens a browser. Log in, connect your MCP server, then close the browser.

### 2. Run Tests

**Single dataset:**
```bash
python testers/chatgpt_tester.py --dataset PLFS --csv queries/chatgpt/test_queries_PLFS.csv --server-log /tmp/mospi_telemetry.log --delay 60
```

**All datasets:**
```bash
# Start your MCP server first, logging to /tmp/mospi_telemetry.log
./scripts/run_chatgpt.sh
./scripts/run_claude.sh
```

### 3. Parse & Judge

```bash
python parse_results.py      # Creates benchmark_results.csv
python judge.py              # Creates judge_results.csv with scores
```

## Evaluation Rubric

The judge scores 6 dimensions (0 or 1 each):

1. **Routing** - Did LLM route to the correct dataset?
2. **Ordering** - Were tools called in 1→2→3→4 order?
3. **Filter Accuracy** - Were correct filter codes passed to get_data?
4. **Data Retrieval** - Did get_data return actual data?
5. **Response Quality** - Do numbers in response match API output?
6. **Behavior Compliance** - No web search, no fabrication?

## Environment Variables

```bash
export GEMINI_API_KEY=your_key_here  # For judge.py
```
