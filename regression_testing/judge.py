#!/usr/bin/env python3
"""
Rule-based judge for MoSPI MCP benchmark results.

FREE alternative to the LLM-as-judge approach.
Uses deterministic heuristics + ground truth to score 7 dimensions:

  1. Routing             — did LLM pick the correct dataset?            (auto)
  2. Ordering            — were tools called in 1→2→3→4 order?          (auto)
  3. Filter Accuracy     — did get_data use numeric codes?               (heuristic)
  4. Data Retrieval      — did any get_data call return real data?       (auto)
  5. Response Quality    — do numbers in the response match output?      (heuristic)
  6. Ground Truth        — does API output contain expected value(s)?    (deterministic)
  7. API Response Valid. — do returned data rows match query entities?   (heuristic)

Usage:
    python judge.py
    python judge.py --csv responses/benchmark_results.csv
    python judge.py --dir responses/my_run/
    python judge.py --only "CPI:2,PLFS:5"
    python judge.py --ground-truth queries/regression_test_queries.csv
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

csv.field_size_limit(10 * 1024 * 1024)  # 10 MB

RESPONSES_DIR = Path(__file__).parent / "responses"

# ── Helpers ──────────────────────────────────────────────────────────────────

def auto_score_routing(row: dict) -> int:
    expected = row.get("dataset", "").strip().upper()
    actual   = row.get("dataset_routed_to", "").strip().upper()
    if not actual:
        return 0
    return 1 if actual == expected else 0


def auto_score_ordering(row: dict) -> int:
    trace = row.get("tool_trace", "")
    if not trace:
        return 0
    tool_nums = re.findall(r'(\d)_', trace)
    if not tool_nums:
        return 0
    deduped = [tool_nums[0]]
    for t in tool_nums[1:]:
        if t != deduped[-1]:
            deduped.append(t)
    expected = ['1', '2', '3', '4']
    idx = 0
    for t in deduped:
        if idx < len(expected) and t == expected[idx]:
            idx += 1
    return 1 if idx == 4 else 0


def _extract_all_calls(row: dict) -> dict:
    raw = row.get("all_tool_calls", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Dimension 3: Filter Accuracy ─────────────────────────────────────────────

_NUMERIC_RE  = re.compile(r'^\d+(\.\d+)?$')
_YEAR_RE     = re.compile(r'^\d{4}(-\d{2,4})?$')
_NAME_WORDS_RE = re.compile(
    r'\b(male|female|rural|urban|total|supply|demand|export|import|'
    r'bihar|delhi|mumbai|india|all|national|state|district)\b',
    re.IGNORECASE,
)


def _value_looks_like_name(v) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    if _NUMERIC_RE.match(s) or _YEAR_RE.match(s):
        return False
    if len(s) <= 2:
        return False
    if _NAME_WORDS_RE.search(s):
        return True
    if ' ' in s:
        return True
    return False


def score_filter_accuracy(row: dict) -> tuple[int, str]:
    all_calls = _extract_all_calls(row)
    get_data_calls = all_calls.get("4_get_data", [])

    meta_calls = all_calls.get("3_get_metadata", [])
    meta_reached = any(not c.get("is_error", False) for c in meta_calls)
    if not meta_reached and not get_data_calls:
        return -1, "Step 3 (get_metadata) was never successfully reached."

    if not get_data_calls:
        return 0, "No get_data calls found."

    name_like = []
    for call in get_data_calls:
        args = call.get("args", {})
        filters = args.get("filters", args) if isinstance(args, dict) else {}
        if not isinstance(filters, dict):
            continue
        for key, val in filters.items():
            if key in ("dataset", "indicator_code"):
                continue
            if _value_looks_like_name(val):
                name_like.append(f"{key}={val!r}")

    if name_like:
        return 0, f"String names used instead of codes: {', '.join(name_like[:5])}"

    filters_tested_raw = row.get("filters_tested", "").strip()
    if filters_tested_raw:
        required_keys = [k.strip() for k in filters_tested_raw.split(",") if k.strip()]
        all_filter_keys = set()
        for call in get_data_calls:
            args = call.get("args", {})
            filters = args.get("filters", args) if isinstance(args, dict) else {}
            if isinstance(filters, dict):
                all_filter_keys.update(filters.keys())

        missing = []
        for req in required_keys:
            req_lower = req.lower()
            found = any(req_lower in k.lower() or k.lower() in req_lower for k in all_filter_keys)
            if not found:
                missing.append(req)

        if missing:
            return 0, f"Required filters missing from get_data: {', '.join(missing)}"

    return 1, "All filter values appear to use numeric codes."


# ── Dimension 4: Data Retrieval ───────────────────────────────────────────────

def score_data_retrieval(row: dict) -> tuple[int, str]:
    got = row.get("got_data", "").upper()
    if got == "YES":
        return 1, "At least one get_data call returned actual data rows."

    response = row.get("response_full", "").lower()
    no_data_phrases = [
        "no data found", "data not available", "not found", "no data available",
        "api did not return", "timed out", "timeout", "could not retrieve",
    ]
    if any(p in response for p in no_data_phrases):
        all_calls = _extract_all_calls(row)
        if all_calls.get("4_get_data"):
            return 1, "No data returned but LLM honestly acknowledged this."

    reached = row.get("reached_get_data", "").upper()
    if reached != "YES":
        return 0, "get_data was never called (tool chain broke before step 4)."

    return 0, "All get_data calls returned empty or errored."


# ── Dimension 5: Response Quality ────────────────────────────────────────────

_NUMBER_RE = re.compile(r'\b\d[\d,]*(?:\.\d+)?\b')


def _extract_numbers(text: str) -> set[str]:
    raw = _NUMBER_RE.findall(text)
    return {n.replace(",", "") for n in raw}


def score_response_quality(row: dict) -> tuple[int, str]:
    response    = row.get("response_full", "")
    data_output = row.get("4_data_output", "")
    got         = row.get("got_data", "").upper()

    if got == "YES" and data_output:
        resp_nums = _extract_numbers(response)
        data_nums = _extract_numbers(data_output)
        if not resp_nums:
            return 0, "Response contains no numbers despite data being retrieved."
        overlap = resp_nums & data_nums
        if not overlap:
            return 0, f"Response numbers {list(resp_nums)[:5]} don't match data output."
        return 1, f"Response numbers match API output ({len(overlap)} matching values)."

    if got != "YES":
        response_lower = response.lower()
        has_numbers    = bool(_NUMBER_RE.search(response))
        honest_phrases = [
            "no data", "not found", "not available", "timed out", "timeout",
            "could not retrieve", "api did not return", "unable to fetch",
        ]
        is_honest = any(p in response_lower for p in honest_phrases)
        if has_numbers and not is_honest:
            return 0, "Response contains statistics but no data was retrieved — possible fabrication."
        if is_honest:
            return 1, "No data retrieved; response honestly acknowledges the failure."
        return 0, "No data retrieved and response neither has numbers nor acknowledges failure."

    return 1, "Response appears consistent with API output."


# ── Dimension 7: API Response Validation ─────────────────────────────────────

_INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand",
    "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan",
    "sikkim", "tamil nadu", "telangana", "tripura", "uttar pradesh",
    "uttarakhand", "west bengal",
    "andaman and nicobar", "chandigarh", "dadra and nagar haveli",
    "daman and diu", "delhi", "jammu and kashmir", "ladakh", "lakshadweep",
    "puducherry", "all india", "india", "national",
}

_CPI_GROUPS = [
    "food and beverages", "pan tobacco and intoxicants", "clothing and footwear",
    "housing", "fuel and light", "miscellaneous", "health",
    "transport and communication", "recreation and amusement",
    "education", "personal care", "cereals and products",
    "vegetables", "pulses", "milk", "oils and fats", "sugar",
]

_YEAR_ENTITY_RE = re.compile(r'\b(20\d{2}(?:-\d{2,4})?|19\d{2})\b')
_SECTOR_WORDS   = {"rural", "urban", "combined"}
_GENDER_MAP     = {"male": "male", "men": "male", "female": "female",
                   "women": "female", "woman": "female", "man": "male"}
_MONTHS         = {
    "january": "january", "february": "february", "march": "march",
    "april": "april", "may": "may", "june": "june", "july": "july",
    "august": "august", "september": "september", "october": "october",
    "november": "november", "december": "december",
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september",
    "oct": "october", "nov": "november", "dec": "december",
}

_FIELD_CANDIDATES = {
    "year":   ["year", "financial_year", "period", "Year"],
    "sector": ["sector", "Sector", "level", "Level"],
    "gender": ["gender", "Gender", "sex"],
    "state":  ["state", "State", "state_name"],
    "month":  ["month", "Month", "month_name"],
    "group":  ["group", "Group", "commodity_group", "description"],
}


def _extract_entities(query: str) -> dict:
    """Extract year, sector, gender, state, month, group from a natural language query."""
    q = query.lower().strip()
    entities = {}

    years = _YEAR_ENTITY_RE.findall(q)
    if years:
        entities["year"] = years

    sectors = [s for s in _SECTOR_WORDS if s in q]
    if sectors:
        entities["sector"] = sectors

    genders = set(canonical for word, canonical in _GENDER_MAP.items()
                  if re.search(r'\b' + word + r'\b', q))
    if genders:
        entities["gender"] = list(genders)

    # Longest match first to avoid "delhi" matching before "new delhi" etc.
    states = [s for s in sorted(_INDIAN_STATES, key=len, reverse=True) if s in q]
    if states:
        entities["state"] = states[:2]

    months = set(_MONTHS[m] for m in _MONTHS if re.search(r'\b' + m + r'\b', q))
    if months:
        entities["month"] = list(months)

    groups = [g for g in _CPI_GROUPS if g in q]
    if groups:
        entities["group"] = groups

    return entities


def _parse_data_rows(data_output: str) -> list:
    if not data_output:
        return []
    try:
        parsed = json.loads(data_output)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        rows = parsed.get("data", [])
        return rows if isinstance(rows, list) else []
    return []


def _row_field_value(row: dict, entity_type: str):
    """Return the lowercased string value of the best matching field, or None."""
    for field in _FIELD_CANDIDATES.get(entity_type, []):
        for k, v in row.items():
            if k.lower() == field.lower():
                return str(v).lower().strip()
    return None


def score_api_validation(row: dict) -> tuple:
    """
    Dimension 7: Do the API data rows match the entities in the user query?
    Returns (score, notes): 1=match, 0=mismatch, -1=N/A.
    """
    if row.get("got_data", "").upper() != "YES":
        return -1, "No data retrieved — nothing to validate."

    data_output = row.get("4_data_output", "").strip()
    if not data_output:
        return -1, "got_data=YES but 4_data_output is empty."

    entities = _extract_entities(row.get("query", ""))
    if not entities:
        return -1, "No matchable entities found in query."

    data_rows = _parse_data_rows(data_output)
    if not data_rows:
        return -1, "Could not parse data rows from 4_data_output."

    sample = data_rows[:5]
    mismatches = []

    for entity_type, entity_values in entities.items():
        row_values = [_row_field_value(r, entity_type) for r in sample if isinstance(r, dict)]
        row_values = [v for v in row_values if v is not None]

        if not row_values:
            continue  # field not in this dataset's schema — skip, don't penalise

        matched = any(
            ev in rv or rv in ev
            for rv in row_values
            for ev in entity_values
        )
        if not matched:
            mismatches.append(
                f"{entity_type}: expected {entity_values!r}, got {list(set(row_values))!r}"
            )

    if mismatches:
        return 0, "Data rows don't match query: " + "; ".join(mismatches)
    return 1, f"Data rows match query entities ({list(entities.keys())})."


# ── Dimension 6: Ground Truth Validation ─────────────────────────────────────

def load_ground_truth(gt_csv_path: Path) -> dict[int, str]:
    """
    Read a ground truth CSV and return {query_no: ground_truth_value}.
    The CSV must have columns: no, ground_truth_value.
    Multi-value answers are pipe-separated in ground_truth_value (e.g. "5.1|6.2").
    NO_DATA means the query should return no data.
    """
    gt = {}
    if not gt_csv_path or not Path(gt_csv_path).exists():
        return gt
    with open(gt_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            no_raw = row.get("no", "").strip()
            val    = row.get("ground_truth_value", "").strip()
            if no_raw and val:
                try:
                    gt[int(no_raw)] = val
                except ValueError:
                    pass
    return gt


def score_ground_truth(row: dict, gt_value: str) -> tuple[int, str]:
    """
    Dimension 6: Does the API output contain the expected ground truth value(s)?

    Returns (score, notes):
      1  = correct (API output matches ground truth, or NO_DATA correctly returned)
      0  = wrong   (API output doesn't contain ground truth, or got data when none expected)
     -1  = N/A     (no ground truth available for this query)
    """
    if not gt_value:
        return -1, "No ground truth available for this query."

    got = row.get("got_data", "").upper()

    # Edge case: expected no data
    if gt_value.strip().upper() == "NO_DATA":
        if got != "YES":
            return 1, "Correctly returned no data (as expected)."
        return 0, "Got data when NO_DATA was expected."

    # Normal case: expected specific value(s)
    if got != "YES":
        return 0, f"No data retrieved; expected ground truth value(s): {gt_value}"

    data_output = row.get("4_data_output", "")
    if not data_output:
        return 0, f"4_data_output is empty; expected: {gt_value}"

    # Support pipe-separated multi-value ground truth: "5.1|6.2|3.8"
    expected_values = [v.strip() for v in gt_value.split("|") if v.strip()]
    missing = []
    for ev in expected_values:
        # Normalize: remove commas for comparison (e.g., "1,234" == "1234")
        ev_norm = ev.replace(",", "")
        out_norm = data_output.replace(",", "")
        if ev_norm not in out_norm:
            missing.append(ev)

    if missing:
        return 0, f"Ground truth value(s) not found in API output: {missing}"
    return 1, f"All ground truth value(s) found in API output: {expected_values}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Rule-based judge for MoSPI MCP Benchmark (free)")
    parser.add_argument("--dir", type=str, default=None,
                        help="Directory containing benchmark_results.csv (default: responses/)")
    parser.add_argument("--csv", type=str, default=None,
                        help="Path to benchmark_results.csv (overrides --dir)")
    parser.add_argument("--start", type=int, default=1,
                        help="Start from this row number (for resuming)")
    parser.add_argument("--only", type=str, default=None,
                        help="Only judge specific queries: 'dataset:no,dataset:no'")
    parser.add_argument("--ground-truth", type=str, default=None,
                        help="Path to ground truth CSV (must have 'no' and 'ground_truth_value' columns). "
                             "Default: queries/regression_test_queries.csv if it exists.")
    args = parser.parse_args()

    only_queries = None
    if args.only:
        only_queries = set()
        for item in args.only.split(","):
            parts = item.strip().split(":")
            if len(parts) == 2:
                only_queries.add((parts[0].strip().upper(), int(parts[1].strip())))

    work_dir = Path(args.dir) if args.dir else RESPONSES_DIR
    csv_path = Path(args.csv) if args.csv else work_dir / "benchmark_results.csv"

    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        print("Run parse_results.py first to generate benchmark_results.csv")
        sys.exit(1)

    # Load ground truth
    base_dir = Path(__file__).parent
    default_gt = base_dir / "queries" / "regression_test_queries.csv"
    gt_path = Path(args.ground_truth) if args.ground_truth else (default_gt if default_gt.exists() else None)
    ground_truth = load_ground_truth(gt_path) if gt_path else {}
    if ground_truth:
        print(f"Ground truth loaded: {len(ground_truth)} entries from {gt_path}")
    else:
        print("Ground truth: none loaded (dimension 6 will be N/A for all rows)")

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    print(f"Loaded {len(rows)} queries from {csv_path}")
    print(f"Judge: rule-based (free, no API calls)")
    print()

    out_path = work_dir / "judge_results.csv"
    out_fields = list(rows[0].keys()) + [
        "score_routing", "score_ordering",
        "score_filter_accuracy", "filter_notes",
        "score_data_retrieval", "data_notes",
        "score_response_quality", "response_notes",
        "score_ground_truth", "ground_truth_notes",
        "score_api_validation", "api_validation_notes",
        "total_score",
    ]

    results = []
    for i, row in enumerate(rows):
        row_num = i + 1
        if row_num < args.start:
            continue

        ds   = row.get("dataset", "")
        qno  = row.get("no", "")
        qstr = row.get("query", "")[:60]

        if only_queries and (ds.upper(), int(qno)) not in only_queries:
            continue

        score_routing  = auto_score_routing(row)
        score_ordering = auto_score_ordering(row)

        score_filter,   filter_notes   = score_filter_accuracy(row)
        score_data,     data_notes     = score_data_retrieval(row)
        score_response, response_notes = score_response_quality(row)

        gt_value = ground_truth.get(int(qno), "") if qno else ""
        score_gt, gt_notes = score_ground_truth(row, gt_value)

        score_api_val, api_val_notes = score_api_validation(row)

        raw_scores = [score_routing, score_ordering, score_filter,
                      score_data, score_response, score_gt, score_api_val]
        total = sum(s for s in raw_scores if isinstance(s, int) and s > 0)

        display_filter  = "N/A" if score_filter  == -1 else score_filter
        display_gt      = "N/A" if score_gt      == -1 else score_gt
        display_api_val = "N/A" if score_api_val == -1 else score_api_val

        print(f"[{row_num}/{len(rows)}] {ds} Q{qno}: {qstr}...")
        print(f"    Routing={score_routing} Order={score_ordering} Filter={display_filter} "
              f"Data={score_data} Response={score_response} GT={display_gt} "
              f"APIVal={display_api_val} Total={total}/7")
        if filter_notes:
            print(f"    [Filter]   {filter_notes}")
        if data_notes:
            print(f"    [Data]     {data_notes}")
        if response_notes:
            print(f"    [Response] {response_notes}")
        if gt_notes and score_gt != -1:
            print(f"    [GT]       {gt_notes}")
        if api_val_notes and score_api_val != -1:
            print(f"    [APIVal]   {api_val_notes}")
        print()

        out_row = dict(row)
        out_row.update({
            "score_routing":          score_routing,
            "score_ordering":         score_ordering,
            "score_filter_accuracy":  display_filter,
            "filter_notes":           filter_notes,
            "score_data_retrieval":   score_data,
            "data_notes":             data_notes,
            "score_response_quality": score_response,
            "response_notes":         response_notes,
            "score_ground_truth":     display_gt,
            "ground_truth_notes":     gt_notes,
            "score_api_validation":   display_api_val,
            "api_validation_notes":   api_val_notes,
            "total_score":            total,
        })
        results.append(out_row)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(results)

    print(f"Results written to: {out_path}")
    print(f"Total queries judged: {len(results)}")

    # ── Summary table ─────────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("BENCHMARK SUMMARY")
    print("=" * 90)

    def safe_avg(values):
        nums = [v for v in values if isinstance(v, (int, float))]
        return sum(nums) / len(nums) if nums else 0

    def to_num(val):
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    platforms = sorted(set(r.get("platform", "unknown") for r in results))
    modes     = sorted(set(r.get("mode", "single") for r in results))
    datasets  = sorted(set(r.get("dataset", "") for r in results))

    header = (f"{'Platform':<10} {'Mode':<6} {'Dataset':<8} "
              f"{'Routing':>7} {'Order':>7} {'Filter':>7} "
              f"{'Data':>7} {'Resp':>7} {'GT':>7} {'APIVal':>7} {'Avg':>6}")
    print(header)
    print("-" * len(header))

    all_scores = {k: [] for k in ["routing", "ordering", "filter", "data", "response", "gt", "apival"]}

    for plat in platforms:
        for m in modes:
            for ds in datasets:
                subset = [r for r in results
                          if r.get("platform") == plat and r.get("mode") == m and r.get("dataset") == ds]
                if not subset:
                    continue

                routing  = [to_num(r["score_routing"]) for r in subset]
                ordering = [to_num(r["score_ordering"]) for r in subset]
                filt     = [to_num(r["score_filter_accuracy"]) for r in subset]
                data     = [to_num(r["score_data_retrieval"]) for r in subset]
                resp     = [to_num(r["score_response_quality"]) for r in subset]
                gt       = [to_num(r["score_ground_truth"]) for r in subset]
                apival   = [to_num(r["score_api_validation"]) for r in subset]

                for k, v in zip(["routing", "ordering", "filter", "data", "response", "gt", "apival"],
                                 [routing, ordering, filt, data, resp, gt, apival]):
                    all_scores[k].extend(v)

                avgs = [safe_avg(routing), safe_avg(ordering), safe_avg(filt),
                        safe_avg(data), safe_avg(resp), safe_avg(gt), safe_avg(apival)]
                overall = safe_avg(avgs)
                print(f"{plat:<10} {m:<6} {ds:<8} "
                      f"{avgs[0]:>6.0%} {avgs[1]:>6.0%} {avgs[2]:>6.0%} "
                      f"{avgs[3]:>6.0%} {avgs[4]:>6.0%} {avgs[5]:>6.0%} {avgs[6]:>6.0%} {overall:>5.0%}")

    print("-" * len(header))
    avgs = [safe_avg(all_scores[k]) for k in ["routing", "ordering", "filter", "data", "response", "gt", "apival"]]
    overall = safe_avg(avgs)
    print(f"{'OVERALL':<10} {'':<6} {'':<8} "
          f"{avgs[0]:>6.0%} {avgs[1]:>6.0%} {avgs[2]:>6.0%} "
          f"{avgs[3]:>6.0%} {avgs[4]:>6.0%} {avgs[5]:>6.0%} {avgs[6]:>6.0%} {overall:>5.0%}")


if __name__ == "__main__":
    main()
