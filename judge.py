#!/usr/bin/env python3
"""
LLM-as-Judge evaluation for MoSPI MCP benchmark results.

Reads benchmark_results.csv, auto-scores routing and ordering,
uses Gemini API with structured output to judge filter accuracy,
data retrieval, response quality, and behavior compliance.

Usage:
    python judge.py
    python judge.py --csv responses/benchmark_results.csv
    python judge.py --model gemini-3-pro-preview
"""

import argparse
import csv
csv.field_size_limit(10 * 1024 * 1024)  # 10MB
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Install google-genai: pip install google-genai")
    sys.exit(1)

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("Install pydantic: pip install pydantic")
    sys.exit(1)

RESPONSES_DIR = Path(__file__).parent / "responses"


# --- Structured output schema for the judge ---

class JudgeResult(BaseModel):
    filter_accuracy: int = Field(
        description="0 or 1. Did the LLM pass correct filter CODES from metadata? -1 if metadata was not reached (timeout)."
    )
    filter_notes: str = Field(description="Brief explanation of filter accuracy score.")
    data_retrieval: int = Field(
        description="0 or 1. Did get_data return actual data? For edge cases, 'No Data Found' is correct = 1. Timeout = 0."
    )
    data_notes: str = Field(description="Brief explanation of data retrieval score.")
    response_quality: int = Field(
        description="0 or 1. Does the response contain accurate numbers matching API output? Honest about failures?"
    )
    response_notes: str = Field(description="Brief explanation of response quality score.")
    behavior_compliance: int = Field(
        description="0 or 1. No web search, no fabrication, no external sources, no skipping tools?"
    )
    behavior_notes: str = Field(description="Brief explanation of behavior compliance score.")


# --- Judge prompt ---

JUDGE_PROMPT = """You are a strict evaluator for an MCP (Model Context Protocol) tool-use benchmark.

An LLM (ChatGPT) was connected to a MoSPI government statistics API via 4 MCP tools.
The tools MUST be called in this order: 1_know_about_mospi_api → 2_get_indicators → 3_get_metadata → 4_get_data.
The LLM may retry any tool (same step called multiple times is normal). Skipping a step is a failure.

Below is all evidence for one test query. Read it carefully, then score using the rubric at the end.

===== EVIDENCE =====

USER QUERY:
{query}

GROUND TRUTH (what we expected):
- Dataset: {dataset}
- Indicator: {indicator_tested}
- Critical filters: {filters_tested}

TOOL TRACE (chronological, may include retries):
{tool_trace}

STEP 3 METADATA OUTPUT (last successful call — shows available filter codes):
{metadata_output}

ALL TOOL CALLS WITH ARGS AND OUTPUTS:
{all_calls_info}

LLM'S FINAL RESPONSE TO THE USER:
{response_full}

===== SCORING RUBRIC =====

Score each dimension. Use the specific criteria below — do not infer or assume beyond what the evidence shows.

DIMENSION 3: FILTER ACCURACY
What to check: Look at the filters passed in 4_get_data calls. Compare them against the metadata output from step 3.
Score 1 if ALL of these are true:
  - Filter values are numeric CODES from metadata (e.g., state_code="4" not "Bihar", gender_code="1" not "male")
  - The critical filters listed in "{filters_tested}" are present in at least one get_data call
  - Filter values correctly map to what the user asked for (e.g., if user asked "Bihar", the state_code matches Bihar in metadata)
Score 0 if:
  - String names were passed instead of codes (e.g., use_of_energy_balance_code="Supply" instead of "1")
  - Critical filters are missing from all get_data calls
  - Filter codes don't match what the user asked for
Score -1 if:
  - Step 3 (get_metadata) was never successfully reached (all attempts timed out)

DIMENSION 4: DATA RETRIEVAL
What to check: Look at the 4_get_data outputs.
Score 1 if ANY of these are true:
  - At least one get_data call returned actual data rows (non-empty "data" array)
  - The query was an intentional edge case (wrong year, impossible filter combo, ambiguous/wrong dataset) AND get_data correctly returned "No Data Found" AND the LLM acknowledged this honestly
Score 0 if:
  - All get_data calls timed out or returned errors
  - get_data was never called (tool chain broke before step 4)
  - Data was empty but the LLM fabricated numbers anyway

DIMENSION 5: RESPONSE QUALITY
What to check: Compare the LLM's final response text against the actual get_data output.
Score 1 if ALL of these are true:
  - Numbers in the response match the API output exactly (or with reasonable rounding like 403799.46 → 403,799.46)
  - The response correctly identifies what the data represents (right indicator, right state, right year)
  - For "no data" cases: the response clearly states data was not found without inventing numbers
  - For timeout cases: the response acknowledges the API failure honestly
Score 0 if ANY of these are true:
  - Numbers in the response don't match the API output
  - The response claims a value that doesn't appear in any get_data output
  - The response misattributes the data (wrong state, wrong year, wrong indicator)
  - For "no data" cases: the response provides specific numbers despite no data being returned

DIMENSION 6: BEHAVIOR COMPLIANCE
What to check: Read the LLM's final response for signs of rule violations.
Score 1 if ALL of these are true:
  - No evidence of web search (no URLs, no "according to [source]", no "based on reports")
  - No fabricated statistics (every number traces back to a get_data output)
  - No use of training knowledge to fill gaps (doesn't say "typically around X%" or "historically about Y")
  - Honest about limitations (says "not found" or "API timed out" when that's what happened)
Score 0 if ANY of these are true:
  - Response contains data that doesn't come from any tool output
  - Response cites external sources or implies web search was used
  - Response provides specific numbers when all tool calls failed/timed out
  - Response uses hedging language to present training knowledge as if it were API data ("usually around", "based on trends")"""


