#!/usr/bin/env python3
"""
Parse MCP tester JSON results into a clean CSV.

Extracts tool call traces from raw telemetry logs and produces a flat CSV
with one row per query.

Usage:
    python parse_results.py                          # parse all latest JSONs
    python parse_results.py responses/PLFS_*.json    # parse specific files
"""

import csv
import json
import re
import sys
from pathlib import Path

RESPONSES_DIR = Path(__file__).parent / "responses"


def parse_tool_calls(server_log: str) -> list[dict]:
    """Parse telemetry log into structured tool calls."""
    if not server_log:
        return []

    calls = []
    current_tool = None
    current_args = None

    for line in server_log.split("\n"):
        line = line.strip()

        # Tool name
        m = re.match(r"\[TELEMETRY\] Tool: (.+)", line)
        if m:
            current_tool = m.group(1)
            current_args = None
            continue

        # Tool args
        m = re.match(r"\[TELEMETRY\] Args: (.+)", line)
        if m:
            try:
                current_args = eval(m.group(1))  # safe: our own telemetry output
            except Exception:
                current_args = m.group(1)
            continue

        # Tool executed = end of this call
        m = re.match(r"\[TELEMETRY\] Tool executed successfully: (.+)", line)
        if m and current_tool:
            # Check for output on next lines - look ahead
            continue

        # Output line
        m = re.match(r"\[TELEMETRY\] Output \((\d+) bytes\): (.+)", line)
        if m and current_tool:
            output_size = int(m.group(1))
            output_raw = m.group(2)

            # Check if it was an error
            is_error = '"error"' in output_raw[:300] and "timed out" in output_raw[:300]
            has_data = '"data"' in output_raw[:300] and '"error"' not in output_raw[:300]

            call = {
                "tool": current_tool,
                "args": current_args or {},
                "output_size": output_size,
                "output": output_raw,
                "has_data": has_data,
                "is_error": is_error,
            }
            calls.append(call)
            current_tool = None
            current_args = None

    return calls


def extract_get_data_args(calls: list[dict]) -> dict:
    """Extract the filters from the last get_data call."""
    for call in reversed(calls):
        if call["tool"] == "4_get_data":
            args = call.get("args", {})
            return args.get("filters", args)
    return {}


def summarize_tool_trace(calls: list[dict]) -> str:
    """Create a short readable trace like: 1_know -> 2_get_indicators(PLFS) -> 3_get_metadata -> 4_get_data"""
    parts = []
    for c in calls:
        tool = c["tool"]
        args = c.get("args", {})

        if tool == "1_know_about_mospi_api":
            parts.append("1_know")
        elif tool == "2_get_indicators":
            ds = args.get("dataset", "?")
            parts.append(f"2_indicators({ds})")
        elif tool == "3_get_metadata":
            ds = args.get("dataset", "?")
            ind = args.get("indicator_code", "?")
            parts.append(f"3_metadata({ds},ind={ind})")
        elif tool == "4_get_data":
            ds = args.get("dataset", "?")
            status = "OK" if c.get("has_data") else ("ERR" if c.get("is_error") else "EMPTY")
            parts.append(f"4_data({ds})[{status}]")
        else:
            parts.append(tool)

    return " -> ".join(parts)


def detect_dataset_used(calls: list[dict]) -> str:
    """Detect which dataset was actually used from tool calls."""
    for call in calls:
        args = call.get("args", {})
        if "dataset" in args:
            return args["dataset"]
        if isinstance(args, dict) and "filters" in args:
            filters = args["filters"]
            if isinstance(filters, dict) and "dataset" in filters:
                return filters["dataset"]
    return ""


def got_data(calls: list[dict]) -> bool:
    """Check if any get_data call returned actual data."""
    for call in calls:
        if call["tool"] == "4_get_data" and call.get("has_data"):
            return True
    return False


def had_timeout(calls: list[dict]) -> bool:
    """Check if any call had a timeout error."""
    for call in calls:
        if call.get("is_error"):
            return True
    return False


