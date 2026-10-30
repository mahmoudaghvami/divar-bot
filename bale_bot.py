"""Sales assistant in Bale: paste a buyer's Divar message, get the reply to send back.

    python bale_bot.py

Only the owner's chat (BALE_CHAT_ID) is answered. Messages:
    علی: قیمت آخر چند؟      a message from buyer «علی» (also makes him the active buyer)
    قیمت آخر چند؟           a message from the active buyer
    /buyer علی              switch the active buyer
    /said <text>            what you actually sent, if you changed the draft
    /list                   all buyers and where each one stands
    /reset علی              forget a buyer
"""
import logging
import re
import time

import requests

import config
import notify
import store
from negotiator import apply, decide

log = logging.getLogger("bale_bot")
ACTIVE_FILE = config.DATA_DIR / "_active.txt"
# "name: text"; no digits in the name, so "ساعت 5:30" stays a plain message
PREFIX = re.compile(r"^\s*([^:\n\d۰-۹]{1,30})\s*[:：]\s*(.+)$", re.S)

HELP = """\
سلام! پیام هر خریدار دیوار را این‌جا بفرستید تا جوابش را آماده کنم.

• «علی: قیمت آخر چند؟» ← پیام خریدار علی
• بعد از آن، پیام‌های بدون اسم مال همان خریدار است
• /buyer علی ← عوض‌کردن خریدار
• /said متن ← اگر جواب را تغییر دادید، متنی که واقعاً فرستادید
• /list ← وضعیت همهٔ خریدارها
• /reset علی ← پاک‌کردن یک خریدار

کف قیمت: {floor} — هیچ‌وقت پایین‌تر نمی‌روم.""".format(floor=notify.fmt(config.FLOOR_PRICE))

STATUS_LABEL = {
    "negotiating": "در حال چانه‌زنی",
    "deal": "✅ نهایی شد",
    "not_interested": "منصرف شد",
    "needs_owner": "❓ منتظر جواب شما",
}


def _conv_id(name):
    return "buyer-" + name.strip()


def _active():
    return ACTIVE_FILE.read_text(encoding="utf-8").strip() if ACTIVE_FILE.exists() else ""


def _set_active(name):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(name.strip(), encoding="utf-8")


def handle(text: str) -> list[str]:
    """Turn one owner message into the bot's answers (one Bale message each)."""
    text = text.strip()
    if text in ("/start", "/help"):
        return [HELP]

    if text.startswith("/buyer"):
        name = text[len("/buyer"):].strip()
        if not name:
            return ["اسم خریدار را بنویسید: /buyer علی"]
        _set_active(name)
        conv = store.load(_conv_id(name))
        return [f"خریدار فعال: {name} ({STATUS_LABEL[conv.status]})"]

    if text == "/list":
        convs = store.all_conversations()
        if not convs:
            return ["هنوز خریداری نیست."]
        lines = [
            f"• {c.id.removeprefix('buyer-')}: {STATUS_LABEL[c.status]} | "
            f"پیشنهاد ما {notify.fmt(c.lowest_offer)} | پیشنهاد او {notify.fmt(c.best_buyer_offer)}"
            for c in convs
        ]
        return ["\n".join(lines)]

    if text.startswith("/reset"):
        name = text[len("/reset"):].strip() or _active()
        path = store._path(_conv_id(name))
        if path.exists():
            path.unlink()
        return [f"گفتگو با {name} پاک شد."]

    name = _active()
    if text.startswith("/said"):
        sent = text[len("/said"):].strip()
        if not (name and sent):
            return ["بعد از /said متنی را که فرستادید بنویسید."]
        conv = store.load(_conv_id(name))
        if conv.messages and conv.messages[-1]["from"] == "bot":
            conv.messages[-1] = {"from": "owner", "text": sent}
        else:
            conv.messages.append({"from": "owner", "text": sent})
        store.save(conv)
        return [f"ثبت شد که به {name} این را فرستادید."]

    if text.startswith("/"):
        return ["این دستور را نمی‌شناسم. /help"]

    m = PREFIX.match(text)
    if m:
        name, text = m.group(1).strip(), m.group(2).strip()
        _set_active(name)
    if not name:
        return ["اول اسم خریدار را بنویسید، مثلاً «علی: سلام قیمت آخر؟»"]

    conv = store.load(_conv_id(name))
    if conv.closed:
        return [f"معامله با {name} به قیمت {notify.fmt(conv.agreed_price)} نهایی شده. "
                f"برای شروع دوباره: /reset {name}"]

    conv.messages.append({"from": "buyer", "text": text})
    d = decide(conv)
    apply(conv, d)
    store.save(conv)

    out = [d.reply, f"↑ جواب برای {name} | {STATUS_LABEL[d.status]} | {d.owner_note}"]
    if d.status == "deal":
        out.append(f"✅ خریدار نهایی شد!\nخریدار: {name}\nقیمت: {notify.fmt(conv.agreed_price)}\n"
                   "جواب بالا را بفرستید و برای تحویل هماهنگ کنید.")
    elif d.status == "needs_owner":
        out.append(f"❓ {name} سؤالی پرسیده که جوابش را ندارم:\n«{text}»\n"
                   "خودتان جوابش را در دیوار بدهید و بعد با /said ثبتش کنید.")
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (config.BALE_BOT_TOKEN and config.BALE_CHAT_ID):
        raise SystemExit("BALE_BOT_TOKEN and BALE_CHAT_ID must be set in .env")
    me = notify.bale("getMe")
    log.info("running as @%s; answering only chat %s", me.get("username"), config.BALE_CHAT_ID)

    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            updates = notify.bale("getUpdates", **params) or []
        except (requests.RequestException, RuntimeError) as e:
            log.warning("getUpdates failed: %s", notify.redact(e))
            time.sleep(5)
            continue

        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text")
            if not text or chat_id != str(config.BALE_CHAT_ID):
                continue
            try:
                answers = handle(text)
            except Exception:
                log.exception("failed to handle %r", text)
                answers = ["خطایی پیش آمد (احتمالاً اتصال به ChatGPT). دوباره بفرستید."]
            for a in answers:
                notify.bale("sendMessage", chat_id=chat_id, text=a)
        if not updates:
            time.sleep(1)


if __name__ == "__main__":
    main()
