#!/usr/bin/env python3
"""
轻量级 Web 测试运行器（仅用 Python 标准库，零额外依赖）。

特点：流式实时输出 —— 测试每执行完一条用例，浏览器立即看到该行结果。

在服务器上启动：
    cd /root/feedsystem_video_go
    nohup python3 tests/test_runner_server.py >/tmp/testrunner.log 2>&1 &

然后在本地浏览器打开 http://localhost:8081 （或隧道映射的本地端口）。
"""
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST, PORT = "0.0.0.0", 8081
ROOT = "/root/feedsystem_video_go"
PYTEST = f"{ROOT}/tests/.venv/bin/pytest"

TARGETS = {
    "all": ("全部用例（26 个）", ["tests/api/"]),
    "account": ("账号模块 test_account", ["tests/api/test_account.py"]),
    "feed": ("Feed 模块 test_feed", ["tests/api/test_feed.py"]),
    "social": ("社交模块 test_social", ["tests/api/test_social.py"]),
}

# UI 演示模式：Playwright 驱动真实浏览器，逐步截图
UI_SHOTS = f"{ROOT}/tests/ui_shots"
UI_DEMO_CMD = [f"{ROOT}/tests/.venv/bin/python", f"{ROOT}/tests/ui_demo.py"]

_lock = threading.Lock()
state = {
    "running": False, "output": "", "exit": None, "target": None,
    "target_label": None, "started_at": None, "finished_at": None,
    "duration": None, "elapsed": 0.0, "done": 0, "total": 0,
}


