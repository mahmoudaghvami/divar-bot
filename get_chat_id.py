"""Print the chat id of whoever last messaged your Bale bot (send it any message first)."""
import config
import notify

if not config.BALE_BOT_TOKEN:
    raise SystemExit("Put BALE_BOT_TOKEN in .env first")
updates = notify.bale("getUpdates") or []
chats = {(str(u["message"]["chat"]["id"]), u["message"]["chat"].get("first_name", "")) for u in updates if "message" in u}
if not chats:
    print("No messages yet. Send your bot any message in Bale, then run this again.")
for chat_id, name in chats:
    print(f"BALE_CHAT_ID={chat_id}   ({name})")
