#!/usr/bin/env python3
"""
Re-run failed queries and merge results back into benchmark/judge CSVs.

Usage:
    # Create a failures.csv with columns: mode,dataset,no
    # Then run:
    python rerun_failed.py --failures failures.csv --dir responses_claude/

    # Or specify individual queries:
    python rerun_failed.py --queries "single,CPI,2" "single,CPI,10" "multiple,ASI,1"
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

csv.field_size_limit(10 * 1024 * 1024)

BASE_DIR = Path(__file__).parent


def load_failures_from_csv(csv_path: str) -> list[dict]:
    """Load failed queries from a CSV file."""
    failures = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            failures.append({
                "mode": row["mode"].strip(),
                "dataset": row["dataset"].strip().upper(),
                "no": int(row["no"]),
            })
    return failures


def parse_query_strings(query_strings: list[str]) -> list[dict]:
    """Parse query strings like 'single,CPI,2' into dicts."""
    failures = []
    for qs in query_strings:
        parts = qs.split(",")
        if len(parts) != 3:
            print(f"Invalid query format: {qs} (expected mode,dataset,no)")
            continue
        failures.append({
            "mode": parts[0].strip(),
            "dataset": parts[1].strip().upper(),
            "no": int(parts[2].strip()),
        })
    return failures


def get_query_from_original_csv(mode: str, dataset: str, query_no: int) -> dict | None:
    """Find the original query from the queries CSV."""
    mode_folder = "single_indicator" if mode == "single" else "multiple_indicator"
    csv_path = BASE_DIR / "queries" / "claude" / mode_folder / f"claude_queries_{dataset}.csv"

    if not csv_path.exists():
        print(f"Query CSV not found: {csv_path}")
        return None

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row.get("no", 0)) == query_no:
                return row
    return None


def run_single_query(mode: str, dataset: str, query_no: int, work_dir: Path) -> dict | None:
    """Run a single query using the claude tester."""
    mode_folder = "single_indicator" if mode == "single" else "multiple_indicator"
    csv_path = BASE_DIR / "queries" / "claude" / mode_folder / f"claude_queries_{dataset}.csv"

    # Create a temp CSV with just this query
    query_row = get_query_from_original_csv(mode, dataset, query_no)
    if not query_row:
        print(f"Query not found: {mode}/{dataset}/Q{query_no}")
        return None

    temp_csv = work_dir / f"_temp_rerun_{dataset}_{query_no}.csv"
    with open(temp_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=query_row.keys())
        writer.writeheader()
        writer.writerow(query_row)

    # Run the tester
    output_json = work_dir / f"_rerun_{dataset}_{mode}_{query_no}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    cmd = [
        "python", str(BASE_DIR / "testers" / "claude_tester.py"),
        "--dataset", dataset,
        "--csv", str(temp_csv),
        "--delay", "30",
    ]

    print(f"  Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  Tester failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"  Tester timed out")

    # Find the output file (claude tester writes to responses_claude/)
    responses_dir = BASE_DIR / "responses_claude"
    pattern = f"claude_{dataset}_{mode}*.json"
    latest = sorted(responses_dir.glob(pattern), key=lambda p: p.stat().st_mtime)

    if latest:
        output_json = latest[-1]
        with open(output_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("results"):
                return data["results"][0]

    # Cleanup temp file
    temp_csv.unlink(missing_ok=True)
    return None


def update_benchmark_csv(csv_path: Path, mode: str, dataset: str, query_no: int, new_row: dict):
    """Update a single row in the benchmark CSV."""
    rows = []
    fieldnames = None
    updated = False

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if (row.get("mode") == mode and
                row.get("dataset") == dataset and
                int(row.get("no", 0)) == query_no):
                # Update this row with new data
                row.update(new_row)
                updated = True
            rows.append(row)

    if updated:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Updated {csv_path.name}: {mode}/{dataset}/Q{query_no}")
    else:
        print(f"  Row not found in {csv_path.name}: {mode}/{dataset}/Q{query_no}")


def judge_single_query(row: dict, model: str = "gemini-2.5-pro") -> dict:
    """Run the judge on a single query row."""
    # Import judge functions
    sys.path.insert(0, str(BASE_DIR))
    from judge import call_llm_judge, auto_score_routing, auto_score_ordering, build_judge_prompt
    import os
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  GEMINI_API_KEY not set, skipping judge")
        return {}

    client = genai.Client(api_key=api_key)

    # Auto-score
    score_routing = auto_score_routing(row)
    score_ordering = auto_score_ordering(row)

    # Build prompt and call LLM
    prompt = build_judge_prompt(row)
    judge_result = call_llm_judge(client, model, prompt)

    if "error" in judge_result:
        print(f"  Judge error: {judge_result['error'][:100]}")
        return {
            "score_routing": score_routing,
            "score_ordering": score_ordering,
            "score_filter_accuracy": "ERR",
            "score_data_retrieval": "ERR",
            "score_response_quality": "ERR",
            "score_behavior": "ERR",
            "total_score": f"{score_routing + score_ordering}/6",
        }

    total = score_routing + score_ordering
    for key in ["score_filter_accuracy", "score_data_retrieval", "score_response_quality", "score_behavior"]:
        val = judge_result.get(key, 0)
        if isinstance(val, (int, float)):
            total += val

    return {
        "score_routing": score_routing,
        "score_ordering": score_ordering,
        "score_filter_accuracy": judge_result.get("score_filter_accuracy", "ERR"),
        "filter_notes": judge_result.get("filter_notes", ""),
        "score_data_retrieval": judge_result.get("score_data_retrieval", "ERR"),
        "data_notes": judge_result.get("data_notes", ""),
        "score_response_quality": judge_result.get("score_response_quality", "ERR"),
        "response_notes": judge_result.get("response_notes", ""),
        "score_behavior": judge_result.get("score_behavior", "ERR"),
        "behavior_notes": judge_result.get("behavior_notes", ""),
        "total_score": f"{total}/6",
        "judge_reasoning": judge_result.get("judge_reasoning", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Re-run failed queries and merge results")
    parser.add_argument("--failures", type=str, help="CSV file with failed queries (mode,dataset,no)")
    parser.add_argument("--queries", nargs="+", help="Query strings like 'single,CPI,2'")
    parser.add_argument("--dir", type=str, default="responses_claude/benchmark_results",
                        help="Directory with benchmark_results.csv and judge_results.csv")
    parser.add_argument("--skip-run", action="store_true", help="Skip running tester, just re-judge")
    parser.add_argument("--skip-judge", action="store_true", help="Skip judging")
    args = parser.parse_args()

    if not args.failures and not args.queries:
        parser.error("Either --failures or --queries is required")

    work_dir = Path(args.dir)

    # Load failures
    if args.failures:
        failures = load_failures_from_csv(args.failures)
    else:
        failures = parse_query_strings(args.queries)

    print(f"Loaded {len(failures)} failed queries to re-run")
    print()

    # Group by mode for reporting
    single_fails = [f for f in failures if f["mode"] == "single"]
    multi_fails = [f for f in failures if f["mode"] == "multi" or f["mode"] == "multiple"]

    print(f"Single indicator: {len(single_fails)}")
    print(f"Multiple indicator: {len(multi_fails)}")
    print()

    # Process each failure
    for i, fail in enumerate(failures, 1):
        mode = fail["mode"]
        dataset = fail["dataset"]
        query_no = fail["no"]

        # Normalize mode
        if mode == "multiple":
            mode = "multi"

        print(f"[{i}/{len(failures)}] {mode}/{dataset}/Q{query_no}")

        if not args.skip_run:
            # Run the query
            result = run_single_query(mode, dataset, query_no, work_dir)
            if result:
                print(f"  Got result: status={result.get('status')}")
            else:
                print(f"  No result captured")
                continue

        # Find benchmark CSV
        if mode == "single":
            benchmark_csv = work_dir / "benchmark_results_single_indicator.csv"
            judge_csv = work_dir / "judge_results_single_indicator.csv"
        else:
            benchmark_csv = work_dir / "benchmark_results_multiple_indicators.csv"
            judge_csv = work_dir / "judge_results_multiple_indicators.csv"

        # TODO: Parse new result and update benchmark CSV
        # For now, user needs to re-run parse_results.py manually

        if not args.skip_judge and judge_csv.exists():
            # Re-judge this query
            # First read the updated benchmark row
            with open(benchmark_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (row.get("dataset") == dataset and
                        int(row.get("no", 0)) == query_no):
                        print(f"  Judging...")
                        judge_scores = judge_single_query(row)
                        if judge_scores:
                            update_benchmark_csv(judge_csv, mode, dataset, query_no, judge_scores)
                        break

        # Small delay between queries
        if i < len(failures):
            time.sleep(5)

    print()
    print("Done!")
    print()
    print("Next steps:")
    print("1. Re-run parse_results.py to update benchmark CSVs")
    print("2. Re-run judge.py with --start to judge new results")


if __name__ == "__main__":
    main()
