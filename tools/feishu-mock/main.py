"""飞书 Webhook 模拟器。

接收 Bug 平台发出的飞书通知（POST JSON），在内存中保存并提供网页查看。
用于本地/演示环境模拟"飞书群机器人"的行为，无需真实飞书配置。

用法：
  python main.py            # 监听 0.0.0.0:9000
  PORT=9001 python main.py  # 自定义端口

接口：
  POST /webhook   接收通知（兼容飞书自定义机器人协议，返回 {"code":0}）
  GET  /          通知列表页面（实时刷新）
  GET  /messages  JSON 格式通知列表
  GET  /clear     清空通知并回到首页
"""
import html
import json
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
MESSAGES = []  # 新的通知插在最前
MAX_KEEP = 200

PORT = int(os.environ.get("PORT", "9000"))

PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>飞书通知模拟器</title>
<meta http-equiv="refresh" content="5">
<style>
  body {{ font-family: system-ui, sans-serif; background: #0e1117; color: #e6edf5;
         max-width: 860px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 20px; }} h1 small {{ color: #8b98ab; font-size: 13px; font-weight: 400; }}
  .bar {{ display: flex; gap: 8px; margin: 12px 0 16px; }}
  .bar a {{ color: #58a6ff; text-decoration: none; font-size: 14px;
            border: 1px solid #2b3a4d; border-radius: 6px; padding: 4px 10px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ border-bottom: 1px solid #21293a; padding: 10px 8px; vertical-align: top; }}
  .t {{ color: #8b98ab; white-space: nowrap; width: 90px; font-size: 13px; }}
  pre {{ white-space: pre-wrap; word-break: break-all; margin: 0;
         font-family: inherit; font-size: 14px; line-height: 1.6; }}
  .empty {{ color: #8b98ab; text-align: center; padding: 40px 0; }}
</style>
</head>
<body>
<h1>📨 飞书通知模拟器 <small>（模拟飞书群机器人收到的消息，5 秒自动刷新）</small></h1>
<div class="bar">
  <a href="/clear">清空</a>
  <a href="/messages" target="_blank">JSON</a>
</div>
<table>{rows}</table>
</body>
</html>"""


def render_rows() -> str:
    with LOCK:
        items = list(MESSAGES)
    if not items:
        return '<tr><td colspan="2" class="empty">暂无通知 —— 去 Bug 平台提交一个 Bug，通知会出现在这里</td></tr>'
    rows = []
    for m in items:
        text = m["body"]
        # 尝试解析飞书消息体，提取 text 字段更易读
        try:
            data = json.loads(m["body"])
            text = data.get("content", {}).get("text") or m["body"]
        except (ValueError, AttributeError):
            pass
        rows.append(
            f'<tr><td class="t">{html.escape(m["time"])}</td>'
            f"<td><pre>{html.escape(text)}</pre></td></tr>"
        )
    return "\n".join(rows)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静默默认访问日志
        pass

    def _json(self, payload: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "path": self.path, "body": body}
        with LOCK:
            MESSAGES.insert(0, entry)
            del MESSAGES[MAX_KEEP:]
        print(f"[feishu-mock] {entry['time']} 收到通知: {body[:200]}", flush=True)
        self._json(b'{"code":0,"msg":"success"}')

    def do_GET(self):
        if self.path == "/messages":
            with LOCK:
                payload = json.dumps(MESSAGES, ensure_ascii=False, indent=2).encode()
            self._json(payload)
            return
        if self.path == "/clear":
            with LOCK:
                MESSAGES.clear()
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return
        page = PAGE.format(rows=render_rows()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


if __name__ == "__main__":
    print(f"[feishu-mock] 飞书通知模拟器已启动: http://0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()