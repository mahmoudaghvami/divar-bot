"""Negotiation without any AI: read the buyer's price, step down slowly, never below the floor.

Used when no AI provider is configured or the provider fails.
"""
import re

import config

STEP = 100_000
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫/", "01234567890123456789..")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
PRICE_WORDS = ("قیمت", "آخر", "تخفیف", "کمتر", "چند", "بیا پایین", "راه بیای", "میدی", "می‌دی", "میدین")
NO_WORDS = ("نمیخوام", "نمی‌خوام", "منصرف", "گرونه", "ممنون نه", "بیخیال")
YES_WORDS = ("قبول", "باشه", "اوکی", "ok", "حله", "میخرم", "می‌خرم", "معامله")


def parse_price(text: str) -> int | None:
    """Best guess at a toman price in a buyer message: «۲.۴»، «2/4 میلیون»، «2400»، «2,400,000»."""
    t = text.translate(FA_DIGITS).lower()
    t = re.sub(r"\d{1,2}:\d{2}", " ", t)  # clock times, «5:30»
    m = NUMBER.search(t)
    if not m:
        return None
    raw = m.group()
    value = float(raw.replace(",", "")) if raw.count(".") <= 1 else float(raw.replace(".", "").replace(",", ""))
    if "میلیون" in t or "ملیون" in t or value < 100:  # «2.4» or «۲ میلیون و ۴۰۰»
        value *= 1_000_000
        rest = NUMBER.findall(t[m.end():])
        if rest and "میلیون" in t[: m.end() + 12] and float(rest[0].replace(",", "")) < 1000:
            value += float(rest[0].replace(",", "")) * 1000
    elif value < 100_000:  # «2400» meaning thousand toman
        value *= 1000
    price = int(round(value, -4))
    # anything far from the asking price is not a price for this item («ساعت ۵»، «۴ تا سری»)
    return price if 0.3 * config.LIST_PRICE <= price <= 1.1 * config.LIST_PRICE else None


def decide(conv, text: str):
    from negotiator import Decision  # avoid a circular import

    floor, ours = config.FLOOR_PRICE, conv.lowest_offer or config.LIST_PRICE
    offer = parse_price(text)
    lowered = text.lower()

    if offer and offer >= ours:
        return Decision(reply=f"باشه، {offer:,} تومان قبوله. برای هماهنگی تحویل بهتون پیام می‌دم.",
                        status="deal", our_offer=offer, buyer_offer=offer, agreed_price=offer,
                        owner_note=f"خریدار {offer:,} را قبول کرد.")
    if not offer and conv.lowest_offer and any(w in lowered for w in YES_WORDS):
        return Decision(reply=f"عالیه، پس {ours:,} تومان. برای هماهنگی تحویل بهتون پیام می‌دم.",
                        status="deal", our_offer=ours, buyer_offer=ours, agreed_price=ours,
                        owner_note=f"خریدار آخرین قیمت ما ({ours:,}) را قبول کرد.")
    if any(w in lowered for w in NO_WORDS) and not offer:
        return Decision(reply=f"باشه، ممنون. اگه نظرتون عوض شد، آخرین قیمتم {ours:,} تومانه.",
                        status="not_interested", our_offer=ours, buyer_offer=None, agreed_price=None,
                        owner_note="خریدار منصرف شد.")

    if offer:
        nxt = max(floor, ours - STEP)
        if offer >= nxt:
            return Decision(reply=f"باشه، {offer:,} تومان قبوله. برای هماهنگی تحویل بهتون پیام می‌دم.",
                            status="deal", our_offer=offer, buyer_offer=offer, agreed_price=offer,
                            owner_note=f"با {offer:,} توافق شد.")
        if nxt == ours:
            reply = f"شرمنده، کمتر از {ours:,} تومان واقعاً نمی‌تونم. دستگاه اصل آلمان و سالمه و سری‌هاش هم هست."
        else:
            reply = f"{offer:,} خیلی کمه. اصل آلمان و کاملاً سالمه، سری‌هاش هم هست. نهایتاً {nxt:,} تومان."
        return Decision(reply=reply, status="negotiating", our_offer=nxt, buyer_offer=offer, agreed_price=None,
                        owner_note=f"خریدار {offer:,} داد، ما {nxt:,} گفتیم.")

    if any(w in lowered for w in PRICE_WORDS) or not conv.lowest_offer:
        return Decision(reply=f"سلام، قیمت {ours:,} تومانه. اصل آلمان، کاملاً سالم، با ۴ تا سری.",
                        status="negotiating", our_offer=ours, buyer_offer=None, agreed_price=None,
                        owner_note="قیمت را پرسید.")

    return Decision(reply="الان می‌پرسم و بهتون خبر می‌دم.", status="needs_owner", our_offer=None,
                    buyer_offer=None, agreed_price=None, owner_note="سؤالی پرسید که ربات جوابش را ندارد.")
