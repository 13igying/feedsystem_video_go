"""测试数据工厂：一键创建用户/视频/评论等测试数据。

注意：注册接口限流 5次/小时/IP，工厂通过复用已注册用户 + 直连后端绕过前端代理来缓解；
若触发 429，用例会给出明确提示（make clean-ratelimit 可清 Redis 限流 key）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .client import APIClient, unique_username, unique_password


@dataclass
class User:
    username: str
    password: str
    account_id: int | None = None
    token: str | None = None
    client: APIClient | None = field(default=None, repr=False)

    def auth_client(self, base_url: str) -> APIClient:
        """返回已认证的独立 client（不影响其他用例）。"""
        c = APIClient(base_url, token=self.token)
        return c


def register_and_login(base_url: str, prefix: str = "u") -> User:
    """注册 + 登录，返回完整 User。注册失败（如限流）时抛出可读错误。"""
    username = unique_username(prefix)
    password = unique_password()

    anon = APIClient(base_url)
    try:
        anon.register(username, password)
    except AssertionError as e:
        raise AssertionError(
            f"\n[工厂] 注册用户失败（可能触发注册限流 5次/小时/IP）\n"
            f"[缓解] 运行 make clean-ratelimit 清除限流后重试\n[详情] {e}"
        )
    finally:
        anon.close()

    c = APIClient(base_url)
    data = c.login(username, password)
    c.set_token(data.get("token"))  # 绑定 token，后续请求自动携带 Authorization
    return User(
        username=username,
        password=password,
        account_id=data.get("account_id"),
        token=data.get("token"),
        client=c,
    )


def make_video_payload() -> dict:
    """生成视频发布 payload（play_url 方式，无需真实文件上传）。"""
    tag = uuid.uuid4().hex[:6]
    return {
        "title": f"自动化测试视频_{tag}",
        "description": f"e2e-auto-{tag} 自动化测试创建的视频",
        "play_url": f"http://example.com/videos/{tag}.mp4",
        "cover_url": f"http://example.com/covers/{tag}.jpg",
    }


def publish_video(base_url: str, user: User, **overrides) -> dict:
    """以 user 身份发布视频，返回发布响应。"""
    payload = make_video_payload()
    payload.update(overrides)
    c = user.client or APIClient(base_url, token=user.token)
    return c.post_ok("/video/publish", payload)


def wait_until(fn, timeout: float = 10.0, interval: float = 0.5, desc: str = "条件成立"):
    """轮询直到 fn() 返回 True（用于异步链路：MQ worker 消费、缓存更新等）。"""
    import time

    deadline = time.time() + timeout
    last_result = None
    while time.time() < deadline:
        last_result = fn()
        if last_result:
            return True
        time.sleep(interval)
    raise TimeoutError(f"等待超时（{timeout}s）：{desc}，最后结果={last_result}")