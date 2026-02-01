#!/usr/bin/env python3
"""
Claude.ai MCP Tester - Playwright automation script.

Reads queries from a CSV, sends each to Claude.ai with MCP connector attached,
waits for the response, captures the response text and server telemetry.

Usage:
    # Step 1: Save auth (one-time) - log into Claude.ai
    python tester_claude.py --save-auth

    # Step 2: Run tests
    python tester_claude.py --dataset PLFS --csv queries_claude/claude_queries_PLFS.csv --server-log /tmp/mospi_telemetry.log

    # Resume from a specific query number
    python tester_claude.py --dataset PLFS --csv queries_claude/claude_queries_PLFS.csv --server-log /tmp/mospi_telemetry.log --start 5
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

BASE_DIR = Path(__file__).parent.parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots_claude"
RESPONSES_DIR = BASE_DIR / "responses_claude"
AUTH_DIR = BASE_DIR / "browser_data_claude"

# --- Selectors ---
# Claude.ai UI selectors
SELECTORS = {
    "composer": 'div[contenteditable="true"].ProseMirror',
    "send_btn": 'button[aria-label="Send Message"]',
    "stop_btn": 'button[aria-label="Stop Response"]',
    "assistant_msg": 'div[data-is-streaming]',
    "response_container": 'div.font-claude-message',
    "new_chat": 'a[href="/new"]',
    "integrations_btn": 'button[data-testid="integrations-menu-button"]',
}


def read_server_log(log_path: str) -> str:
    """Read current contents of server telemetry log."""
    if not log_path:
        return ""
    try:
        with open(log_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def save_auth():
    """Open persistent browser for manual login. Auth persists in browser_data_claude/."""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(AUTH_DIR),
            headless=False,
            channel="chromium",
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://claude.ai/")

        print(">>> Browser opened. Please:")
        print("    1. Log into Claude.ai")
        print("    2. Make sure your MCP server is connected (check integrations)")
        print("    3. Close the browser window when done")
        print()

        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass

        context.close()
        print(f"Auth saved to {AUTH_DIR}")


def wait_for_response(page, timeout_ms=180_000):
    """
    Wait until Claude finishes generating.

    1. Wait for any response content to appear.
    2. Wait for streaming to stop.
    3. Extra settle time for rendering.
    """
    # Multiple selectors to detect response start
    response_selectors = [
        '[data-testid="chat-message-content"]',
        'div.font-claude-message',
        'div[data-is-streaming]',
        '[data-testid="assistant-message"]',
        'div.prose',  # Common markdown container
    ]

    # Wait for response to start - try multiple selectors
    response_found = False
    for selector in response_selectors:
        try:
            page.wait_for_selector(selector, state="attached", timeout=10_000)
            response_found = True
            print(f"    [debug] Response detected via: {selector}")
            break
        except PwTimeout:
            continue

    if not response_found:
        # Last resort: wait a bit and check if page content changed
        print("    [warn] No response selector matched, waiting 30s...")
        time.sleep(30)

    # Poll for streaming to finish (can't use wait_for_function due to CSP)
    # Look for stop button to disappear
    start_time = time.time()
    while time.time() - start_time < timeout_ms / 1000:
        # Multiple stop button selectors
        stop_selectors = [
            'button[aria-label="Stop Response"]',
            'button[aria-label="Stop generating"]',
            'button:has-text("Stop")',
        ]
        stop_visible = False
        for sel in stop_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    stop_visible = True
                    break
            except:
                continue

        if not stop_visible:
            # No stop button visible = done streaming
            break
        time.sleep(2)
    else:
        print("    [warn] Response still generating after timeout")
        return False

    # Let final content settle
    time.sleep(10)
    return True


def get_response_text(page):
    """Extract the last assistant message text from the page."""
    # Claude uses different selectors - try multiple approaches
    selectors_to_try = [
        'div[data-is-streaming="false"]',
        'div[data-is-streaming]',
        'div.font-claude-message',
        'div[data-testid="assistant-message"]',
        '[data-testid="chat-message-content"]',
        'div.prose',
    ]

    for selector in selectors_to_try:
        messages = page.locator(selector)
        count = messages.count()
        if count > 0:
            return messages.nth(count - 1).inner_text()

    # Fallback: get all text from the conversation area
    try:
        conv = page.locator('main').first
        return conv.inner_text()
    except:
        return ""


def send_query(page, query_text):
    """Type a query into the composer and send it."""
    # Find the contenteditable composer
    composer = page.locator('div[contenteditable="true"]').first
    composer.click()
    time.sleep(0.3)

    # Clear and type
    composer.fill("")
    time.sleep(0.2)
    composer.fill(query_text)
    time.sleep(0.5)

    # Send - try multiple selectors
    send_selectors = [
        'button[aria-label="Send Message"]',
        'button[type="submit"]',
        'button:has-text("Send")',
    ]

    for selector in send_selectors:
        try:
            send = page.locator(selector).first
            if send.is_visible():
                send.click()
                return
        except:
            continue

    # Fallback: press Enter
    composer.press("Enter")


def start_new_chat(page):
    """Navigate to a fresh chat."""
    page.goto("https://claude.ai/new", wait_until="networkidle")
    time.sleep(3)


def run_queries(
    csv_path,
    dataset_tag,
    server_log="",
    start_from=1,
    headless=False,
    take_screenshots=False,
    query_delay=60,
):
    """Read CSV, send each query, capture response text and server log."""
    RESPONSES_DIR.mkdir(exist_ok=True)
    if take_screenshots:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)

    queries = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            queries.append(row)

    if not queries:
        print("No queries found in CSV.")
        return

    tag = dataset_tag or Path(csv_path).stem
    # Detect mode from path
    mode = "multi" if "multiple" in csv_path else "single"
    results = []
    # Filename: claude_{dataset}_{mode}_{timestamp}.json
    results_path = RESPONSES_DIR / f"claude_{tag}_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    print(f"Loaded {len(queries)} queries from {csv_path}")
    print(f"Starting from query #{start_from}")
    print(f"Responses -> {RESPONSES_DIR}/")
    if server_log:
        print(f"Server log -> {server_log}")
    if take_screenshots:
        print(f"Screenshots -> {SCREENSHOTS_DIR}/")
    print()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(AUTH_DIR),
            headless=headless,
            channel="chromium",
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(60_000)

        for qno, row in enumerate(queries, 1):
            query_no = int(row.get("no", qno))
            query = row["query"]

            if query_no < start_from:
                continue

            print(f"[{query_no}/{len(queries)}] {query[:80]}...")

            # Snapshot server log before query
            log_before = read_server_log(server_log)

            start_new_chat(page)

            # Send query
            try:
                send_query(page, query)
            except Exception as e:
                print(f"    [ERROR] Failed to send: {e}")
                results.append({
                    "no": query_no,
                    "query": query,
                    "indicator_tested": row.get("indicator_tested", ""),
                    "filters_tested": row.get("filters_tested", ""),
                    "status": "SEND_ERROR",
                    "response_text": "",
                    "server_log": "",
                    "error": str(e),
                })
                continue

            # Wait for response
            success = wait_for_response(page, timeout_ms=180_000)

            # Capture response text
            response_text = get_response_text(page)
            print(f"    Response: {response_text[:120]}...")

            # Snapshot server log after
            log_after = read_server_log(server_log)
            new_log = ""
            if log_after and log_before:
                new_log = log_after[len(log_before):] if log_after.startswith(log_before) else log_after
            elif log_after:
                new_log = log_after

            # Optional screenshot
            ss_name = ""
            if take_screenshots:
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1)
                ss_name = f"{tag}_{query_no:02d}.png"
                ss_path = SCREENSHOTS_DIR / ss_name
                page.screenshot(path=str(ss_path), full_page=True)
                print(f"    Screenshot: {ss_path}")

            status = "PASS" if success else "TIMEOUT"
            results.append({
                "no": query_no,
                "query": query,
                "indicator_tested": row.get("indicator_tested", ""),
                "filters_tested": row.get("filters_tested", ""),
                "status": status,
                "response_text": response_text,
                "server_log": new_log,
                "screenshot": ss_name,
            })

            # Save after each query
            with open(results_path, "w", encoding="utf-8") as f:
                json.dump({
                    "dataset": tag,
                    "csv": str(csv_path),
                    "timestamp": datetime.now().isoformat(),
                    "total_queries": len(queries),
                    "results": results,
                }, f, indent=2, ensure_ascii=False)

            # Rate limit delay
            if query_no < len(queries):
                print(f"    Waiting {query_delay}s before next query...")
                time.sleep(query_delay)

        context.close()

    print(f"\nDone. Results -> {results_path}")

    # Print summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] != "PASS")
    print(f"Summary: {passed} passed, {failed} failed/timeout out of {len(results)} run")


def main():
    parser = argparse.ArgumentParser(description="Claude.ai MCP Tester")
    parser.add_argument(
        "--save-auth", action="store_true",
        help="Open browser to log in and save auth state.",
    )
    parser.add_argument("--csv", type=str, help="Path to queries CSV file")
    parser.add_argument("--dataset", type=str, default=None,
                        help="Dataset tag for filenames (default: CSV stem)")
    parser.add_argument("--server-log", type=str, default="",
                        help="Path to server telemetry log file")
    parser.add_argument("--start", type=int, default=1,
                        help="Start from this query number (for resuming)")
    parser.add_argument("--delay", type=int, default=60,
                        help="Delay between queries in seconds (default: 60)")
    parser.add_argument("--headless", action="store_true",
                        help="Run in headless mode")
    parser.add_argument("--screenshots", action="store_true",
                        help="Take screenshots (off by default)")
    args = parser.parse_args()

    if args.save_auth:
        save_auth()
        return

    if not args.csv:
        parser.error("--csv is required when not using --save-auth")

    if not AUTH_DIR.exists():
        print(f"Auth not found at {AUTH_DIR}")
        print("Run: python tester_claude.py --save-auth")
        sys.exit(1)

    run_queries(
        args.csv,
        args.dataset,
        server_log=args.server_log,
        start_from=args.start,
        headless=args.headless,
        take_screenshots=args.screenshots,
        query_delay=args.delay,
    )


if __name__ == "__main__":
    main()
