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


def _infer_tool_from_output(output_raw: str) -> str:
    """Infer which MCP tool produced this output based on content.

    The server embeds navigation hints in each response:
      - next_step containing "get_indicators" -> this is step 1 output
      - next_step containing "get_metadata"   -> this is step 2 output
      - api_params present (or next_step "get_data") -> this is step 3 output
      - meta_data present (no next_step)      -> this is step 4 output

    Falls back to content-structure heuristics when these signals are absent.
    """
    # Scan both the beginning and end of the output (structural markers like
    # next_step and api_params often appear at the end of large JSON outputs)
    scan = output_raw[:3000] + output_raw[-3000:] if len(output_raw) > 6000 else output_raw

    # ---- Primary signals: next_step and structural markers ----

    # Step 1: dataset catalog
    if '"total_datasets"' in scan[:500] or '"datasets"' in scan[:100]:
        return "1_know_about_mospi_api"

    # next_step is the most reliable discriminator
    if '"next_step"' in scan:
        ns_match = re.search(r'"next_step"\s*:\s*"([^"]*)"', scan)
        if ns_match:
            ns = ns_match.group(1).lower()
            if "get_indicators" in ns:
                return "1_know_about_mospi_api"
            if "get_metadata" in ns or "metadata" in ns:
                return "2_get_indicators"
            if "get_data" in ns:
                return "3_get_metadata"

    # api_params is ALWAYS present in step 3, NEVER in others
    if '"api_params"' in scan:
        return "3_get_metadata"

    # meta_data is ALWAYS present in step 4 data responses
    if '"meta_data"' in scan:
        return "4_get_data"

    # ---- PLFS-style specific markers ----
    if '"indicators_by_frequency"' in scan[:500]:
        return "2_get_indicators"
    if '"filter_values"' in scan[:500]:
        return "3_get_metadata"

    # ---- Fallback: content structure heuristics ----
    if '"data"' in scan[:100]:
        try:
            parsed = json.loads(output_raw)
            if isinstance(parsed, dict):
                data = parsed.get("data")
                if isinstance(data, dict):
                    # Dict with nested indicator_code lists -> step 2
                    for val in data.values():
                        if isinstance(val, list) and val and isinstance(val[0], dict):
                            if "indicator_code" in val[0]:
                                return "2_get_indicators"
                    # Dict with filter-value arrays -> step 3
                    return "3_get_metadata"
                if isinstance(data, list) and data:
                    first = data[0] if isinstance(data[0], dict) else {}
                    if "indicator_code" in first and "value" not in first:
                        return "2_get_indicators"
                    # Items with nested arrays -> step 3 (list-format metadata)
                    if first and sum(1 for v in first.values() if isinstance(v, list)) >= 2:
                        return "3_get_metadata"
                    return "4_get_data"
        except (json.JSONDecodeError, TypeError):
            pass

        # Raw text fallbacks for truncated JSON
        if '"indicator_code"' in scan[:500] and '"value"' not in scan[:500]:
            return "2_get_indicators"
        return "4_get_data"

    return "unknown"


_KNOWN_DATASETS = {
    "PLFS", "CPI", "IIP", "ASI", "NAS", "WPI", "ENERGY", "AISHE",
    "CPIALRL", "HCES", "ASUSE", "GENDER", "NFHS", "NSS77", "NSS78",
    "RBI", "TUS", "EC", "ENVSTATS",
}

