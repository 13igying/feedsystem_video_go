# 测试套件运行指南

## 本地电脑远程运行（针对部署在服务器上的服务）

测试通过 `API_BASE_URL` 环境变量指向任意后端地址，无需改动代码。

### 1. 把 tests/ 目录拷贝到本地电脑

```bash
# 方式 A：scp 整个目录（在本地电脑执行）
scp -r <user>@<服务器IP>:/root/feedsystem_video_go/tests ./tests

# 方式 B：git 方式（若已推送）
git clone <仓库地址> && cd feedsystem_video_go/tests
```

### 2. 本地安装依赖（一次性）

```bash
cd tests
python3 -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt
# macOS / Linux
.venv/bin/pip install -r requirements.txt
```

### 3. 指向服务器后端并运行

```bash
# macOS / Linux（服务器内网 IP 示例：172.16.0.97）
API_BASE_URL=http://172.16.0.97:8080 .venv/bin/pytest tests/api/ -v

# Windows PowerShell
$env:API_BASE_URL="http://172.16.0.97:8080"; .venv\Scripts\pytest tests\api\ -v

# Windows CMD
set API_BASE_URL=http://172.16.0.97:8080 && .venv\Scripts\pytest tests\api\ -v
```

> 把 `172.16.0.97` 换成您实际访问服务器的 IP/域名。
> 若走公网或跳板机，可先建 SSH 隧道：`ssh -L 8080:localhost:8080 <user>@<服务器IP>`，然后 `API_BASE_URL=http://127.0.0.1:8080` 即可。

### 4. 常用命令

```bash
# 全部 26 个用例
API_BASE_URL=http://172.16.0.97:8080 .venv/bin/pytest tests/api/ -v

# 单模块
API_BASE_URL=http://172.16.0.97:8080 .venv/bin/pytest tests/api/test_social.py -v

# 单用例
API_BASE_URL=http://172.16.0.97:8080 .venv/bin/pytest "tests/api/test_social.py::TestLike::test_likes_count_increases" -v

# 生成 HTML 报告
API_BASE_URL=http://172.16.0.97:8080 .venv/bin/pytest tests/api/ -v --html=report.html --self-contained-html
```

## 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_BASE_URL` | `http://127.0.0.1:8080` | 后端 API 地址 |
| `FRONTEND_URL` | `http://127.0.0.1:5173` | 前端地址（E2E 用） |

## 测试覆盖

- `tests/api/test_account.py` — 注册/登录/鉴权（10 例）
- `tests/api/test_feed.py` — 发布/feed 流/游标分页（9 例）
- `tests/api/test_social.py` — 点赞/取消/关注/粉丝列表，含 MQ 异步轮询（7 例）

注意：测试会向目标服务写入真实数据（注册用户、发布视频），请勿指向生产环境。

## UI 自动化演示（Playwright）

`tests/ui_demo.py` 用 Playwright 驱动真实 Chromium 浏览器，模拟用户完整操作流程：

**打开首页 → 注册新用户 → 登录 → 浏览推荐页 → 切换热榜 → 进入账号页 → 查看设置页**

每一步自动截图到 `tests/ui_shots/`，并生成 `result.json` 结果摘要。

### 运行方式

```bash
# 方式一：命令行直接运行
cd /root/feedsystem_video_go
tests/.venv/bin/python tests/ui_demo.py

# 方式二：Web 运行器页面点击「🎬 UI 自动化演示」按钮（推荐，可看实时日志 + 截图墙）
# 浏览器打开 http://<服务器IP>:8081
```

### 首次准备（一次性）

```bash
# 安装 playwright pip 包（已包含在 requirements.txt）
tests/.venv/bin/pip install playwright

# 下载 Chromium 浏览器（国内服务器建议用 npmmirror 镜像，速度快）
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
  tests/.venv/bin/playwright install chromium
```

### 查看结果

- 截图：`tests/ui_shots/*.png`（10 张，覆盖每个操作步骤）
- 结果：`tests/ui_shots/result.json`（每步 ok/detail + 总体 passed）
- Web 运行器：点击 UI 演示按钮后，页面下方自动展示截图墙，实时刷新
