# 服务器部署指南（Ubuntu 22.04 / 4C4G / 40G 盘）

从零把本系统部署到一台云服务器：Go 后端 + Vue 前端 + MySQL/Redis/RabbitMQ + 飞书群通知。
所有服务由 Docker Compose 编排，前端容器内 nginx 同时反向代理 `/api` 与 `/static`。

## 端口规划（云控制台安全组只需放行前三个）

| 端口 | 服务 | 绑定 | 说明 |
|---|---|---|---|
| 22 | SSH | 公网 | 远程管理 |
| 5173 | frontend (nginx) | 公网 | 页面入口，`/api/`、`/static/` 反代到 backend |
| 8080 | backend | 公网 | 直连 API（可选，只留 5173 也够用） |
| 3307 / 6379 / 5672 / 15672 | MySQL / Redis / RabbitMQ | **仅 127.0.0.1** | 不暴露公网，勿在安全组放行 |

## 1. 安装 Docker（已装可跳过）

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version && docker compose version
```

> 若拉取镜像超时（国内网络），配置镜像加速后重启 docker：
>
> ```bash
> mkdir -p /etc/docker && cat > /etc/docker/daemon.json <<'EOF'
> {"registry-mirrors":["https://docker.m.daocloud.io","https://docker.1ms.run"]}
> EOF
> systemctl restart docker
> ```

## 2. 加 2G swap（4G 内存防构建期 OOM，必做）

```bash
fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h
```

## 3. 拉取代码

```bash
git clone -b deploy https://github.com/13igying/feedsystem_video_go.git /opt/feedsystem
cd /opt/feedsystem
```

> 仓库为私有/需要认证时：
> `git clone -b deploy https://<你的PAT>@github.com/13igying/feedsystem_video_go.git /opt/feedsystem`

## 4. 生成 .env（不进 git，必须手动创建）

```bash
cd /opt/feedsystem
cat > .env <<EOF
MYSQL_ROOT_PASSWORD=123456
MYSQL_DATABASE=feedsystem
REDIS_PASSWORD=123456
RABBITMQ_USER=admin
RABBITMQ_PASS=password123
JWT_SECRET=$(openssl rand -hex 32)
FEISHU_WEBHOOK_URL=<你的飞书群机器人 Webhook 地址>
FEISHU_WEBHOOK_SECRET=
# 真 @ 映射：平台用户名=飞书open_id，逗号分隔（获取方式见下文「飞书真 @ 通知」）
FEISHU_AT_MAP=
EOF
chmod 600 .env
```

说明：

- `FEISHU_WEBHOOK_URL` 填飞书群「自定义机器人」的 webhook 地址；机器人未开启「签名校验」则 `FEISHU_WEBHOOK_SECRET` 留空。
- 不配置该 URL 时默认指向本地 feishu-mock 模拟器（本地调试用）；服务器上务必填真实值。

### 飞书真 @ 通知（FEISHU_AT_MAP）

机器人发送**富文本消息并真实 @ 责任人**（对方会收到飞书推送提醒），需要每个成员的
open_id（`ou_` 开头）。自定义机器人无法自行查询成员 ID，一次性按下面步骤获取：

1. 打开 [飞书开放平台](https://open.feishu.cn/) → 开发者后台 → 创建**企业自建应用**（名称随意，如 `bugbot-helper`）；
2. 应用详情 → 添加应用能力 → **机器人**；创建版本并发布（测试用途可将可用范围设为自己/本部门）；
3. 把该应用机器人拉进 Bug 通知所在的群（群设置 → 群机器人 → 添加机器人）；
4. 打开 [API 调试台](https://open.feishu.cn/api-explorer/)，选择该应用 → 调用「获取用户或机器人所在的群列表」
   （`im/v1/chats`）拿到目标群的 `chat_id`，再调用「获取群成员列表」（`im/v1/chats/:chat_id/members`）；
5. 从返回的 members 中复制每个成员的 `open_id`；
6. 在服务器 `.env` 中配置映射（**key 必须与平台注册的用户名完全一致**）：
   `FEISHU_AT_MAP=张三=ou_xxx,李四=ou_yyy`；
7. `docker compose up -d backend` 重启生效。

行为规则：

- 映射命中 → 消息真实 @ 该成员（飞书单独向他推送提醒）；
- 未命中/未配置 → 降级为 **@所有人**（群里成员都会被提醒，两人小群效果等同点对点）；
- 只想快速演示（两人群、不想建应用）：不配置 `FEISHU_AT_MAP`，直接用 @所有人 也能完成闭环。

## 5. 串行构建（4G 内存，勿并行 build，防 OOM）

```bash
docker compose build backend
docker compose build worker     # 复用 backend 的构建缓存，很快
docker compose build frontend
```

## 6. 启动

```bash
# 先起基础设施，等全部 healthy
docker compose up -d mysql redis rabbitmq
watch -n 2 docker compose ps    # mysql/redis/rabbitmq 均 healthy 后 Ctrl+C 退出

# 再起应用（注意：不启动 feishu-mock，走真实飞书 webhook）
docker compose up -d backend worker frontend
```

## 7. 验证

```bash
docker compose ps                                                       # 6 个服务 Up/healthy
curl -s http://localhost:8080/healthz                                   # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/         # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/api/healthz  # 200（nginx→backend）
```

浏览器访问 `http://<服务器IP>:5173`（安全组放行 5173 后）。

## 8. 飞书通知端到端验收

```bash
curl -s -X POST http://localhost:8080/account/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"deploy01","password":"Deploy#12345"}'

RESP=$(curl -s -X POST http://localhost:8080/account/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"deploy01","password":"Deploy#12345"}')
TOKEN=$(echo "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
AID=$(echo "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["account_id"])')

curl -s -X POST http://localhost:8080/bug/create \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"title\":\"[部署验收] 飞书通知端到端\",\"description\":\"来自服务器的验收 Bug\",\"severity\":\"minor\",\"assignee_id\":$AID}"
```

执行后飞书群里应收到「新 Bug 待修复」卡片；通知发送失败只记日志，不影响接口返回。

## 9. 日常运维

```bash
docker compose logs -f backend        # 看日志（worker/frontend 同理）
docker compose restart backend        # 重启某服务
docker compose down                   # 停止（数据卷保留，MySQL 数据不丢）
docker compose up -d mysql redis rabbitmq backend worker frontend   # 再启动

# 更新版本
git pull
docker compose build backend worker frontend
docker compose up -d backend worker frontend
```

- **注册限流**：compose 默认已调高（`RATELIMIT_REGISTER_MAX=1000`/小时/IP），部署验收的注册不会被限；代码默认值为 5/小时/IP。
- **RabbitMQ 管理台**（15672）仅监听 127.0.0.1，需要查看时用 SSH 隧道：`ssh -L 15672:127.0.0.1:15672 root@<服务器IP>`。
- **首屏 502**：backend 未就绪时 nginx 反代会 502，等 `docker compose ps` 中 backend 变 healthy 即可。