# Keywords in user_query or _note that map to datasets (longer/more specific first)
_DATASET_KEYWORDS = [
    # CPIALRL
    ("agricultural labourers", "CPIALRL"), ("rural labourers", "CPIALRL"),
    ("cpialrl", "CPIALRL"), ("cpi-al", "CPIALRL"), ("cpi(al)", "CPIALRL"),
    ("cpi for al", "CPIALRL"), ("cpi al ", "CPIALRL"),
    # EC
    ("economic census", "EC"), ("ec6", "EC"), ("ec7", "EC"),
    ("number of establishments", "EC"), ("number of workers", "EC"),
    # TUS
    ("time use", "TUS"), ("time-use", "TUS"), ("minutes per day", "TUS"),
    ("time spent", "TUS"), ("paid activities", "TUS"), ("unpaid activities", "TUS"),
    # NSS
    ("nss 77", "NSS77"), ("nss-77", "NSS77"), ("nss77", "NSS77"), ("77th round", "NSS77"),
    ("nss 78", "NSS78"), ("nss-78", "NSS78"), ("nss78", "NSS78"), ("78th round", "NSS78"),
    ("drinking water", "NSS78"), ("sanitation", "NSS78"),
    # HCES
    ("household consumption", "HCES"), ("hces", "HCES"), (" mpce ", "HCES"),
    ("monthly per capita expenditure", "HCES"), ("consumption expenditure", "HCES"),
    ("expenditure class", "HCES"), ("mpce by", "HCES"),
    # ASUSE
    ("annual survey of unincorporated", "ASUSE"), ("asuse", "ASUSE"),
    ("unincorporated", "ASUSE"), ("unorganised", "ASUSE"), ("own account enterprise", "ASUSE"),
    # GENDER
    ("gender statistics", "GENDER"), ("gender stat", "GENDER"),
    ("sex ratio", "GENDER"), ("female literacy", "GENDER"),
    ("infant mortality rate", "GENDER"), (" imr ", "GENDER"),
    ("maternal mortality", "GENDER"), (" mmr ", "GENDER"),
    ("wpr ", "GENDER"), ("worker population ratio", "GENDER"),
    # NFHS
    ("family health", "NFHS"), ("nfhs", "NFHS"),
    ("stunting", "NFHS"), ("wasting", "NFHS"), ("underweight", "NFHS"),
    ("immunization", "NFHS"), ("immunisation", "NFHS"),
    ("teenage pregnancy", "NFHS"), ("anemia", "NFHS"), ("anaemia", "NFHS"),
    ("institutional delivery", "NFHS"), ("antenatal", "NFHS"),
    ("contraceptive", "NFHS"), ("breastfeeding", "NFHS"),
    # ENVSTATS
    ("environment statistics", "ENVSTATS"), ("envstats", "ENVSTATS"),
    ("temperature", "ENVSTATS"), ("rainfall", "ENVSTATS"),
    ("forest cover", "ENVSTATS"), ("emission", "ENVSTATS"),
    ("air quality", "ENVSTATS"), ("solid waste", "ENVSTATS"),
    # AISHE
    ("higher education", "AISHE"), ("aishe", "AISHE"),
    ("universities", "AISHE"), ("colleges", "AISHE"),
    ("gross enrolment ratio", "AISHE"), (" ger ", "AISHE"),
    # ENERGY
    ("energy balance", "ENERGY"), ("energy consumption", "ENERGY"),
    ("energy statistics", "ENERGY"), (" ktoe", "ENERGY"), ("petajoule", "ENERGY"),
    # WPI
    ("wholesale price", "WPI"), (" wpi ", "WPI"),
    # IIP
    ("industrial production", "IIP"), (" iip ", "IIP"),
    # ASI
    ("annual survey of industries", "ASI"), (" asi ", "ASI"),
    ("factory", "ASI"), ("factories", "ASI"),
    # NAS
    ("national accounts", "NAS"), (" gdp ", "NAS"), ("gross domestic product", "NAS"),
    ("gross value added", "NAS"), (" gva ", "NAS"), (" nas ", "NAS"),
    ("capital formation", "NAS"), ("final consumption", "NAS"),
    # RBI
    ("reserve bank", "RBI"), (" rbi ", "RBI"),
    ("bank credit", "RBI"), ("bank deposits", "RBI"), ("money supply", "RBI"),
    ("repo rate", "RBI"), ("interest rate", "RBI"),
    ("scheduled commercial bank", "RBI"), ("financial inclusion", "RBI"),
    # CPI
    ("consumer price index", "CPI"), (" cpi ", "CPI"),
    ("inflation", "CPI"),
    # PLFS
    ("periodic labour", "PLFS"), ("plfs", "PLFS"), ("labour force survey", "PLFS"),
    ("unemployment rate", "PLFS"),
]


def _extract_args_from_output(tool: str, output_raw: str) -> dict:
    """Try to extract dataset and key args from the output content."""
    args = {}

    # Step 1 lists ALL datasets - don't try to extract a specific one
    if tool == "1_know_about_mospi_api":
        return args

    try:
        parsed = json.loads(output_raw)
        if isinstance(parsed, dict):
            if "dataset" in parsed:
                args["dataset"] = parsed["dataset"]
    except (json.JSONDecodeError, TypeError):
        pass

    if "dataset" not in args:
        # Try regex for "dataset": "XXX"
        m = re.search(r'"dataset"\s*:\s*"([^"]+)"', output_raw[:1000])
        if m:
            args["dataset"] = m.group(1)

    if "dataset" not in args:
        # Check user_query and _note fields for dataset keywords
        # These are specific to the actual query, not a catalog listing
        uq_match = re.search(r'"user_query"\s*:\s*"([^"]*)"', output_raw[:5000])
        note_match = re.search(r'"_note"\s*:\s*"([^"]*)"', output_raw[:5000])
        search_text = ""
        if uq_match:
            search_text += " " + uq_match.group(1)
        if note_match:
            search_text += " " + note_match.group(1)
        if search_text:
            search_lower = f" {search_text.lower()} "
            for keyword, ds in _DATASET_KEYWORDS:
                if keyword in search_lower:
                    args["dataset"] = ds
                    break

    return args


