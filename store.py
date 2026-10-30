"""One JSON file per Divar conversation: the transcript and the negotiation state."""
import json
import threading
from dataclasses import asdict, dataclass, field

from config import DATA_DIR

_lock = threading.Lock()


@dataclass
class Conversation:
    id: str
    messages: list = field(default_factory=list)  # [{"from": "buyer"|"bot"|"owner", "text": ...}]
    status: str = "negotiating"  # negotiating | deal | not_interested | needs_owner
    lowest_offer: int | None = None  # lowest price the bot has said out loud
    best_buyer_offer: int | None = None
    agreed_price: int | None = None
    buyer_name: str = ""

    @property
    def closed(self):
        return self.status == "deal"


def _path(conv_id):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in conv_id)
    return DATA_DIR / f"{safe}.json"


def load(conv_id) -> Conversation:
    p = _path(conv_id)
    if p.exists():
        return Conversation(**json.loads(p.read_text(encoding="utf-8")))
    return Conversation(id=conv_id)


def all_conversations() -> list[Conversation]:
    if not DATA_DIR.exists():
        return []
    return [Conversation(**json.loads(p.read_text(encoding="utf-8"))) for p in sorted(DATA_DIR.glob("*.json"))]


def save(conv: Conversation):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        _path(conv.id).write_text(json.dumps(asdict(conv), ensure_ascii=False, indent=2), encoding="utf-8")
