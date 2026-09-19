"""API 测试层 conftest：client 与用户 fixtures。"""
from __future__ import annotations

import pytest

from tests.api.utils.client import APIClient
from tests.api.utils.factories import User, register_and_login


@pytest.fixture
def anon_client(api_base_url) -> APIClient:
    """未认证 client（用例级，自动关闭）。"""
    c = APIClient(api_base_url)
    yield c
    c.close()


@pytest.fixture
def user(api_base_url) -> User:
    """每个用例独立的新注册用户（已登录）。"""
    return register_and_login(api_base_url, prefix="case")


@pytest.fixture(scope="module")
def module_user(api_base_url) -> User:
    """模块级共享用户（减少注册次数，规避限流）。"""
    return register_and_login(api_base_url, prefix="mod")