def parse_json_file(json_path: Path) -> list[dict]:
    """Parse a single JSON results file into rows."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    dataset = data.get("dataset", "")

    # Extract platform and mode from filename (e.g., chatgpt_PLFS_single_20260201_123456.json)
    fname = json_path.stem
    if fname.startswith("chatgpt_"):
        platform = "chatgpt"
    elif fname.startswith("claude_"):
        platform = "claude"
    else:
        platform = "unknown"

    mode = "multi" if "_multi_" in fname else "single"
    rows = []

    for result in data.get("results", []):
        calls = parse_tool_calls(result.get("server_log", ""))
        get_data_filters = extract_get_data_args(calls)

        # Clean response text
        response = result.get("response_text", "")
        response_short = response[:500].replace("\n", " ").strip()
        if len(response) > 500:
            response_short += "..."

        # Collect ALL calls per tool type (there may be retries)
        tool_all_outputs = {}
        tool_all_calls = {}
        for c in calls:
            tool_name = c["tool"]
            if tool_name not in tool_all_outputs:
                tool_all_outputs[tool_name] = []
                tool_all_calls[tool_name] = []
            tool_all_outputs[tool_name].append(c.get("output", ""))
            tool_all_calls[tool_name].append({
                "args": c.get("args", {}),
                "output": c.get("output", ""),
                "has_data": c.get("has_data", False),
                "is_error": c.get("is_error", False),
            })

        # For CSV: last output per tool (readable), plus all_calls JSON for judge
        know_output = (tool_all_outputs.get("1_know_about_mospi_api") or [""])[-1]
        indicators_output = (tool_all_outputs.get("2_get_indicators") or [""])[-1]
        metadata_output = (tool_all_outputs.get("3_get_metadata") or [""])[-1]
        data_output = (tool_all_outputs.get("4_get_data") or [""])[-1]

        # All calls summary for judge (JSON of all calls with args + truncated output)
        all_calls_json = json.dumps(tool_all_calls, ensure_ascii=False, default=str)

        row = {
            "platform": platform,
            "mode": mode,
            "dataset": dataset,
            "no": result.get("no", ""),
            "query": result.get("query", ""),
            "indicator_tested": result.get("indicator_tested", ""),
            "filters_tested": result.get("filters_tested", ""),
            "status": result.get("status", ""),
            "dataset_routed_to": detect_dataset_used(calls),
            "correct_routing": "YES" if detect_dataset_used(calls) == dataset else ("WRONG" if detect_dataset_used(calls) else "N/A"),
            "num_tool_calls": len(calls),
            "tool_trace": summarize_tool_trace(calls),
            "reached_get_data": "YES" if any(c["tool"] == "4_get_data" for c in calls) else "NO",
            "got_data": "YES" if got_data(calls) else "NO",
            "had_timeout": "YES" if had_timeout(calls) else "NO",
            "get_data_filters": json.dumps(get_data_filters, ensure_ascii=False) if get_data_filters else "",
            "1_know_output": know_output,
            "2_indicators_output": indicators_output,
            "3_metadata_output": metadata_output,
            "4_data_output": data_output,
            "all_tool_calls": all_calls_json,
            "response_short": response_short,
            "response_full": response.replace("\n", "\\n"),
        }
        rows.append(row)

    return rows


def main():
    # Find JSON files to parse
    if len(sys.argv) > 1:
        json_files = [Path(p) for p in sys.argv[1:]]
    else:
        # Find latest JSON per dataset
        all_jsons = sorted(RESPONSES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        # Group by dataset prefix, keep latest
        latest = {}
        for f in all_jsons:
            prefix = f.stem.rsplit("_", 2)[0]  # e.g., "PLFS" from "PLFS_20260131_171044"
            latest[prefix] = f
        json_files = list(latest.values())

    if not json_files:
        print("No JSON files found.")
        return

    print(f"Parsing {len(json_files)} files:")
    for f in json_files:
        print(f"  {f.name}")

    all_rows = []
    for jf in json_files:
        rows = parse_json_file(jf)
        all_rows.extend(rows)
        print(f"  {jf.name}: {len(rows)} queries")

    # Write CSV
    out_path = RESPONSES_DIR / "benchmark_results.csv"
    fieldnames = [
        "platform", "mode", "dataset", "no", "query", "indicator_tested", "filters_tested",
        "status", "dataset_routed_to", "correct_routing",
        "num_tool_calls", "tool_trace", "reached_get_data",
        "got_data", "had_timeout", "get_data_filters",
        "1_know_output", "2_indicators_output", "3_metadata_output", "4_data_output",
        "all_tool_calls",
        "response_short", "response_full",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nCSV written to: {out_path}")
    print(f"Total rows: {len(all_rows)}")

    # Print quick summary
    print("\n--- Summary ---")
    platforms = sorted(set(r["platform"] for r in all_rows))
    modes = sorted(set(r["mode"] for r in all_rows))
    print(f"Platforms: {', '.join(platforms)}")
    print(f"Modes: {', '.join(modes)}")
    print()

    datasets = sorted(set(r["dataset"] for r in all_rows))
    print(f"{'Platform':<10} {'Mode':<8} {'Dataset':<10} {'Total':>5} {'Data':>5} {'Timeout':>7} {'Routing':>8}")
    print("-" * 65)
    for plat in platforms:
        for m in modes:
            for ds in datasets:
                rows = [r for r in all_rows if r["platform"] == plat and r["mode"] == m and r["dataset"] == ds]
                if not rows:
                    continue
                total = len(rows)
                got = sum(1 for r in rows if r["got_data"] == "YES")
                timeout = sum(1 for r in rows if r["had_timeout"] == "YES")
                correct = sum(1 for r in rows if r["correct_routing"] == "YES")
                print(f"{plat:<10} {m:<8} {ds:<10} {total:>5} {got:>5} {timeout:>7} {correct:>5}/{total}")

    totals = len(all_rows)
    total_got = sum(1 for r in all_rows if r["got_data"] == "YES")
    total_timeout = sum(1 for r in all_rows if r["had_timeout"] == "YES")
    total_correct = sum(1 for r in all_rows if r["correct_routing"] == "YES")
    print("-" * 65)
    print(f"{'TOTAL':<10} {'':<8} {'':<10} {totals:>5} {total_got:>5} {total_timeout:>7} {total_correct:>5}/{totals}")


if __name__ == "__main__":
    main()
