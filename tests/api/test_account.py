"""账号模块测试：注册 / 登录 / 认证 / 异常流。"""
import pytest

from tests.api.utils.client import APIClient, unique_username, unique_password

pytestmark = pytest.mark.api


class TestRegister:
    def test_register_success(self, anon_client: APIClient):
        """注册成功返回成功消息。"""
        resp = anon_client.register(unique_username("reg"), unique_password())
        assert "message" in resp

    def test_register_duplicate_username(self, anon_client: APIClient, user):
        """重复用户名注册应失败（400 或业务错误）。"""
        anon_client.post_expect_error(
            "/account/register",
            {"username": user.username, "password": unique_password()},
            expect_status=400,
        )

    def test_register_missing_fields(self, anon_client: APIClient):
        """缺字段注册应 400。"""
        anon_client.post_expect_error("/account/register", {"username": "only_name"}, 400)


class TestLogin:
    def test_login_success(self, anon_client: APIClient, user):
        """正确密码登录返回 token/account_id/username。"""
        data = anon_client.login(user.username, user.password)
        assert data.get("token"), "缺少 token"
        assert data.get("account_id") == user.account_id
        assert data.get("username") == user.username

    def test_login_wrong_password(self, anon_client: APIClient, user):
        """错误密码登录应 401/400。"""
        resp = anon_client.post("/account/login", {"username": user.username, "password": "WrongPass!"})
        assert resp.status_code in (400, 401), f"期望 400/401，实际 {resp.status_code}"

    def test_login_nonexistent_user(self, anon_client: APIClient):
        """不存在用户登录应失败。"""
        resp = anon_client.post("/account/login", {"username": "no_such_user_xyz", "password": "whatever1"})
        assert resp.status_code in (400, 401, 404)


class TestJWTProtection:
    def test_protected_endpoint_without_token(self, anon_client: APIClient):
        """无 token 访问受保护接口应 401。"""
        anon_client.post_expect_error("/social/getAllFollowers", {}, 401)

    def test_protected_endpoint_with_invalid_token(self, api_base_url):
        """伪造 token 应 401。"""
        c = APIClient(api_base_url, token="fake.token.here")
        try:
            c.post_expect_error("/social/getAllFollowers", {}, 401)
        finally:
            c.close()

    def test_protected_endpoint_with_valid_token(self, api_base_url, user):
        """有效 token 访问受保护接口应 200。"""
        c = user.auth_client(api_base_url)
        try:
            c.post_ok("/social/getAllFollowers", {})
        finally:
            c.close()

    def test_soft_auth_feed_without_token(self, anon_client: APIClient):
        """feed 是软认证：无 token 也能浏览（200）。"""
        data = anon_client.feed_latest(limit=5)
        assert "video_list" in data
        assert isinstance(data["video_list"], list)