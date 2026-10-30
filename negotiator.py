"""Price negotiation with a Divar buyer, written by an AI model, guarded by hard rules in code.

The model drafts the reply and reports the prices in it; the code makes sure the bot
never names or accepts a price below FLOOR_PRICE and never goes back up after a concession.
Without an AI key, or when the provider fails, the fixed rules in rules.py answer instead.
"""
import json
import logging
import re
from typing import Literal

import openai
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

import config
import rules
from store import Conversation

log = logging.getLogger(__name__)
_client = None


def _openai():
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_BASE_URL)
    return _client


SYSTEM_PROMPT = f"""\
تو از طرف فروشندهٔ یک کالا در دیوار، در چت با خریدارها صحبت می‌کنی. فارسی محاوره‌ای، مؤدب و کوتاه بنویس (یک تا سه جمله)، مثل یک فروشندهٔ معمولی دیوار.

کالا: {config.ITEM_TITLE}
مشخصات: {config.ITEM_DETAILS}
قیمت آگهی: {config.LIST_PRICE:,} تومان
نکته‌هایی که می‌توانی برای دفاع از قیمت بگویی: {config.SELLING_POINTS}

قواعد چانه‌زنی:
- هدف: فروش با بیشترین قیمت ممکن. کف قیمت محرمانه است و هرگز آن را نگو و زیر آن قیمت نده و قبول نکن.
- اول از قیمت آگهی دفاع کن. تخفیف را آهسته و پله‌ای بده (هر بار حداکثر حدود ۱۰۰ هزار تومان) و فقط وقتی خریدار جدی است.
- قیمتی که یک بار گفته‌ای را دوباره بالا نبر.
- اگر خریدار قیمتی بالاتر یا مساوی پیشنهاد آخر تو گفت، یا به قیمتی بالاتر از کف رسیدید و خریدار قبول کرد، معامله نهایی است (status = deal). در این حالت به خریدار بگو فروشنده برای هماهنگی تحویل خودش پیام می‌دهد.
- اگر خریدار فقط قیمت پرسید یا هنوز پیشنهاد نداده، status = negotiating.
- اگر خریدار صریحاً منصرف شد یا پیشنهادش خیلی پایین است و کوتاه نمی‌آید، مؤدبانه آخرین قیمتت را بگو و status = not_interested.
- اگر سؤالی پرسید که جوابش در مشخصات نیست (مثلاً آدرس دقیق، زمان دقیق بازدید، ارسال با پیک، عکس بیشتر)، قول نده و چیزی از خودت نساز؛ بگو «چند دقیقه دیگه خبرتون می‌کنم» (نگو از کسی می‌پرسی) و status = needs_owner.
- دربارهٔ کالا فقط چیزهایی را بگو که در «مشخصات» بالا آمده. هیچ ادعای فنی (نوع موتور، قدرت، دوام، گارانتی) یا قولی از خودت نساز و اغراق نکن؛ اگر جوابش در مشخصات نیست، status = needs_owner.
- شماره تلفن، آدرس دقیق یا اطلاعات شخصی فروشنده را نده.
- نگو که ربات یا هوش مصنوعی هستی مگر مستقیم بپرسند؛ اگر پرسیدند، صادقانه بگو دستیار فروشنده هستی.
- قیمت‌ها را به تومان و با عدد بنویس.

our_offer: قیمتی که در همین پاسخ به خریدار می‌گویی (اگر قیمتی نگفتی null).
buyer_offer: آخرین قیمتی که خریدار پیشنهاد داده (اگر نداده null).
agreed_price: فقط وقتی status = deal، قیمت نهایی توافق‌شده.
owner_note: یک جملهٔ کوتاه برای فروشنده که وضعیت این گفتگو را خلاصه کند.
"""


class Decision(BaseModel):
    reply: str = Field(description="متن پیام به خریدار")
    status: Literal["negotiating", "deal", "not_interested", "needs_owner"]
    our_offer: int | None
    buyer_offer: int | None
    agreed_price: int | None
    owner_note: str