def parse_tool_calls(server_log: str) -> list[dict]:
    """Parse telemetry log into structured tool calls.

    Supports two formats:
      - Full: [TELEMETRY] Tool: / Args: / Output lines
      - Output-only: just [TELEMETRY] Output lines (tool inferred from content)

    Handles multi-line output (Windows CRLF can split JSON across lines).
    """
    if not server_log:
        return []

    # First, extract all Output blocks (may span multiple lines until next marker)
    # Use regex that captures everything until next [TELEMETRY], INFO:, or end of string
    output_pattern = re.compile(
        r'\[TELEMETRY\] Output \((\d+) bytes\): (.*?)(?=\[TELEMETRY\]|INFO:|$)',
        re.DOTALL,
    )
    tool_pattern = re.compile(r'\[TELEMETRY\] Tool: (.+)')
    args_pattern = re.compile(r'\[TELEMETRY\] Args: (.+)')

    calls = []
    current_tool = None
    current_args = None

    # Check for Tool:/Args: lines (full format)
    for m in tool_pattern.finditer(server_log):
        current_tool = m.group(1).strip()
    for m in args_pattern.finditer(server_log):
        try:
            current_args = eval(m.group(1).strip())
        except Exception:
            current_args = m.group(1).strip()

    # If full format (has Tool: lines), parse line by line
    if current_tool:
        current_tool = None
        current_args = None
        for line in server_log.split("\n"):
            line = line.strip()
            m = re.match(r"\[TELEMETRY\] Tool: (.+)", line)
            if m:
                current_tool = m.group(1).strip()
                current_args = None
                continue
            m = re.match(r"\[TELEMETRY\] Args: (.+)", line)
            if m:
                try:
                    current_args = eval(m.group(1))
                except Exception:
                    current_args = m.group(1)
                continue
            m = re.match(r"\[TELEMETRY\] Tool executed successfully", line)
            if m:
                continue
            m = re.match(r"\[TELEMETRY\] Output \((\d+) bytes\): (.+)", line)
            if m and current_tool:
                output_raw = m.group(2).strip()
                is_error = '"error"' in output_raw[:300] and "timed out" in output_raw[:300]
                has_data = '"data"' in output_raw[:300] and '"error"' not in output_raw[:300]
                calls.append({
                    "tool": current_tool,
                    "args": current_args or {},
                    "output_size": int(m.group(1)),
                    "output": output_raw,
                    "has_data": has_data,
                    "is_error": is_error,
                })
                current_tool = None
                current_args = None
        return calls

    # Output-only format: infer tool from content
    for m in output_pattern.finditer(server_log):
        output_size = int(m.group(1))
        output_raw = m.group(2).strip().replace("\r\n", "\n").replace("\r", "")
        # Clean trailing whitespace/newlines
        output_raw = output_raw.rstrip()

        tool = _infer_tool_from_output(output_raw)
        args = _extract_args_from_output(tool, output_raw)

        is_error = '"error"' in output_raw[:300] and "timed out" in output_raw[:300]
        has_data = '"data"' in output_raw[:300] and '"error"' not in output_raw[:300]

        calls.append({
            "tool": tool,
            "args": args,
            "output_size": output_size,
            "output": output_raw,
            "has_data": has_data,
            "is_error": is_error,
        })

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
    """Detect which dataset was actually used from tool calls.

    Prefers later steps (step 3/4) over earlier (step 2) and explicit JSON
    matches over keyword-inferred ones, since step 3 outputs often contain
    the actual dataset name while step 2 may match wrong keywords.
    """
    # Priority order: step 3 > step 4 > step 2 > step 1
    priority = {"3_get_metadata": 0, "4_get_data": 1, "2_get_indicators": 2,
                "1_know_about_mospi_api": 3, "unknown": 4}
    sorted_calls = sorted(calls, key=lambda c: priority.get(c["tool"], 4))

    for call in sorted_calls:
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

    dataset_tag = data.get("dataset", "")

    # For REGRESSION runs, load the expected dataset per query from the queries CSV
    query_datasets = {}
    if dataset_tag == "REGRESSION":
        csv_path_raw = data.get("csv", "").replace("\\", "/")
        if csv_path_raw:
            # Try relative to json_path's parent's parent (responses/ -> regression_testing/)
            candidates = [
                json_path.parent / csv_path_raw,
                json_path.parent.parent / csv_path_raw,
                Path(csv_path_raw),
            ]
            for cp in candidates:
                if cp.exists():
                    with open(cp, newline="", encoding="utf-8") as f:
                        for row in csv.DictReader(f):
                            qno = row.get("no", "").strip()
                            ds = row.get("datasets", "").strip()
                            if qno and ds:
                                query_datasets[int(qno)] = ds.split("|")[0]  # use first dataset for cross-dataset
                    break

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

        # Resolve per-query dataset (REGRESSION mode uses queries CSV, else tag)
        qno = result.get("no", "")
        dataset = query_datasets.get(int(qno), dataset_tag) if qno and query_datasets else dataset_tag

        # Detect routed dataset: telemetry first, then response text fallback
        routed = detect_dataset_used(calls)
        if not routed and calls:
            # Fallback: scan response text for dataset keywords
            resp_lower = f" {response.lower()} "
            for keyword, ds in _DATASET_KEYWORDS:
                if keyword in resp_lower:
                    routed = ds
                    break

        row = {
            "platform": platform,
            "mode": mode,
            "dataset": dataset,
            "no": qno,
            "query": result.get("query", ""),
            "indicator_tested": result.get("indicator_tested", ""),
            "filters_tested": result.get("filters_tested", ""),
            "status": result.get("status", ""),
            "dataset_routed_to": routed,
            "correct_routing": "YES" if routed == dataset else ("WRONG" if routed else "N/A"),
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
    import argparse
    from datetime import datetime
    parser = argparse.ArgumentParser(description="Parse MCP tester JSON results into CSV")
    parser.add_argument("--dir", type=str, default=None,
                        help="Directory containing JSON files (default: responses/)")
    parser.add_argument("--run-name", type=str, default=None,
                        help="Name for this run's output folder (default: today's date YYYY-MM-DD). "
                             "Output goes to responses/<run-name>/benchmark_results.csv")
    parser.add_argument("files", nargs="*", help="JSON files to parse (optional, defaults to all in --dir)")
    args = parser.parse_args()

    # Determine working directory (where JSON files live)
    work_dir = Path(args.dir) if args.dir else RESPONSES_DIR

    # Find JSON files to parse
    if args.files:
        json_files = [Path(p) for p in args.files]
    else:
        # Find latest JSON per dataset in work_dir
        all_jsons = sorted(work_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        # Group by dataset prefix, keep latest
        latest = {}
        for f in all_jsons:
            prefix = f.stem.rsplit("_", 2)[0]  # e.g., "PLFS" from "PLFS_20260131_171044"
            latest[prefix] = f
        json_files = list(latest.values())

    if not json_files:
        print(f"No JSON files found in {work_dir}")
        return

    # Sort files by modification time so newer files override older ones
    json_files.sort(key=lambda p: p.stat().st_mtime)

    print(f"Parsing {len(json_files)} files:")
    for f in json_files:
        print(f"  {f.name}")

    all_rows = []
    for jf in json_files:
        rows = parse_json_file(jf)
        all_rows.extend(rows)
        print(f"  {jf.name}: {len(rows)} queries")

    # Deduplicate: for same (dataset, no), keep the LAST occurrence (from latest file)
    seen = {}
    for i, row in enumerate(all_rows):
        key = (row["dataset"], row["no"])
        seen[key] = i  # overwrite with latest index
    deduped_rows = [all_rows[i] for i in sorted(seen.values())]
    if len(deduped_rows) < len(all_rows):
        print(f"\n  Deduplicated: {len(all_rows)} -> {len(deduped_rows)} rows (removed {len(all_rows) - len(deduped_rows)} duplicates)")
    all_rows = deduped_rows

    # Write CSV to dated subfolder
    run_name = args.run_name or datetime.now().strftime("%Y-%m-%d")
    out_dir = work_dir / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "benchmark_results.csv"
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
    print(f"Run folder:     {out_dir}")
    print(f"Total rows: {len(all_rows)}")
    print(f"\nTo judge this run:")
    print(f"  python judge.py --csv \"{out_path}\"")

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