def _count_tests(paths) -> int:
    """用 pytest --collect-only -q 预先统计用例数（用于进度显示）。"""
    try:
        p = subprocess.run(
            [PYTEST, *paths, "--collect-only", "-q", "--no-header"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        # 优先解析统计行："26 tests collected in 0.05s"
        import re
        m = re.search(r"(\d+) tests? collected", p.stdout or "")
        if m:
            return int(m.group(1))
        # 兜底：数 <Function ...> 行
        return len(re.findall(r"<Function ", p.stdout or ""))
    except Exception:
        return 0


def _run(key: str) -> None:
    _, paths = TARGETS[key]
    cmd = [PYTEST, *paths, "-v", "--tb=short", "--capture=no", "-p", "no:cacheprovider"]
    total = _count_tests(paths)
    t0 = time.time()
    buf: list[str] = []

    def _append(text: str, done_delta: int = 0) -> None:
        buf.append(text)
        with _lock:
            state["output"] = "".join(buf)
            state["elapsed"] = round(time.time() - t0, 1)
            state["done"] = min(state["done"] + done_delta, state["total"])

    with _lock:
        state.update(
            running=True, output="", exit=None, target=key,
            target_label=TARGETS[key][0],
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=None, duration=None, elapsed=0.0,
            done=0, total=total,
        )
    _append(f"$ pytest {' '.join(paths)} -v\n（共 {total} 个用例，实时输出如下）\n\n")

    code = 0
    try:
        proc = subprocess.Popen(
            cmd, cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            # -v 模式下，形如 "tests/api/test_x.py::TestY::test_z PASSED" 的行代表一条用例完成
            done_delta = 1 if ("PASSED" in line or "FAILED" in line or "ERROR" in line or "SKIPPED" in line) else 0
            _append(line, done_delta)
        proc.wait()
        code = proc.returncode or 0
    except subprocess.TimeoutExpired:
        _append("\n!! 执行超时（300s），已终止\n")
        code = -1
    except Exception as e:  # noqa: BLE001
        _append(f"\n!! 运行器异常: {e}\n")
        code = -2

    _append(f"\n{'=' * 60}\n结束：退出码 {code}，总耗时 {round(time.time() - t0, 1)}s\n")
    with _lock:
        state.update(
            running=False, exit=code,
            finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            duration=round(time.time() - t0, 1),
            elapsed=round(time.time() - t0, 1),
        )


def _run_ui_demo() -> None:
    """运行 UI 自动化演示，实时输出步骤日志。"""
    t0 = time.time()
    buf: list[str] = []

    def _append(text: str) -> None:
        buf.append(text)
        with _lock:
            state["output"] = "".join(buf)
            state["elapsed"] = round(time.time() - t0, 1)

    with _lock:
        state.update(
            running=True, output="", exit=None, target="ui",
            target_label="UI 自动化演示（浏览器直播）",
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=None, duration=None, elapsed=0.0,
            done=0, total=8,
        )
    _append("🎬 UI 自动化演示启动：Playwright 无头浏览器\n流程：首页→注册→登录→推荐→热榜→账号→设置\n每步自动截图，见下方图片墙。\n\n")

    code = 0
    try:
        proc = subprocess.Popen(
            UI_DEMO_CMD, cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _append(line)
            with _lock:
                if "✅" in line or "❌" in line:
                    state["done"] = min(state["done"] + 1, state["total"])
        proc.wait()
        code = proc.returncode or 0
    except Exception as e:  # noqa: BLE001
        _append(f"\n!! UI 演示异常: {e}\n")
        code = -2

    _append(f"\n{'=' * 60}\n结束：退出码 {code}，总耗时 {round(time.time() - t0, 1)}s\n")
    with _lock:
        state.update(
            running=False, exit=code,
            finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            duration=round(time.time() - t0, 1),
            elapsed=round(time.time() - t0, 1),
        )


def start(key: str) -> bool:
    with _lock:
        if state["running"]:
            return False
        if key == "ui":
            threading.Thread(target=_run_ui_demo, daemon=True).start()
            return True
        if key not in TARGETS:
            return False
    threading.Thread(target=_run, args=(key,), daemon=True).start()
    return True


PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>feedsystem 测试运行器</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;background:#0d1117;color:#c9d1d9}
 h1{font-size:20px} button{margin:4px;padding:10px 18px;font-size:15px;border:0;border-radius:6px;background:#238636;color:#fff;cursor:pointer}
 button:disabled{background:#30363d;color:#8b949e;cursor:not-allowed}
 pre{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;min-height:380px;max-height:65vh;overflow-y:auto;white-space:pre-wrap;font-size:13px;line-height:1.5}
 .meta{color:#8b949e;font-size:13px;margin:8px 0}
 .bar{height:10px;background:#21262d;border-radius:5px;overflow:hidden;margin:6px 0}
 .bar>div{height:100%;background:#3fb950;width:0%;transition:width .4s}
 a{color:#58a6ff}
 .live{color:#f85149;font-weight:bold}
</style></head><body>
<h1>🧪 feedsystem_video_go 测试运行器 <span class="live" id="live" style="display:none">● LIVE</span></h1>
<div class="meta">在服务器上远程执行 pytest，实时逐条显示用例执行过程。前端体验：<a id="felink" href="#" target="_blank"></a></div>
<div>
 <button onclick="run('all')">▶ 全部用例</button>
 <button onclick="run('account')">账号模块</button>
 <button onclick="run('feed')">Feed 模块</button>
 <button onclick="run('social')">社交模块</button>
 <button onclick="run('ui')" style="background:#8957e5">🎬 UI 自动化演示</button>
</div>
<div id="gallery" style="display:none">
 <h2 style="font-size:16px;margin:16px 0 8px">📸 UI 演示截图墙（浏览器自动操作的每一步）</h2>
 <div id="shots" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px"></div>
</div>
<div class="meta" id="meta"></div>
<div class="bar"><div id="bar"></div></div>
<pre id="out">点击上方按钮开始运行，下方将实时滚动显示每条用例的执行结果…</pre>
<script>
let timer=null;
const fePort = (location.port === '18081') ? '15173' : '5173';
const feUrl = 'http://' + location.hostname + ':' + fePort;
const felink = document.getElementById('felink');
felink.href = feUrl; felink.textContent = feUrl;
const out=document.getElementById('out'), meta=document.getElementById('meta'),
      bar=document.getElementById('bar'), live=document.getElementById('live');
let lastLen=-1;
async function refresh(){
  const s=await (await fetch('/status')).json();
  if(s.output.length!==lastLen){
    const stick = out.scrollTop + out.clientHeight >= out.scrollHeight - 30;
    out.textContent=s.output;
    if(stick) out.scrollTop=out.scrollHeight;
    lastLen=s.output.length;
  }
  let m=[];
  if(s.running){
    m.push('⏳ 正在执行：'+(s.target_label||''));
    if(s.total>0) m.push('进度 '+s.done+'/'+s.total);
    m.push('已用时 '+s.elapsed+'s');
    live.style.display='inline';
  }else{
    live.style.display='none';
    if(s.exit!==null){
      m.push((s.exit===0?'✅ 全部通过':'❌ 存在失败')+'，退出码 '+s.exit+'，总耗时 '+s.duration+'s，完成于 '+s.finished_at);
    }
  }
  if(s.started_at) m.push('开始于 '+s.started_at);
  meta.textContent=m.join(' ｜ ');
  bar.style.width = s.total>0 ? Math.round(100*s.done/s.total)+'%' : (s.running?'5%':'0%');
  document.querySelectorAll('button').forEach(b=>b.disabled=!!s.running);
  if(!s.running&&timer){clearInterval(timer);timer=null;refresh();}
}
async function run(t){
  const r=await fetch('/run?target='+t,{method:'POST'});
  if(!r.ok){alert(await r.text());return;}
  lastLen=-1;
  if(t==='ui'){document.getElementById('gallery').style.display='block';}
  if(!timer)timer=setInterval(refresh,600);
  refresh();
}
async function loadShots(){
  try{
    const s=await (await fetch('/shots')).json();
    const box=document.getElementById('shots');
    box.innerHTML=s.shots.map(f=>`<figure style="margin:0"><img src="/shot/${f}" style="width:100%;border:1px solid #30363d;border-radius:6px"><figcaption style="font-size:12px;color:#8b949e;padding:4px 2px">${f}</figcaption></figure>`).join('');
  }catch(e){}
}
setInterval(()=>{ if(document.getElementById('gallery').style.display!=='none') loadShots(); },2000);
refresh();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif u.path == "/status":
            with _lock:
                self._send(200, json.dumps(state).encode(), "application/json")
        elif u.path == "/shots":
            # 返回截图列表 + result.json 摘要
            import os
            shots = sorted(f for f in os.listdir(UI_SHOTS) if f.endswith(".png")) if os.path.isdir(UI_SHOTS) else []
            summary = {}
            try:
                summary = json.load(open(f"{UI_SHOTS}/result.json"))
            except Exception:
                pass
            self._send(200, json.dumps({"shots": shots, **summary}).encode(), "application/json")
        elif u.path.startswith("/shot/"):
            # 返回单张截图
            fn = u.path[len("/shot/"):]
            if "/" not in fn and fn.endswith(".png"):
                try:
                    with open(f"{UI_SHOTS}/{fn}", "rb") as f:
                        self._send(200, f.read(), "image/png")
                    return
                except FileNotFoundError:
                    pass
            self._send(404, b"not found", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/run":
            key = (parse_qs(u.query).get("target") or ["all"])[0]
            if start(key):
                self._send(200, b"started", "text/plain")
            elif state.get("running"):
                self._send(409, b"a run is already in progress", "text/plain")
            else:
                self._send(400, b"bad target", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *a):  # 静默访问日志
        pass


if __name__ == "__main__":
    print(f"test runner listening on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()