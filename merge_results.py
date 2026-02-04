#!/usr/bin/env python3
"""
Merge new results into existing benchmark and judge CSVs.

Usage:
    # After re-running failed queries, merge the new JSON into existing CSVs:
    python merge_results.py --new responses_claude/claude_CPI_single_rerun.json \
                            --benchmark responses_claude/benchmark_results/benchmark_results_single_indicator.csv \
                            --judge responses_claude/benchmark_results/judge_results_single_indicator.csv
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

csv.field_size_limit(10 * 1024 * 1024)

BASE_DIR = Path(__file__).parent

# Import parse functions from parse_results
sys.path.insert(0, str(BASE_DIR))
from parse_results import parse_json_file


def merge_into_benchmark(benchmark_csv: Path, new_rows: list[dict], platform: str, mode: str):
    """Merge new rows into existing benchmark CSV, replacing matching rows."""
    existing_rows = []
    fieldnames = None

    # Read existing
    with open(benchmark_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            existing_rows.append(row)

    # Create lookup for new rows
    new_lookup = {}
    for row in new_rows:
        key = (row.get("platform", platform), row.get("mode", mode),
               row.get("dataset"), int(row.get("no", 0)))
        new_lookup[key] = row

    # Merge
    updated_count = 0
    for i, row in enumerate(existing_rows):
        key = (row.get("platform"), row.get("mode"), row.get("dataset"), int(row.get("no", 0)))
        if key in new_lookup:
            # Update with new data, preserving any fields not in new row
            for k, v in new_lookup[key].items():
                existing_rows[i][k] = v
            updated_count += 1
            print(f"  Updated: {key[2]} Q{key[3]}")

    # Write back
    with open(benchmark_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)

    print(f"  Total updated: {updated_count} rows in {benchmark_csv.name}")
    return updated_count


def merge_into_judge(judge_csv: Path, updated_queries: list[tuple], rejudge: bool = False):
    """
    Update judge CSV for the updated queries.
    If rejudge=True, clears scores so they can be re-judged.
    """
    if not judge_csv.exists():
        print(f"  Judge CSV not found: {judge_csv}")
        return

    existing_rows = []
    fieldnames = None

    with open(judge_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            existing_rows.append(row)

    # Mark updated queries for re-judging
    updated_count = 0
    for i, row in enumerate(existing_rows):
        key = (row.get("platform"), row.get("mode"), row.get("dataset"), int(row.get("no", 0)))
        if key in updated_queries:
            if rejudge:
                # Clear judge scores so they get re-evaluated
                for field in ["score_filter_accuracy", "score_data_retrieval",
                             "score_response_quality", "score_behavior",
                             "filter_notes", "data_notes", "response_notes",
                             "behavior_notes", "total_score", "judge_reasoning"]:
                    if field in existing_rows[i]:
                        existing_rows[i][field] = ""
            updated_count += 1

    with open(judge_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)

    print(f"  Marked {updated_count} rows for re-judging in {judge_csv.name}")


def main():
    parser = argparse.ArgumentParser(description="Merge new results into existing CSVs")
    parser.add_argument("--new", type=str, required=True, nargs="+",
                        help="New JSON result file(s) from re-run")
    parser.add_argument("--benchmark", type=str, required=True,
                        help="Existing benchmark_results.csv to update")
    parser.add_argument("--judge", type=str, default=None,
                        help="Existing judge_results.csv to update (optional)")
    parser.add_argument("--rejudge", action="store_true",
                        help="Clear judge scores for updated rows so they get re-judged")
    args = parser.parse_args()

    benchmark_csv = Path(args.benchmark)
    if not benchmark_csv.exists():
        print(f"Benchmark CSV not found: {benchmark_csv}")
        sys.exit(1)

    # Parse new JSON files
    all_new_rows = []
    for json_path in args.new:
        print(f"Parsing {json_path}...")
        rows = parse_json_file(Path(json_path))
        all_new_rows.extend(rows)
        print(f"  Found {len(rows)} rows")

    if not all_new_rows:
        print("No rows parsed from new JSON files")
        sys.exit(1)

    # Detect platform and mode from first row
    platform = all_new_rows[0].get("platform", "claude")
    mode = all_new_rows[0].get("mode", "single")

    print(f"\nMerging {len(all_new_rows)} rows into {benchmark_csv.name}...")
    updated = merge_into_benchmark(benchmark_csv, all_new_rows, platform, mode)

    # Track which queries were updated
    updated_queries = set()
    for row in all_new_rows:
        key = (row.get("platform", platform), row.get("mode", mode),
               row.get("dataset"), int(row.get("no", 0)))
        updated_queries.add(key)

    if args.judge:
        judge_csv = Path(args.judge)
        print(f"\nUpdating judge CSV...")
        merge_into_judge(judge_csv, updated_queries, args.rejudge)

    print("\nDone!")
    if args.judge and args.rejudge:
        print(f"\nNext: Re-run judge.py to score the updated rows")


if __name__ == "__main__":
    main()