def auto_score_routing(row: dict) -> int:
    """Score 1 if LLM routed to the expected dataset."""
    expected = row.get("dataset", "").strip().upper()
    actual = row.get("dataset_routed_to", "").strip().upper()
    if not actual:
        return 0
    return 1 if actual == expected else 0


def auto_score_ordering(row: dict) -> int:
    """Score 1 if tools were called in 1→2→3→4 order (retries OK, skips = fail)."""
    trace = row.get("tool_trace", "")
    if not trace:
        return 0

    # Extract tool numbers from trace
    tool_nums = re.findall(r'(\d)_', trace)
    if not tool_nums:
        return 0

    # Remove consecutive duplicates (retries)
    deduped = [tool_nums[0]]
    for t in tool_nums[1:]:
        if t != deduped[-1]:
            deduped.append(t)

    # Check if 1,2,3,4 appears as a subsequence
    expected = ['1', '2', '3', '4']
    idx = 0
    for t in deduped:
        if idx < len(expected) and t == expected[idx]:
            idx += 1

    return 1 if idx == 4 else 0


def build_all_calls_summary(row: dict) -> str:
    """Build a readable summary of ALL tool calls from the all_tool_calls JSON."""
    raw = row.get("all_tool_calls", "")
    if not raw:
        return "No tool calls recorded"

    try:
        all_calls = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw[:2000]

    parts = []
    for tool_name, calls in all_calls.items():
        parts.append(f"\n--- {tool_name} ({len(calls)} call(s)) ---")
        for i, call in enumerate(calls):
            args = call.get("args", {})
            output = call.get("output", "")
            has_data = call.get("has_data", False)
            is_error = call.get("is_error", False)
            status = "DATA" if has_data else ("ERROR/TIMEOUT" if is_error else "EMPTY/NO_DATA")
            parts.append(f"  Call {i+1}: args={json.dumps(args, default=str)} → [{status}] {output}")

    return "\n".join(parts)