def _transcript(conv: Conversation) -> str:
    names = {"buyer": "خریدار", "bot": "فروشنده", "owner": "فروشنده"}
    lines = [f"{names[m['from']]}: {m['text']}" for m in conv.messages]
    state = (
        f"کمترین قیمتی که تا حالا به این خریدار گفته‌ای: {conv.lowest_offer:,} تومان"
        if conv.lowest_offer
        else "هنوز تخفیفی نداده‌ای."
    )
    return "گفتگو تا اینجا:\n" + "\n".join(lines) + f"\n\n{state}\nپاسخ بعدی فروشنده را بنویس."


_strict_schema_ok = True  # flips off if the provider rejects json_schema output


def _ask(conv: Conversation, extra: str = "") -> Decision:
    global _strict_schema_ok
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _transcript(conv) + extra},
    ]
    kwargs = {"model": config.AI_MODEL, "messages": messages}
    if config.AI_REASONING_EFFORT:
        kwargs["reasoning_effort"] = config.AI_REASONING_EFFORT

    if _strict_schema_ok:
        try:
            msg = _openai().chat.completions.parse(response_format=Decision, **kwargs).choices[0].message
            if msg.parsed is None:
                raise RuntimeError(f"model returned no decision (refusal: {msg.refusal!r})")
            return msg.parsed
        except openai.BadRequestError as e:
            log.warning("provider rejected json_schema output, using plain JSON instead: %s", e)
            _strict_schema_ok = False

    # providers/models without structured outputs: ask for JSON in the prompt and validate it
    schema = json.dumps(Decision.model_json_schema(), ensure_ascii=False)
    messages[0] = {"role": "system", "content": SYSTEM_PROMPT + "\nفقط یک شیء JSON با این ساختار برگردان:\n" + schema}
    text = _openai().chat.completions.create(**kwargs).choices[0].message.content or ""
    match = re.search(r"\{.*\}", text, re.S)
    return Decision.model_validate_json(match.group() if match else text)


def _violations(d: Decision, conv: Conversation) -> list[str]:
    floor = config.FLOOR_PRICE
    problems = []
    if d.our_offer is not None and d.our_offer < floor:
        problems.append("قیمتی که گفتی از حداقل مجاز پایین‌تر است.")
    if d.our_offer is not None and conv.lowest_offer and d.our_offer > conv.lowest_offer:
        problems.append(f"قبلاً {conv.lowest_offer:,} گفته‌ای؛ قیمت را بالا نبر.")
    if d.status == "deal" and (d.agreed_price is None or d.agreed_price < floor):
        problems.append("این قیمت برای معامله قابل قبول نیست.")
    return problems


def _rules(conv: Conversation, why: str) -> Decision:
    d = rules.decide(conv, conv.messages[-1]["text"])
    d.owner_note = f"{d.owner_note} ({why})"
    return d


def decide(conv: Conversation) -> Decision:
    """Draft the next reply for this conversation, retrying once if it breaks a hard rule."""
    if not config.AI_API_KEY:
        return _rules(conv, "بدون هوش مصنوعی")
    try:
        d = _ask(conv)
        problems = _violations(d, conv)
        if problems:
            log.info("conversation %s: redrafting (%s)", conv.id, " ".join(problems))
            d = _ask(conv, "\n\nتوجه: پیش‌نویس قبلی ایراد داشت: " + " ".join(problems))
    except (openai.OpenAIError, ValidationError, RuntimeError, json.JSONDecodeError) as e:
        log.warning("AI provider failed, answering with fixed rules: %s", e)
        return _rules(conv, "هوش مصنوعی در دسترس نبود")
    if _violations(d, conv):
        # still broken: hold at the last price we already named (or the list price)
        hold = conv.lowest_offer or config.LIST_PRICE
        d = Decision(
            reply=f"شرمنده، کمتر از {hold:,} تومان واقعاً برام نمی‌صرفه.",
            status="negotiating",
            our_offer=hold,
            buyer_offer=d.buyer_offer,
            agreed_price=None,
            owner_note="ربات روی آخرین قیمت ایستاد.",
        )
    return d


def apply(conv: Conversation, d: Decision):
    """Record the decision in the conversation state."""
    conv.messages.append({"from": "bot", "text": d.reply})
    if d.our_offer:
        conv.lowest_offer = min(conv.lowest_offer or d.our_offer, d.our_offer)
    if d.buyer_offer:
        conv.best_buyer_offer = max(conv.best_buyer_offer or 0, d.buyer_offer)
    conv.status = d.status
    if d.status == "deal":
        conv.agreed_price = d.agreed_price
