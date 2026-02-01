#!/usr/bin/env python3
"""
ChatGPT MCP Tester - Playwright automation script.

Reads queries from a CSV, sends each to ChatGPT with MCP connector attached,
waits for the response, and captures the response text.

Usage:
    # Step 1: Save auth (one-time) - log into ChatGPT, connect MCP
    python tester.py --save-auth

    # Step 2: Run tests
    python tester.py --dataset plfs --csv queries/plfs.csv
    python tester.py --dataset cpi --csv queries/cpi.csv
    python tester.py --dataset asi --csv queries/asi.csv

    # Resume from a specific query number
    python tester.py --dataset plfs --csv queries/plfs.csv --start 5

    # Also take screenshots
    python tester.py --dataset plfs --csv queries/plfs.csv --screenshots
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
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
RESPONSES_DIR = BASE_DIR / "responses"
AUTH_DIR = BASE_DIR / "browser_data"

# --- Selectors ---
# ChatGPT UI selectors. Update these if the UI changes.
SELECTORS = {
    "composer": "#prompt-textarea",
    "send_btn": 'button[data-testid="send-button"]',
    "stop_btn": 'button[aria-label="Stop generating"]',
    "assistant_msg": 'div[data-message-author-role="assistant"]',
    "attach_btn": 'button[data-testid="composer-plus-btn"]',
    "new_chat": 'a[data-testid="create-new-chat-button"]',
}

# MCP connector name to look for in the attach menu
MCP_CONNECTOR_NAME = "mospi_V1"


def save_auth():
    """Open persistent browser for manual login. Auth persists in browser_data/."""
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
        page.goto("https://chatgpt.com/")

        print(">>> Browser opened. Please:")
        print("    1. Log into ChatGPT")
        print("    2. Connect your MCP server in developer mode")
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
    Wait until ChatGPT finishes generating.

    1. Wait for stop button or assistant message to appear (generation started).
    2. Wait for stop button to disappear (generation done).
    3. Extra settle time for rendering.
    """
    # Wait for generation to start
    try:
        page.wait_for_selector(
            f'{SELECTORS["stop_btn"]}, {SELECTORS["assistant_msg"]}',
            state="attached",
            timeout=120_000,
        )
    except PwTimeout:
        if not page.query_selector(SELECTORS["assistant_msg"]):
            print("    [warn] No response detected within 30s")
            return False

    # Wait for stop button to disappear
    try:
        page.wait_for_selector(
            SELECTORS["stop_btn"],
            state="detached",
            timeout=timeout_ms,
        )
    except PwTimeout:
        print("    [warn] Response still generating after timeout")
        return False

    # Let final content settle (MCP responses can be long)
    time.sleep(15)
    return True


def get_response_text(page):
    """Extract the last assistant message text from the page."""
    messages = page.locator(SELECTORS["assistant_msg"])
    count = messages.count()
    if count == 0:
        return ""
    return messages.nth(count - 1).inner_text()


def attach_mcp_connector(page, connector_name=MCP_CONNECTOR_NAME):
    """Click +, then More, then select the MCP connector from dropdown."""
    try:
        # Step 1: Click the + button
        plus_btn = page.locator(SELECTORS["attach_btn"])
        plus_btn.wait_for(state="visible", timeout=10_000)
        plus_btn.click()
        time.sleep(1)

        # Step 2: Hover on "More" to open submenu
        more_btn = page.locator('div[role="menuitem"][data-has-submenu]')
        more_btn.wait_for(state="visible", timeout=5_000)
        more_btn.hover()
        time.sleep(1.5)

        # Step 3: Click the MCP connector in the submenu
        connector = page.get_by_text(connector_name, exact=False)
        connector.wait_for(state="visible", timeout=5_000)
        connector.click()
        time.sleep(1)
        print(f"    MCP connector '{connector_name}' attached")
        return True
    except PwTimeout:
        print(f"    [warn] Could not find MCP connector '{connector_name}'")
        return False
    except Exception as e:
        print(f"    [warn] Failed to attach MCP connector: {e}")
        return False


