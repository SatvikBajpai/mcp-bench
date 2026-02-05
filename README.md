# MCP Bench

A benchmark for evaluating how well LLMs use MCP (Model Context Protocol) tools. Tests ChatGPT and Claude.ai against the MoSPI government statistics API.

## Results

| Platform | Mode | Queries | Overall | Routing | Ordering | Filter | Data | Response | Behavior |
|----------|------|---------|---------|---------|----------|--------|------|----------|----------|
| Claude | Single | 107 | **89%** | 89% | 93% | 91% | 94% | 75% | 93% |
| Claude | Multi | 105 | **85%** | 82% | 90% | 95% | 89% | 66% | 90% |
| ChatGPT | Single | 98 | **91%** | 89% | 95% | 85% | 92% | 94% | 91% |
| ChatGPT | Multi | 105 | **82%** | 87% | 84% | 78% | 83% | 82% | 78% |

## What It Tests

The MoSPI API requires a strict 4-step tool chain:

```
1_know_about_mospi_api → 2_get_indicators → 3_get_metadata → 4_get_data
```

Each query tests whether the LLM can:
1. Route to the correct dataset
2. Follow the tool order
3. Pass correct filter codes
4. Retrieve actual data
5. Report accurate numbers
6. Avoid fabrication

## Scoring Rubric

| Dimension | Method | Criteria |
|-----------|--------|----------|
| **Routing** | Auto | Correct dataset selected |
| **Ordering** | Auto | Tools called in 1→2→3→4 order |
| **Filter Accuracy** | LLM Judge | Correct codes from metadata passed to get_data |
| **Data Retrieval** | LLM Judge | get_data returned actual data |
| **Response Quality** | LLM Judge | Numbers match API output |
| **Behavior** | LLM Judge | No web search or fabrication |

## Project Structure

```
mcp-bench/
├── queries/
│   ├── chatgpt/
│   │   ├── single_indicator/     # 107 single-indicator queries
│   │   └── multiple_indicator/   # 105 multi-indicator queries
│   └── claude/
│       ├── single_indicator/
│       └── multiple_indicator/
├── responses/                    # ChatGPT results
│   └── benchmark_results/
│       ├── benchmark_results_*.csv
│       └── judge_results_*.csv
├── responses_claude/             # Claude results
│   └── benchmark_results/
├── testers/
│   ├── chatgpt_tester.py        # Playwright automation
│   └── claude_tester.py
├── scripts/
│   ├── run_chatgpt.sh
│   └── run_claude.sh
├── parse_results.py              # JSON → CSV
└── judge.py                      # LLM-as-Judge scoring
```

## Quick Start

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Authenticate (one-time)
python testers/chatgpt_tester.py --save-auth
python testers/claude_tester.py --save-auth

# Run benchmarks
./scripts/run_chatgpt.sh
./scripts/run_claude.sh

# Parse and judge
export GEMINI_API_KEY='your_key'
python parse_results.py --dir responses/benchmark_results
python judge.py --csv responses/benchmark_results/benchmark_results.csv --dir responses/benchmark_results
```

## Datasets

7 MoSPI datasets, 15 queries each:

| Dataset | Description |
|---------|-------------|
| PLFS | Labour force, employment, wages |
| CPI | Consumer price indices |
| IIP | Industrial production indices |
| ASI | Annual survey of industries |
| NAS | National accounts (GDP, GVA) |
| WPI | Wholesale price indices |
| ENERGY | Energy statistics |

## License

MIT
