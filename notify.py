"""Talking to the owner through a Bale bot (Bale's Bot API mirrors Telegram's)."""
import logging

import requests

from config import BALE_BOT_TOKEN, BALE_CHAT_ID

log = logging.getLogger(__name__)
BALE_API = "https://tapi.bale.ai/bot{token}/{method}"


def bale(method: str, **params):
    """Call a Bale Bot API method and return its `result`."""
    r = requests.post(BALE_API.format(token=BALE_BOT_TOKEN, method=method), json=params, timeout=40)
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Bale {method} failed: {body}")
    return body.get("result")


def redact(error) -> str:
    """Error text without the bot token, which requests puts in the URL."""
    text = str(error)
    return text.replace(BALE_BOT_TOKEN, "***") if BALE_BOT_TOKEN else text


def send_owner(text: str) -> bool:
    if not (BALE_BOT_TOKEN and BALE_CHAT_ID):
        log.warning("Bale not configured; alert was:\n%s", text)
        return False
    try:
        bale("sendMessage", chat_id=BALE_CHAT_ID, text=text)
        return True
    except (requests.RequestException, RuntimeError) as e:
        log.warning("Bale alert failed (%s); alert was:\n%s", redact(e), text)
        return False


def fmt(price):
    return f"{price:,} تومان" if price else "-"