def send_query(page, query_text):
    """Type a query into the composer and send it."""
    composer = page.locator(SELECTORS["composer"])
    composer.click()
    composer.fill("")
    time.sleep(0.3)
    composer.fill(query_text)
    time.sleep(0.5)

    send = page.locator(SELECTORS["send_btn"])
    send.click()


def start_new_chat(page):
    """Navigate to a fresh chat."""
    page.goto("https://chatgpt.com/", wait_until="networkidle")
    time.sleep(2)


def run_queries(csv_path, dataset_tag, start_from=1, headless=False, take_screenshots=False, mcp_name=MCP_CONNECTOR_NAME):
    """Read CSV, send each query, capture response text and optionally screenshot."""
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
    results = []
    results_path = RESPONSES_DIR / f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    print(f"Loaded {len(queries)} queries from {csv_path}")
    print(f"Starting from query #{start_from}")
    print(f"Responses -> {RESPONSES_DIR}/")
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

        for row in queries:
            qno = int(row["no"])
            query = row["query"]

            if qno < start_from:
                continue

            print(f"[{qno}/{len(queries)}] {query[:80]}...")

            start_new_chat(page)

            # Attach MCP connector
            attach_mcp_connector(page, mcp_name)

            # Send query
            try:
                send_query(page, query)
            except Exception as e:
                print(f"    [ERROR] Failed to send: {e}")
                results.append({
                    "no": qno,
                    "query": query,
                    "status": "SEND_ERROR",
                    "response_text": "",
                    "error": str(e),
                })
                continue

            # Give ChatGPT time to start processing (MCP tool calls take time)
            time.sleep(30)

            # Wait for response
            success = wait_for_response(page, timeout_ms=180_000)

            # Capture response text
            response_text = get_response_text(page)
            print(f"    Response: {response_text[:120]}...")

            # Optional screenshot
            ss_name = ""
            if take_screenshots:
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1)
                ss_name = f"{tag}_{qno:02d}.png"
                ss_path = SCREENSHOTS_DIR / ss_name
                page.screenshot(path=str(ss_path), full_page=True)
                print(f"    Screenshot: {ss_path}")

            status = "PASS" if success else "TIMEOUT"
            results.append({
                "no": qno,
                "query": query,
                "status": status,
                "response_text": response_text,
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

        context.close()

    print(f"\nDone. Results -> {results_path}")

    # Print summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] != "PASS")
    print(f"Summary: {passed} passed, {failed} failed/timeout out of {len(results)} run")


def main():
    parser = argparse.ArgumentParser(description="ChatGPT MCP Tester")
    parser.add_argument(
        "--save-auth", action="store_true",
        help="Open browser to log in and save auth state.",
    )
    parser.add_argument("--csv", type=str, help="Path to queries CSV file")
    parser.add_argument("--dataset", type=str, default=None,
                        help="Dataset tag for filenames (default: CSV stem)")
    parser.add_argument("--start", type=int, default=1,
                        help="Start from this query number (for resuming)")
    parser.add_argument("--headless", action="store_true",
                        help="Run in headless mode")
    parser.add_argument("--screenshots", action="store_true",
                        help="Take screenshots (off by default)")
    parser.add_argument("--mcp-name", type=str, default=MCP_CONNECTOR_NAME,
                        help=f"MCP connector name to attach (default: {MCP_CONNECTOR_NAME})")
    args = parser.parse_args()

    if args.save_auth:
        save_auth()
        return

    if not args.csv:
        parser.error("--csv is required when not using --save-auth")

    if not AUTH_DIR.exists():
        print(f"Auth not found at {AUTH_DIR}")
        print("Run: python tester.py --save-auth")
        sys.exit(1)

    run_queries(args.csv, args.dataset, args.start, args.headless,
                take_screenshots=args.screenshots, mcp_name=args.mcp_name)


if __name__ == "__main__":
    main()
