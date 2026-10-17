"""飞书 open_id 获取助手（FEISHU_AT_MAP 配套工具）。

Bug 平台要「真 @」指定成员，需要每个成员的飞书 open_id（ou_ 开头）。
自定义机器人无法查询成员 ID，需借助一个企业自建应用（只需配置一次）：

  1. https://open.feishu.cn/app 创建企业自建应用，拿到 App ID / App Secret；
  2. 应用详情 → 添加应用能力 → 机器人；
  3. 权限管理 → 开通「获取群信息」（im:chat:readonly）；
  4. 创建版本并发布（可用范围含自己即可），再把应用机器人拉进 Bug 通知群；
  5. 运行本脚本：python tools/feishu_openids.py
     （App ID/Secret 也可用环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET 提供）

脚本自动列出该应用机器人所在群及群成员 open_id，并生成可直接粘贴进服务器
.env 的 FEISHU_AT_MAP 行。注意：key 为飞书昵称，若与平台注册用户名不一致，
请把 key 改成 Bug 卡片「提交人」字段显示的名字（必须完全一致）。

用法：
  python tools/feishu_openids.py                # 按提示交互
  FEISHU_APP_ID=cli_xxx FEISHU_APP_SECRET=xxx python tools/feishu_openids.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://open.feishu.cn/open-apis"


def http_json(method, path, token=None, body=None, params=None):
    """调用飞书开放 API，统一返回 dict（失败也返回 {"code":..,"msg":..}，不抛异常）。"""
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"code": -1, "msg": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"}
    except urllib.error.URLError as e:
        return {"code": -2, "msg": f"网络错误: {e.reason}（检查本机能否访问 open.feishu.cn）"}


# 常见业务错误码 → 可操作的修复提示（与文档「飞书真 @ 通知」章节对应）
HINTS = {
    99991672: "权限不足：开发者后台 → 权限管理 开通「获取群信息」（im:chat:readonly），"
              "创建新版本并发布后重试",
    99991661: "tenant_access_token 获取失败：检查 App ID / App Secret 是否复制完整",
    99991663: "tenant_access_token 获取失败：检查 App ID / App Secret 是否复制完整",
    10003: "App ID 或 App Secret 不正确（或应用不属于该租户），请到 开发者后台 → 凭证与基础信息 重新复制",
}


def fail(resp, step):
    print(f"\n[错误] {step} 失败: code={resp.get('code')} msg={resp.get('msg', '')}")
    hint = HINTS.get(resp.get("code"))
    if hint:
        print(f"[提示] {hint}")
    sys.exit(1)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台中文输出
    except Exception:
        pass

    app_id = os.environ.get("FEISHU_APP_ID") or input("请输入自建应用 App ID: ").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET") or input("请输入 App Secret: ").strip()
    if not app_id or not app_secret:
        print("App ID / App Secret 不能为空")
        sys.exit(1)

    # ① 应用身份凭证（企业自建应用专用接口）
    tok = http_json("POST", "/auth/v3/tenant_access_token/internal",
                    body={"app_id": app_id, "app_secret": app_secret})
    if tok.get("code") != 0:
        fail(tok, "获取 tenant_access_token")
    token = tok["tenant_access_token"]

    # ② 机器人所在的群列表（应用机器人须已被拉进 Bug 通知群）
    chats = http_json("GET", "/im/v1/chats", token=token, params={"page_size": 20})
    if chats.get("code") != 0:
        fail(chats, "获取机器人所在群列表")
    items = (chats.get("data") or {}).get("items") or []
    if not items:
        print("应用机器人不在任何飞书群里。请先到目标群：群设置 → 群机器人 → 添加机器人 →"
              " 选择该自建应用，然后重跑本脚本。")
        sys.exit(1)
    if len(items) == 1:
        chat = items[0]
    else:
        print("\n该机器人所在群：")
        for i, c in enumerate(items, 1):
            print(f"  {i}. {c.get('name')}")
        idx = input("选择 Bug 通知所在群的序号: ").strip()
        if not idx.isdigit() or not 1 <= int(idx) <= len(items):
            print("无效的序号")
            sys.exit(1)
        chat = items[int(idx) - 1]
    chat_id, chat_name = chat["chat_id"], chat.get("name", "")

    # ③ 群成员列表（分页拉全），member_id_type=open_id 使 member_id 即 open_id
    members, page_token = [], ""
    while True:
        params = {"member_id_type": "open_id", "page_size": 100}
        if page_token:
            params["page_token"] = page_token
        resp = http_json("GET", f"/im/v1/chats/{chat_id}/members", token=token, params=params)
        if resp.get("code") != 0:
            fail(resp, "获取群成员列表")
        data = resp.get("data") or {}
        members += [(m.get("name"), m.get("member_id")) for m in (data.get("items") or [])]
        if not data.get("has_more"):
            break
        page_token = data.get("page_token") or ""

    print(f"\n群「{chat_name}」成员 open_id：")
    for name, oid in sorted(members):
        print(f"  {name}  =  {oid}")
    line = ",".join(f"{name}={oid}" for name, oid in sorted(members))
    print("\n可直接粘贴到服务器 .env 的 FEISHU_AT_MAP（key 为飞书昵称；")
    print("若与平台注册用户名不一致，请把 key 改成 Bug 卡片「提交人」显示的名字）：")
    print(f"FEISHU_AT_MAP={line}")
    print("\n改完 .env 后执行: docker compose up -d backend （重建容器，无需 build）")


if __name__ == "__main__":
    main()
