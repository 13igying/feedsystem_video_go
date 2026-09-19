"""顶层 conftest：全局配置与环境探活。

环境变量：
    API_BASE_URL  后端直连地址，默认 http://127.0.0.1:8080
    FRONTEND_URL  前端地址（E2E 用），默认 http://127.0.0.1:5173
"""
import os

import pytest
import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8080")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")


def _wait_backend_ready(base_url: str, timeout: float = 30.0) -> None:
    """轮询 /healthz 直到后端就绪。"""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/healthz", timeout=3.0)
            if r.status_code == 200:
                return
        except httpx.HTTPError as e:
            last_err = e
        time.sleep(0.5)
    pytest.exit(f"后端 {base_url} 未就绪: {last_err}", returncode=4)


import time  # noqa: E402  (置于 _wait_backend_ready 之后仅为可读性)


@pytest.fixture(scope="session", autouse=True)
def backend_ready():
    """session 级：确保后端可用，否则快速失败。"""
    _wait_backend_ready(API_BASE_URL, timeout=30.0)


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return API_BASE_URL


@pytest.fixture(scope="session")
def frontend_url() -> str:
    return FRONTEND_URL