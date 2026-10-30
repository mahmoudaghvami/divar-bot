"""Log in to Divar once in a visible browser and save the session for the worker.

    python divar_login.py

You type your phone number and the SMS code yourself in the window that opens;
the script notices the login and saves it.
"""
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

import config

LOGIN_COOKIE = "sFrontToken"  # set by Divar once you are logged in

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel=config.BROWSER_CHANNEL or None, headless=False)
    context = browser.new_context(locale="fa-IR")
    page = context.new_page()
    try:
        page.goto("https://divar.ir/my-divar/my-posts", wait_until="domcontentloaded", timeout=120_000)
    except PlaywrightTimeout:
        print("Divar is loading slowly; keep the window open (reload it if it stays blank).")
    print("Log in to Divar in the browser window (phone number + SMS code)...")
    deadline = time.time() + 30 * 60
    while time.time() < deadline:
        if any(c["name"] == LOGIN_COOKIE for c in context.cookies()):
            time.sleep(3)  # let the remaining login cookies settle
            break
        time.sleep(2)
    else:
        raise SystemExit("Timed out waiting for the login")
    context.storage_state(path=str(config.DIVAR_SESSION))
    browser.close()

print(f"Logged in. Session saved to {config.DIVAR_SESSION}")
