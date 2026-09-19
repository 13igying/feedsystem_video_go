"""API 测试客户端：httpx 封装，自动携带 JWT、统一错误提示。"""
from __future__ import annotations

import json
import uuid
from typing import Any

import httpx


class APIError(AssertionError):
    """接口返回非预期结果时抛出，附带请求/响应详情。"""


class APIClient:
    """线程安全的轻量 API 客户端（每个测试用例独立实例）。"""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(base_url=self.base_url, headers=self._headers, timeout=timeout)

    # ---------- 基础方法 ----------
    def post(self, path: str, json_body: dict | None = None, **kwargs) -> httpx.Response:
        return self._client.post(path, json=json_body if json_body is not None else {}, **kwargs)

    def post_multipart(self, path: str, data: dict, files: dict, **kwargs) -> httpx.Response:
        """multipart 上传（会自动切换 Content-Type）。"""
        headers = {k: v for k, v in self._headers.items() if k.lower() != "content-type"}
        return self._client.post(path, data=data, files=files, headers=headers, **kwargs)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self._client.get(path, **kwargs)

    def close(self):
        self._client.close()

    # ---------- 断言辅助 ----------
    def post_ok(self, path: str, json_body: dict | None = None, expect: int = 200) -> dict:
        """POST 并断言状态码，返回 JSON dict。失败时抛出带上下文的 APIError。"""
        resp = self.post(path, json_body)
        if resp.status_code != expect:
            raise APIError(
                f"\n[请求] POST {path} body={json_body}"
                f"\n[响应] {resp.status_code} {resp.text[:500]}"
            )
        try:
            return resp.json()
        except json.JSONDecodeError:
            raise APIError(f"[响应非 JSON] POST {path} -> {resp.text[:300]}")

    def post_expect_error(self, path: str, json_body: dict | None, expect_status: int) -> dict:
        """POST 并断言返回错误状态码（401/400/403/429 等）。"""
        resp = self.post(path, json_body)
        assert resp.status_code == expect_status, (
            f"[期望 {expect_status}] POST {path} body={json_body} -> 实际 {resp.status_code} {resp.text[:300]}"
        )
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {}

    # ---------- 认证 ----------
    def set_token(self, token: str | None):
        """绑定/清除 token。注意必须同步修改 httpx.Client 的 headers
        （Client 构造时会快照传入的 headers，仅改 self._headers 无效）。"""
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
            self._client.headers["Authorization"] = f"Bearer {token}"
        else:
            self._headers.pop("Authorization", None)
            self._client.headers.pop("Authorization", None)

    @property
    def token(self) -> str | None:
        return self._headers.get("Authorization", "").removeprefix("Bearer ") or None

    # ---------- 便捷业务方法 ----------
    def register(self, username: str, password: str) -> dict:
        return self.post_ok("/account/register", {"username": username, "password": password})

    def login(self, username: str, password: str) -> dict:
        """返回 {token, refresh_token, account_id, username}。"""
        return self.post_ok("/account/login", {"username": username, "password": password})

    def login_and_auth(self, username: str, password: str) -> dict:
        """登录并把 token 绑定到当前 client。"""
        data = self.login(username, password)
        self.set_token(data["token"])
        return data

    def feed_latest(self, limit: int = 10, latest_time: int = 0) -> dict:
        return self.post_ok("/feed/listLatest", {"limit": limit, "latest_time": latest_time})

    def feed_by_likes(self, limit: int = 10, likes_count_before: int = 0, id_before: int = 0) -> dict:
        return self.post_ok(
            "/feed/listLikesCount",
            {"limit": limit, "likes_count_before": likes_count_before, "id_before": id_before},
        )

    def feed_by_following(self, limit: int = 10, latest_time: int = 0) -> dict:
        return self.post_ok("/feed/listByFollowing", {"limit": limit, "latest_time": latest_time})

    def like(self, video_id: int) -> dict:
        return self.post_ok("/like/like", {"video_id": video_id})

    def unlike(self, video_id: int) -> dict:
        return self.post_ok("/like/unlike", {"video_id": video_id})

    def is_liked(self, video_id: int) -> dict:
        return self.post_ok("/like/isLiked", {"video_id": video_id})

    def video_detail(self, video_id: int) -> dict:
        """视频详情（含 likes_count）。后端无独立 getLikesCount 接口。"""
        return self.post_ok("/video/getDetail", {"id": video_id})

    def likes_count(self, video_id: int) -> int:
        return int(self.video_detail(video_id).get("likes_count", 0))

    def list_my_liked(self, limit: int = 20) -> list:
        """我的喜欢列表（响应为裸数组）。"""
        data = self.post_ok("/like/listMyLikedVideos", {"limit": limit})
        return data if isinstance(data, list) else data.get("video_list", [])

    def follow(self, vlogger_id: int) -> dict:
        return self.post_ok("/social/follow", {"vlogger_id": vlogger_id})

    def unfollow(self, vlogger_id: int) -> dict:
        return self.post_ok("/social/unfollow", {"vlogger_id": vlogger_id})

    def publish_comment(self, video_id: int, content: str) -> dict:
        return self.post_ok("/comment/publish", {"video_id": video_id, "content": content})

    def list_comments(self, video_id: int) -> dict:
        return self.post_ok("/comment/listAll", {"video_id": video_id})


def unique_username(prefix: str = "t") -> str:
    """生成唯一用户名（避免注册重复 & 并发冲突）。"""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def unique_password() -> str:
    return "Test#" + uuid.uuid4().hex[:8]