"""Watch Divar chats, draft replies, and send each one after the owner taps «بفرست» in Bale.

    python worker.py

Loop: every POLL_SECONDS read the chats on the ad in Divar; for every chat whose last
message is from the buyer, draft a reply and post it to Bale with approve/skip buttons.
In between, listen to Bale: an approved draft is typed into Divar and sent.
Replying to a draft in Bale with your own text sends your text instead.
Logs carry counts and ids only, never message text (GitHub Actions logs can be public).
"""
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass

import requests

import config
import notify
import rules
import store
from divar_web import DivarChat
from negotiator import Decision, apply, decide

log = logging.getLogger("worker")


@dataclass
class Draft:
    id: str
    conv_id: str
    name: str
    sig: str
    decision: Decision
    bale_message_id: int | None = None


pending: dict[str, Draft] = {}
drafted_sigs: set[str] = set()
last_preview: dict[str, str] = {}
bale_offset = None


def _sig(conv_id, msgs):
    last = msgs[-1]["text"] if msgs else ""
    return f"{conv_id}:{len(msgs)}:{hashlib.sha1(last.encode()).hexdigest()[:10]}"


def _conversation(conv_id, msgs) -> store.Conversation:
    """Rebuild the negotiation state from what Divar shows (Divar is the source of truth)."""
    conv = store.load(conv_id)
    conv.messages = [{"from": "buyer" if m["peer"] else "bot", "text": m["text"]} for m in msgs]
    our_prices = [p for m in msgs if not m["peer"] for p in [rules.parse_price(m["text"])] if p]
    conv.lowest_offer = min(our_prices) if our_prices else None
    return conv


def _buttons(draft_id):
    return {"inline_keyboard": [[
        {"text": "✅ بفرست", "callback_data": f"send:{draft_id}"},
        {"text": "❌ نفرست", "callback_data": f"skip:{draft_id}"},
    ]]}


def check_divar(dc: DivarChat):
    new = 0
    for chat in dc.conversations():
        if last_preview.get(chat.id) == chat.last and not any(d.conv_id == chat.id for d in pending.values()):
            continue
        last_preview[chat.id] = chat.last
        msgs = dc.messages(chat.id)
        if not msgs or not msgs[-1]["peer"]:
            continue  # we spoke last; waiting for the buyer
        sig = _sig(chat.id, msgs)
        if sig in drafted_sigs:
            continue
        drafted_sigs.add(sig)
        name = chat.name.replace("~ کاربر:", "").strip() or "خریدار"

        conv = _conversation(chat.id, msgs)
        if conv.status == "deal":
            notify.send_owner(f"💬 {name} (معامله نهایی‌شده) پیام جدید داده:\n«{msgs[-1]['text']}»")
            continue
        if msgs[-1]["kind"] != "text":
            notify.send_owner(f"📎 {name} عکس/صدا/فایل فرستاده؛ خودتان در دیوار ببینید.")
            continue

        # drop older drafts for this chat; the new one answers everything so far
        for old in [d for d in pending.values() if d.conv_id == chat.id]:
            pending.pop(old.id)
        d = decide(conv)
        draft = Draft(uuid.uuid4().hex[:8], chat.id, name, sig, d)
        buyer_lines = "\n".join(f"«{m['text']}»" for m in msgs[-3:] if m["peer"])
        text = (f"🛒 {name}:\n{buyer_lines}\n\n✍️ جواب پیشنهادی:\n{d.reply}\n\n"
                f"وضعیت: {d.status} | قیمت ما: {notify.fmt(d.our_offer)}\n"
                "(برای متن دیگر، روی همین پیام Reply کنید و متن خودتان را بنویسید)")
        msg = notify.bale("sendMessage", chat_id=config.BALE_CHAT_ID, text=text, reply_markup=_buttons(draft.id))
        draft.bale_message_id = (msg or {}).get("message_id")
        pending[draft.id] = draft
        new += 1

    if new > 1:
        notify.bale("sendMessage", chat_id=config.BALE_CHAT_ID, text=f"{new} جواب منتظر تأیید است.",
                    reply_markup={"inline_keyboard": [[{"text": "✅ همه را بفرست", "callback_data": "sendall"}]]})
    log.info("divar check: %d new draft(s), %d pending", new, len(pending))


