#!/usr/bin/env python3
"""Inject Page Ferryman notification settings into a Talebook v26 backend/frontend.

Usage: settings_patch.py <talebook-root> [--unpatch]
It edits only the copied source tree. install.sh performs backup and syntax checks.
"""
import os
import re
import sys

MARK = "# page-ferryman notification settings"
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
UNPATCH = "--unpatch" in sys.argv
ADMIN = os.path.join(ROOT, "webserver", "handlers", "admin.py")
INDEX = os.path.join(ROOT, "app", "dist", "index.html")

PY = r'''
# page-ferryman notification settings
class PageFerrymanNotify(BaseHandler):
    @js
    @auth
    def get(self):
        if not self.admin_user:
            return {"err": "permission"}
        from pathlib import Path
        p = Path("/data/.reading-progress-bridge/notify.json")
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            d = {"enabled": False, "type": "webhook", "url": "", "bot_token": "", "chat_id": ""}
        if d.get("bot_token"):
            d["bot_token"] = "***" + d["bot_token"][-4:]
        return {"err": "ok", "settings": d}

    @js
    @auth
    def post(self):
        if not self.admin_user:
            return {"err": "permission"}
        data = tornado.escape.json_decode(self.request.body)
        typ = data.get("type", "webhook")
        if typ not in ("webhook", "telegram"):
            return {"err": "params.type"}
        from pathlib import Path
        p = Path("/data/.reading-progress-bridge/notify.json")
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            old = {}
        token = data.get("bot_token", "")
        if token.startswith("***"):
            token = old.get("bot_token", "")
        d = {"enabled": bool(data.get("enabled")), "type": typ,
             "url": str(data.get("url", "")), "bot_token": str(token),
             "chat_id": str(data.get("chat_id", ""))}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"err": "ok"}

    @js
    @auth
    def put(self):
        if not self.admin_user:
            return {"err": "permission"}
        from page_ferryman_notify import send
        data = tornado.escape.json_decode(self.request.body)
        return {"err": "ok" if send({"kind": "test", "message": data.get("message", "页渡者测试消息")}) else "notify_failed"}
'''

def patch():
    s = open(ADMIN, encoding="utf-8").read()
    if UNPATCH:
        s = re.sub(r"\n" + re.escape(MARK) + r".*?\n\n(?=def _build_mysql_url)", "\n", s, flags=re.S)
        open(ADMIN, "w", encoding="utf-8").write(s)
        if os.path.isfile(INDEX):
            html = open(INDEX, encoding="utf-8").read()
            html = html.replace('<script src="/static/page-ferryman-notify.js"></script>', '')
            open(INDEX, "w", encoding="utf-8").write(html)
        return
    if MARK in s:
        return
    if "class AdminSettings(BaseHandler):" not in s or "(r\"/api/admin/settings\", AdminSettings)" not in s:
        raise SystemExit("Talebook admin.py 锚点不匹配")
    s = s.replace("import tornado", "import tornado\nimport json", 1)
    s = s.replace("\n\ndef _build_mysql_url", "\n\n" + PY + "\n\ndef _build_mysql_url", 1)
    s = s.replace('(r"/api/admin/settings", AdminSettings),', '(r"/api/admin/settings", AdminSettings),\n        (r"/api/page-ferryman/notify", PageFerrymanNotify),', 1)
    open(ADMIN, "w", encoding="utf-8").write(s)
    if os.path.isfile(INDEX):
        html = open(INDEX, encoding="utf-8").read()
        if '/static/page-ferryman-notify.js' not in html:
            html = html.replace('</body>', '<script src="/static/page-ferryman-notify.js"></script></body>')
        open(INDEX, "w", encoding="utf-8").write(html)

patch()
print("unpatched" if UNPATCH else "patched")
