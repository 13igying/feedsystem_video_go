#!/usr/bin/env python3
"""
UI 自动化演示：Playwright 驱动真实浏览器，模拟用户完整操作流程。

流程：打开首页 → 注册新用户 → 登录 → 浏览推荐页 → 切换热榜 →
      进入账号页 → 查看设置页 → 全程每步截图。

由 test_runner_server.py 以子进程方式调用，输出步骤日志 + 截图路径。
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

# 支持本地电脑远程运行：FRONTEND_URL 指向服务器前端地址
# 例：FRONTEND_URL=http://172.16.0.97:5173 python ui_demo.py
FRONTEND = os.environ.get("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")
SHOTS = Path(__file__).parent / "ui_shots"
SHOTS.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def shot(page, name: str) -> str:
    p = SHOTS / f"{name}.png"
    page.screenshot(path=str(p), full_page=False)
    log(f"📸 截图: {name}.png")
    return p.name


def main() -> int:
    user = f"uidemo_{uuid.uuid4().hex[:8]}"
    pwd = "Passw0rd!123"
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"name": name, "ok": ok, "detail": detail})
        log(f"{'✅' if ok else '❌'} {name} {detail}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.set_default_timeout(10000)

        # 1. 打开首页
        log("🌐 打开前端首页…")
        page.goto(FRONTEND, wait_until="networkidle")
        step("打开首页", page.title() != "", f"title={page.title()!r}")
        shot(page, "01_home")

        # 2. 进入注册页
        page.goto(f"{FRONTEND}/account/register", wait_until="networkidle")
        step("进入注册页", "/account/register" in page.url)
        shot(page, "02_register_page")

        # 3. 填写注册表单并提交（注意：侧边栏有搜索框，必须用 autocomplete 精确定位）
        page.locator("input[autocomplete='username']").fill(user)
        page.locator("input[autocomplete='new-password']").fill(pwd)
        shot(page, "03_register_filled")
        page.locator("button.primary", has_text="注册").click()
        page.wait_for_timeout(1500)
        ok = "/account/register" not in page.url  # 注册成功会跳转
        step("提交注册", ok, f"user={user}")
        shot(page, "04_register_done")

        # 4. 登录（若注册后未自动登录）
        page.goto(f"{FRONTEND}/account", wait_until="networkidle")
        if page.locator("input[autocomplete='username']").count() > 0:
            page.locator("input[autocomplete='username']").fill(user)
            page.locator("input[autocomplete='current-password']").fill(pwd)
            shot(page, "05_login_filled")
            # 页面有两个"登录"按钮（侧边栏 + 表单），用表单内的 primary 按钮精确匹配
            page.locator("button.primary", has_text="登录").click()
            page.wait_for_timeout(1500)
        # 登录成功后登录卡片消失，显示 @用户名 个人主页
        page.wait_for_timeout(500)
        logged = page.locator(".login-card").count() == 0 and page.locator(f"text=@{user}").count() > 0
        step("登录", logged, f"user={user}")
        shot(page, "06_after_login")

        # 5. 浏览推荐页
        page.goto(f"{FRONTEND}/", wait_until="networkidle")
        page.wait_for_timeout(1000)
        step("浏览推荐页", True, page.url)
        shot(page, "07_feed")

        # 6. 切换热榜
        page.get_by_role("link", name="热榜").click()
        page.wait_for_timeout(1200)
        step("切换热榜", "/hot" in page.url)
        shot(page, "08_hot")

        # 7. 账号页
        page.get_by_role("link", name="账号").click()
        page.wait_for_timeout(1200)
        step("进入账号页", "/account" in page.url)
        shot(page, "09_account")

        # 8. 设置页
        page.get_by_role("link", name="设置").click()
        page.wait_for_timeout(1200)
        step("进入设置页", "/settings" in page.url)
        shot(page, "10_settings")

        browser.close()

    result = {
        "user": user, "steps": steps,
        "passed": all(s["ok"] for s in steps),
        "shots": sorted(p.name for p in SHOTS.glob("*.png")),
    }
    (SHOTS / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    log(f"{'🎉 全部步骤通过' if result['passed'] else '⚠️ 有步骤失败'}，共 {len(steps)} 步")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())