def send_draft(dc: DivarChat, draft: Draft, text: str | None = None) -> str:
    """Send one approved draft in Divar; returns a short status for the owner."""
    msgs = dc.messages(draft.conv_id)
    if _sig(draft.conv_id, msgs) != draft.sig:
        pending.pop(draft.id, None)
        return f"⏳ {draft.name} پیام تازه‌ای داده؛ جواب جدید آماده می‌کنم."
    reply = text or draft.decision.reply
    dc.send(draft.conv_id, reply)
    pending.pop(draft.id, None)

    conv = _conversation(draft.conv_id, msgs)
    d = draft.decision if not text else Decision(
        reply=text, status="negotiating", our_offer=rules.parse_price(text), buyer_offer=None,
        agreed_price=None, owner_note="متن خود فروشنده")
    apply(conv, d)
    store.save(conv)
    last_preview.pop(draft.conv_id, None)

    if d.status == "deal":
        notify.send_owner(f"✅ خریدار نهایی شد!\nخریدار: {draft.name}\nقیمت: {notify.fmt(conv.agreed_price)}\n"
                          "برای تحویل در دیوار هماهنگ کنید.")
    elif d.status == "needs_owner":
        notify.send_owner(f"❓ {draft.name} سؤالی دارد که فقط خودتان می‌توانید جواب بدهید؛ در دیوار ببینید.")
    return f"✅ برای {draft.name} فرستاده شد."


def _mark(draft: Draft, status: str):
    if draft.bale_message_id:
        try:
            notify.bale("editMessageReplyMarkup", chat_id=config.BALE_CHAT_ID,
                        message_id=draft.bale_message_id, reply_markup={"inline_keyboard": []})
        except (requests.RequestException, RuntimeError):
            pass
    notify.send_owner(status)


def handle_bale(dc: DivarChat, timeout: int):
    global bale_offset
    params = {"timeout": timeout}
    if bale_offset is not None:
        params["offset"] = bale_offset
    try:
        updates = notify.bale("getUpdates", **params) or []
    except (requests.RequestException, RuntimeError) as e:
        log.warning("bale getUpdates failed: %s", notify.redact(e))
        time.sleep(5)
        return

    for u in updates:
        bale_offset = u["update_id"] + 1
        cb = u.get("callback_query")
        msg = u.get("message")
        if cb and str(cb.get("message", {}).get("chat", {}).get("id")) == str(config.BALE_CHAT_ID):
            try:
                notify.bale("answerCallbackQuery", callback_query_id=cb["id"])
            except (requests.RequestException, RuntimeError):
                pass
            action, _, draft_id = cb.get("data", "").partition(":")
            if action == "sendall":
                for draft in list(pending.values()):
                    _mark(draft, send_draft(dc, draft))
            elif draft_id not in pending:
                notify.send_owner("این جواب دیگر معتبر نیست (یا قبلاً فرستاده شده).")
            elif action == "send":
                draft = pending[draft_id]
                _mark(draft, send_draft(dc, draft))
            elif action == "skip":
                draft = pending.pop(draft_id)
                _mark(draft, f"❌ جواب {draft.name} فرستاده نشد.")
        elif msg and str(msg.get("chat", {}).get("id")) == str(config.BALE_CHAT_ID):
            replied = (msg.get("reply_to_message") or {}).get("message_id")
            draft = next((d for d in pending.values() if d.bale_message_id and d.bale_message_id == replied), None)
            if draft and msg.get("text"):
                _mark(draft, send_draft(dc, draft, text=msg["text"]))
            elif msg.get("text") in ("/start", "/help", "/status"):
                notify.send_owner(f"ربات فعال است. {len(pending)} جواب منتظر تأیید.\n"
                                  f"کف قیمت: {notify.fmt(config.FLOOR_PRICE)}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not config.DIVAR_SESSION.exists():
        raise SystemExit("No Divar login yet: run divar_login.py first")
    deadline = time.time() + config.RUN_MINUTES * 60 if config.RUN_MINUTES else None
    dc = DivarChat(headless=True)
    notify.send_owner("🤖 دستیار فروش دیوار روشن شد.")
    try:
        next_check = 0.0
        while deadline is None or time.time() < deadline:
            if time.time() >= next_check:
                try:
                    check_divar(dc)
                    # Divar rotates its login tokens; save the newest so a crash never leaves a stale one
                    dc.context.storage_state(path=str(config.DIVAR_SESSION))
                except Exception as e:  # keep running through page hiccups
                    log.warning("divar check failed: %s", type(e).__name__)
                    if "login expired" in str(e):
                        notify.send_owner("⚠️ ورود به دیوار منقضی شده؛ divar_login.py را دوباره اجرا کنید.")
                        raise
                next_check = time.time() + config.POLL_SECONDS
            handle_bale(dc, timeout=max(1, min(20, int(next_check - time.time()))))
    finally:
        dc.close()


if __name__ == "__main__":
    main()