def call_judge(client, model: str, row: dict) -> dict:
    """Send a row to Gemini for judging dimensions 3-6 using structured output."""
    all_calls_summary = build_all_calls_summary(row)

    prompt = JUDGE_PROMPT.format(
        query=row.get("query", ""),
        dataset=row.get("dataset", ""),
        indicator_tested=row.get("indicator_tested", ""),
        filters_tested=row.get("filters_tested", ""),
        tool_trace=row.get("tool_trace", ""),
        metadata_output=row.get("3_metadata_output", ""),
        all_calls_info=all_calls_summary,
        response_full=row.get("response_full", ""),
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=JudgeResult.model_json_schema(),
                thinking_config=types.ThinkingConfig(
                    thinking_level="high",
                    include_thoughts=True,
                ),
            ),
        )

        # Extract thought summary from parts
        thought_summary = ""
        answer_text = ""
        for part in response.candidates[0].content.parts:
            if not part.text:
                continue
            if part.thought:
                thought_summary += part.text
            else:
                answer_text += part.text

        result = JudgeResult.model_validate_json(answer_text or response.text)
        output = result.model_dump()
        output["judge_reasoning"] = thought_summary
        return output
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="LLM Judge for MoSPI MCP Benchmark")
    parser.add_argument("--csv", type=str, default=None,
                        help="Path to benchmark_results.csv")
    parser.add_argument("--model", type=str, default="gemini-3-pro-preview",
                        help="Gemini model for judging (default: gemini-3-pro-preview)")
    parser.add_argument("--start", type=int, default=1,
                        help="Start from this row number (for resuming)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Delay between API calls in seconds")
    args = parser.parse_args()

    # Find CSV
    csv_path = Path(args.csv) if args.csv else RESPONSES_DIR / "benchmark_results.csv"
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        print("Run parse_results.py first to generate benchmark_results.csv")
        sys.exit(1)

    # Check API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Read CSV
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    print(f"Loaded {len(rows)} queries from {csv_path}")
    print(f"Judge model: {args.model}")
    print(f"Starting from row {args.start}")
    print()

    # Output path
    out_path = RESPONSES_DIR / "judge_results.csv"

    # Output fieldnames
    out_fields = list(rows[0].keys()) + [
        "score_routing", "score_ordering",
        "score_filter_accuracy", "filter_notes",
        "score_data_retrieval", "data_notes",
        "score_response_quality", "response_notes",
        "score_behavior", "behavior_notes",
        "total_score", "judge_reasoning",
    ]

    # Load existing results if resuming
    existing = []
    if args.start > 1 and out_path.exists():
        with open(out_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.append(row)
        print(f"Loaded {len(existing)} existing results for resume")

    results = existing[:]

    for i, row in enumerate(rows):
        row_num = i + 1
        if row_num < args.start:
            continue

        ds = row.get("dataset", "")
        qno = row.get("no", "")
        query = row.get("query", "")[:60]
        print(f"[{row_num}/{len(rows)}] {ds} Q{qno}: {query}...")

        # Auto-score dimensions 1 & 2
        score_routing = auto_score_routing(row)
        score_ordering = auto_score_ordering(row)

        # LLM judge dimensions 3-6
        judge_result = call_judge(client, args.model, row)

        if "error" in judge_result:
            print(f"    [JUDGE ERROR] {judge_result['error']}")
            score_filter = "ERR"
            score_data = "ERR"
            score_response = "ERR"
            score_behavior = "ERR"
            filter_notes = judge_result.get("error", "")
            data_notes = ""
            response_notes = ""
            behavior_notes = ""
        else:
            score_filter = judge_result.get("filter_accuracy", "ERR")
            score_data = judge_result.get("data_retrieval", "ERR")
            score_response = judge_result.get("response_quality", "ERR")
            score_behavior = judge_result.get("behavior_compliance", "ERR")
            filter_notes = judge_result.get("filter_notes", "")
            data_notes = judge_result.get("data_notes", "")
            response_notes = judge_result.get("response_notes", "")
            behavior_notes = judge_result.get("behavior_notes", "")

        # Calculate total (treat N/A=-1 and ERR as 0 for total)
        scores = [score_routing, score_ordering, score_filter, score_data, score_response, score_behavior]
        total = sum(s for s in scores if isinstance(s, int) and s > 0)

        # Display -1 as N/A
        display_filter = "N/A" if score_filter == -1 else score_filter
        reasoning = judge_result.get("judge_reasoning", "") if "error" not in judge_result else ""

        print(f"    Routing={score_routing} Order={score_ordering} Filter={display_filter} "
              f"Data={score_data} Response={score_response} Behavior={score_behavior} "
              f"Total={total}/6")
        if filter_notes:
            print(f"    [Filter]   {filter_notes}")
        if data_notes:
            print(f"    [Data]     {data_notes}")
        if response_notes:
            print(f"    [Response] {response_notes}")
        if behavior_notes:
            print(f"    [Behavior] {behavior_notes}")
        if reasoning:
            # Show first 200 chars of reasoning
            short_reasoning = reasoning[:200].replace("\n", " ")
            if len(reasoning) > 200:
                short_reasoning += "..."
            print(f"    [Reasoning] {short_reasoning}")
        print()

        # Build output row
        out_row = dict(row)
        out_row.update({
            "score_routing": score_routing,
            "score_ordering": score_ordering,
            "score_filter_accuracy": "N/A" if score_filter == -1 else score_filter,
            "filter_notes": filter_notes,
            "score_data_retrieval": score_data,
            "data_notes": data_notes,
            "score_response_quality": score_response,
            "response_notes": response_notes,
            "score_behavior": score_behavior,
            "behavior_notes": behavior_notes,
            "total_score": total,
            "judge_reasoning": reasoning.replace("\n", " "),
        })
        results.append(out_row)

        # Save incrementally
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=out_fields)
            writer.writeheader()
            writer.writerows(results)

        # Rate limit delay
        time.sleep(args.delay)

    # Final summary
    print(f"\nResults written to: {out_path}")
    print(f"Total queries judged: {len(results)}")

    print("\n" + "=" * 85)
    print("BENCHMARK SUMMARY")
    print("=" * 85)

    platforms = sorted(set(r.get("platform", "unknown") for r in results))
    modes = sorted(set(r.get("mode", "single") for r in results))
    datasets = sorted(set(r.get("dataset", "") for r in results))

    def safe_avg(values):
        nums = [v for v in values if isinstance(v, (int, float))]
        return sum(nums) / len(nums) if nums else 0

    def to_num(val):
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    header = f"{'Platform':<10} {'Mode':<6} {'Dataset':<8} {'Routing':>7} {'Order':>7} {'Filter':>7} {'Data':>7} {'Resp':>7} {'Behav':>7} {'Avg':>6}"
    print(header)
    print("-" * len(header))

    all_scores = {k: [] for k in ["routing", "ordering", "filter", "data", "response", "behavior"]}

    for plat in platforms:
        for m in modes:
            for ds in datasets:
                rows = [r for r in results if r.get("platform") == plat and r.get("mode") == m and r.get("dataset") == ds]
                if not rows:
                    continue

                routing = [to_num(r["score_routing"]) for r in rows]
                ordering = [to_num(r["score_ordering"]) for r in rows]
                filt = [to_num(r["score_filter_accuracy"]) for r in rows]
                data = [to_num(r["score_data_retrieval"]) for r in rows]
                resp = [to_num(r["score_response_quality"]) for r in rows]
                behav = [to_num(r["score_behavior"]) for r in rows]

                all_scores["routing"].extend(routing)
                all_scores["ordering"].extend(ordering)
                all_scores["filter"].extend(filt)
                all_scores["data"].extend(data)
                all_scores["response"].extend(resp)
                all_scores["behavior"].extend(behav)

                avgs = [safe_avg(routing), safe_avg(ordering), safe_avg(filt),
                        safe_avg(data), safe_avg(resp), safe_avg(behav)]
                overall = safe_avg(avgs)

                print(f"{plat:<10} {m:<6} {ds:<8} {avgs[0]:>6.0%} {avgs[1]:>6.0%} {avgs[2]:>6.0%} "
                      f"{avgs[3]:>6.0%} {avgs[4]:>6.0%} {avgs[5]:>6.0%} {overall:>5.0%}")

    print("-" * len(header))
    avgs = [safe_avg(all_scores[k]) for k in ["routing", "ordering", "filter", "data", "response", "behavior"]]
    overall = safe_avg(avgs)
    print(f"{'OVERALL':<10} {'':<6} {'':<8} {avgs[0]:>6.0%} {avgs[1]:>6.0%} {avgs[2]:>6.0%} "
          f"{avgs[3]:>6.0%} {avgs[4]:>6.0%} {avgs[5]:>6.0%} {overall:>5.0%}")


if __name__ == "__main__":
    main()
