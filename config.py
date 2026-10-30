"""Settings, read from environment variables (or a .env file next to this one)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


def _int(name, default):
    return int(os.getenv(name) or default)  # empty (e.g. an unset GitHub secret) means default


# --- the item and the negotiation range (toman) ---
ITEM_TITLE = os.getenv("ITEM_TITLE", "ماشین اصلاح موزر ۱۴۰۰ اصل آلمان با سری کامل")
ITEM_DETAILS = os.getenv(
    "ITEM_DETAILS",
    "موزر مدل ۱۴۰۰ (Type 1400)، اصل و ساخت آلمان، مدل قدیمی زرشکی و سفید. "
    "کاملاً سالم و بدون هیچ ایرادی، تیغه سالم. همراه با ۴ عدد سری (شانهٔ راهنما). "
    "برقی سیمی ۲۲۰ ولت. کارکرده. تحویل حضوری در تهران.",
)
LIST_PRICE = _int("LIST_PRICE", 2_700_000)
FLOOR_PRICE = _int("FLOOR_PRICE", 2_100_000)  # never agree below this
SELLING_POINTS = os.getenv(
    "SELLING_POINTS",
    "نوی این دستگاه در دیوار تهران از حدود ۳.۹ میلیون شروع می‌شود؛ "
    "تیغهٔ نوی موزر ۱۴۰۰ به‌تنهایی حدود ۷۵۰ هزار تومان است؛ سری‌ها همراهش است.",
)

# --- AI provider: any OpenAI-compatible API (OpenAI, Gemini, Groq, OpenRouter) ---
# Leave AI_API_KEY empty to negotiate with fixed rules only (no AI, no cost).
AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL") or None  # None = OpenAI itself
AI_MODEL = os.getenv("AI_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.5")
# "low" for OpenAI reasoning models; empty for providers that reject the parameter
AI_REASONING_EFFORT = os.getenv("AI_REASONING_EFFORT", "" if AI_BASE_URL else "low")

# --- Bale messenger bot, for owner alerts ---
BALE_BOT_TOKEN = os.getenv("BALE_BOT_TOKEN", "")
BALE_CHAT_ID = os.getenv("BALE_CHAT_ID", "")

# --- where conversation state is kept ---
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).with_name("data")))

# --- Divar web (worker.py) ---
DIVAR_SESSION = Path(os.getenv("DIVAR_SESSION", Path(__file__).with_name("divar_session.json")))
AD_TITLE_MATCH = os.getenv("AD_TITLE_MATCH", "موزر")  # only chats on ads whose title contains this
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "msedge" if os.name == "nt" else "chrome")
POLL_SECONDS = _int("POLL_SECONDS", 60)
RUN_MINUTES = _int("RUN_MINUTES", 0)  # 0 = forever; GitHub Actions sets a limit per job
