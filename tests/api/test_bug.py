"""Bug 跟踪模块接口测试

接口（对齐后端 handler）：
- POST /bug/create       {title, description?, severity?, assignee_id} -> bug
- POST /bug/updateStatus {bug_id, status} -> bug
- POST /bug/list         {status?, role?, limit?} -> {bugs: [...], total: n}

状态机：open -> fixing -> fixed -> closed；fixed 可被 reporter 打回 open。
权限：assignee 推进修复流程；reporter 关闭 / 回归。
"""
import pytest

from tests.api.utils.client import APIClient
from tests.api.utils.factories import User, register_and_login

pytestmark = pytest.mark.api


@pytest.fixture(scope="module")
def reporter(api_base_url) -> User:
    """Bug 提交者。"""
    return register_and_login(api_base_url, prefix="bugr")


@pytest.fixture(scope="module")
def assignee(api_base_url) -> User:
    """Bug 负责人。"""
    return register_and_login(api_base_url, prefix="buga")


def _list_bugs(client: APIClient, **kwargs) -> list:
    resp = client.post_ok("/bug/list", kwargs or None)
    return resp.get("bugs", [])


class TestBugCreate:
    def test_create_success(self, api_base_url, reporter, assignee):
        """创建 Bug：默认状态 open，reporter 为当前用户。"""
        bug = reporter.client.post_ok("/bug/create", {
            "title": "[测试] 播放器黑屏",
            "description": "复现步骤：打开任意视频",
            "severity": "major",
            "assignee_id": assignee.account_id,
        })
        assert bug["id"] > 0
        assert bug["status"] == "open"
        assert bug["reporter_id"] == reporter.account_id
        assert bug["assignee_id"] == assignee.account_id

    def test_create_missing_title(self, api_base_url, reporter, assignee):
        """缺少标题应报错（4xx 或业务错误码）。"""
        resp = reporter.client.post_expect_error("/bug/create", {
            "description": "no title",
            "assignee_id": assignee.account_id,
        }, expect_status=400)
        assert resp  # 后端返回错误结构即可


class TestBugWorkflow:
    def test_full_lifecycle(self, api_base_url, reporter, assignee):
        """完整生命周期：open -> fixing -> fixed -> closed。"""
        bug = reporter.client.post_ok("/bug/create", {
            "title": "[测试] 生命周期",
            "severity": "minor",
            "assignee_id": assignee.account_id,
        })
        bid = bug["id"]

        # assignee 开始修复
        b = assignee.client.post_ok("/bug/updateStatus", {"bug_id": bid, "status": "fixing"})
        assert b["status"] == "fixing"

        # assignee 修复完成
        b = assignee.client.post_ok("/bug/updateStatus", {"bug_id": bid, "status": "fixed"})
        assert b["status"] == "fixed"

        # reporter 回归通过，关闭
        b = reporter.client.post_ok("/bug/updateStatus", {"bug_id": bid, "status": "closed"})
        assert b["status"] == "closed"

    def test_reject_flow(self, api_base_url, reporter, assignee):
        """回归失败打回：fixed -> open（仅 reporter 可操作）。"""
        bug = reporter.client.post_ok("/bug/create", {
            "title": "[测试] 回归打回",
            "assignee_id": assignee.account_id,
        })
        bid = bug["id"]
        assignee.client.post_ok("/bug/updateStatus", {"bug_id": bid, "status": "fixing"})
        assignee.client.post_ok("/bug/updateStatus", {"bug_id": bid, "status": "fixed"})

        b = reporter.client.post_ok("/bug/updateStatus", {"bug_id": bid, "status": "open"})
        assert b["status"] == "open"

    def test_invalid_transition_rejected(self, api_base_url, reporter, assignee):
        """非法状态流转应被拒绝（如 open -> closed 由非 reporter / 越序流转）。"""
        bug = reporter.client.post_ok("/bug/create", {
            "title": "[测试] 非法流转",
            "assignee_id": assignee.account_id,
        })
        bid = bug["id"]
        # assignee 不能直接把 open 关闭（只有 reporter 可以）
        resp = assignee.client.post_expect_error(
            "/bug/updateStatus", {"bug_id": bid, "status": "closed"}, expect_status=400)
        assert resp


class TestBugList:
    def test_list_filter_by_status(self, api_base_url, reporter, assignee):
        """按状态过滤列表。"""
        bug = reporter.client.post_ok("/bug/create", {
            "title": "[测试] 列表过滤",
            "assignee_id": assignee.account_id,
        })
        bugs = _list_bugs(reporter.client, status="open", limit=50)
        assert any(b["id"] == bug["id"] for b in bugs)

    def test_list_role_reported(self, api_base_url, reporter):
        """role=reported 只返回我提交的。"""
        bugs = _list_bugs(reporter.client, role="reported", limit=50)
        assert all(b["reporter_id"] == reporter.account_id for b in bugs)

    def test_list_role_assigned(self, api_base_url, reporter, assignee):
        """role=assigned 只返回指派给我的。"""
        reporter.client.post_ok("/bug/create", {
            "title": "[测试] 指派过滤",
            "assignee_id": assignee.account_id,
        })
        bugs = _list_bugs(assignee.client, role="assigned", limit=50)
        assert all(b["assignee_id"] == assignee.account_id for b in bugs)
        assert len(bugs) >= 1

    def test_list_requires_auth(self, api_base_url):
        """未登录访问列表应 401。"""
        anon = APIClient(api_base_url)
        resp = anon.post_expect_error("/bug/list", {}, expect_status=401)
        assert resp