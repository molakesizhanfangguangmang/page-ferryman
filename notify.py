"""Error notification adapter for Page Ferryman.

The Talebook injection stores this module's configuration in the data volume.
It never logs webhook URLs, Telegram tokens, or response bodies.
"""
import json
import os
import urllib.parse
import urllib.request

CONFIG = "/data/.reading-progress-bridge/notify.json"


def load():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"enabled": False, "type": "webhook", "url": "", "bot_token": "", "chat_id": ""}
    return {
        "enabled": bool(d.get("enabled", False)),
        "type": d.get("type", "webhook") if d.get("type") in ("webhook", "telegram") else "webhook",
        "url": str(d.get("url", "")),
        "bot_token": str(d.get("bot_token", "")),
        "chat_id": str(d.get("chat_id", "")),
    }


def save(data):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    clean = load()
    clean.update({k: data[k] for k in ("enabled", "type", "url", "bot_token", "chat_id") if k in data})
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG)


def _message(event):
    return "页渡者错误\n%s" % json.dumps(event, ensure_ascii=False, sort_keys=True)


def send(event):
    cfg = load()
    if not cfg["enabled"]:
        return False
    msg = _message(event)
    if cfg["type"] == "telegram":
        if not cfg["bot_token"] or not cfg["chat_id"]:
            return False
        url = "https://api.telegram.org/bot%s/sendMessage" % cfg["bot_token"]
        body = urllib.parse.urlencode({"chat_id": cfg["chat_id"], "text": msg}).encode()
    else:
        if not cfg["url"]:
            return False
        url = cfg["url"]
        body = json.dumps({"text": msg, "event": event}, ensure_ascii=False).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception:
        return False
