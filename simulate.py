"""Play the buyer in the terminal to try the negotiation before connecting to Divar.

    python simulate.py            # new conversation
    python simulate.py test-2     # another conversation id
"""
import sys

import notify
import store
from negotiator import apply, decide

conv = store.Conversation(id=sys.argv[1] if len(sys.argv) > 1 else "simulated")
print("You are the buyer. Empty line to quit.\n")
while not conv.closed:
    text = input("buyer> ").strip()
    if not text:
        break
    conv.messages.append({"from": "buyer", "text": text})
    d = decide(conv)
    apply(conv, d)
    print(f"bot>   {d.reply}")
    print(f"       [{d.status} | ours={d.our_offer} buyer={d.buyer_offer} | {d.owner_note}]\n")

if conv.status == "deal":
    notify.send_owner(f"✅ خریدار نهایی شد (شبیه‌سازی)\nقیمت: {notify.fmt(conv.agreed_price)}")
elif conv.status == "needs_owner":
    notify.send_owner(f"❓ خریدار سؤالی دارد (شبیه‌سازی)\n{conv.messages[-2]['text']}")
