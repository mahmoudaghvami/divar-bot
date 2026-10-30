"""Read and send Divar chat messages through divar.ir in a headless browser.

Uses a saved login (divar_session.json, made by divar_login.py). Unofficial: it drives the
same web page a person uses, so it can break when Divar changes its page.
"""
import logging
from dataclasses import dataclass

from playwright.sync_api import Browser, Page, sync_playwright

import config

log = logging.getLogger(__name__)
CHAT_URL = "https://divar.ir/chat"

LIST_JS = """() => [...document.querySelectorAll('a[href^="/chat/"]')].map(a => {
  const q = s => a.querySelector(s)?.innerText?.trim() || '';
  return {id: a.getAttribute('href').slice(6), title: q('.kt-conversation__body'),
          name: q('.kt-conversation__name'), last: q('.kt-conversation__message'),
          mine: [...a.querySelectorAll('.kt-tag__text')].some(t => t.innerText.includes('آگهی من'))};
})"""

MESSAGES_JS = """() => [...document.querySelectorAll('.kt-message')].map(m => {
  const body = m.querySelector('.kt-message__body');
  if (!body) return null;
  const copy = body.cloneNode(true);
  copy.querySelectorAll('.kt-message-info').forEach(e => e.remove());
  return {peer: m.classList.contains('kt-message--peer'),
          text: copy.innerText.trim(),
          kind: body.classList.contains('kt-message__body--text-message') ? 'text' : 'other'};
}).filter(Boolean)"""


@dataclass
class ChatSummary:
    id: str
    title: str
    name: str
    last: str


class DivarChat:
    def __init__(self, headless=True):
        self._pw = sync_playwright().start()
        self.browser: Browser = self._pw.chromium.launch(channel=config.BROWSER_CHANNEL or None, headless=headless)
        self.context = self.browser.new_context(storage_state=str(config.DIVAR_SESSION), locale="fa-IR")
        self.page: Page = self.context.new_page()

    def close(self):
        try:
            self.context.storage_state(path=str(config.DIVAR_SESSION))  # keep refreshed cookies
        finally:
            self.browser.close()
            self._pw.stop()

    def _open(self, url):
        self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        if "login" in self.page.url:
            raise RuntimeError("Divar login expired; run divar_login.py again")

    def conversations(self) -> list[ChatSummary]:
        """Chats on my ads whose title matches AD_TITLE_MATCH."""
        self._open(CHAT_URL)
        # the official "postchi" chat renders first; wait for real conversations ("آگهی من" tags)
        self.page.wait_for_selector(".kt-conversation .kt-tag__text", timeout=60_000)
        self.page.wait_for_timeout(1500)
        rows = self.page.evaluate(LIST_JS)
        return [ChatSummary(r["id"], r["title"], r["name"], r["last"]) for r in rows
                if r["mine"] and config.AD_TITLE_MATCH in r["title"]]

    def messages(self, conv_id) -> list[dict]:
        """[{"peer": True if the buyer wrote it, "text": ..., "kind": "text"|"other"}], oldest first."""
        self._open(f"{CHAT_URL}/{conv_id}")
        self.page.wait_for_selector(".kt-message", timeout=60_000)
        self.page.wait_for_timeout(1500)  # let the rest of the history render
        return self.page.evaluate(MESSAGES_JS)

    def send(self, conv_id, text):
        if not self.page.url.endswith(conv_id):
            self._open(f"{CHAT_URL}/{conv_id}")
        box = self.page.locator("#chat-input")
        box.wait_for(timeout=30_000)
        box.fill(text)
        self.page.get_by_role("button", name="ارسال پیام").click()
        # confirm it shows up as my last message
        self.page.wait_for_function(
            """t => { const m = [...document.querySelectorAll('.kt-message:not(.kt-message--peer) .kt-message__body')];
                      return m.length && m[m.length - 1].innerText.includes(t.slice(0, 20)); }""",
            arg=text, timeout=20_000,
        )
