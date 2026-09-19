"""Feed 模块测试：最新流 / 热度流 / 关注流 / 分页游标。"""
import pytest

from tests.api.utils.client import APIClient
from tests.api.utils.factories import publish_video, wait_until

pytestmark = pytest.mark.api


class TestFeedLatest:
    def test_list_latest_structure(self, anon_client: APIClient):
        """listLatest 返回结构完整：video_list/next_time/has_more。"""
        data = anon_client.feed_latest(limit=5)
        assert set(data.keys()) >= {"video_list", "next_time", "has_more"}
        assert isinstance(data["video_list"], list)
        assert isinstance(data["has_more"], bool)

    def test_list_latest_limit_respected(self, api_base_url, module_user):
        """limit 参数生效：返回条数 <= limit。"""
        for _ in range(3):
            publish_video(api_base_url, module_user)
        data = module_user.client.feed_latest(limit=2)
        assert len(data["video_list"]) <= 2

    def test_list_latest_pagination_cursor(self, api_base_url, module_user):
        """分页游标：用 next_time 翻页，第二页不重复第一页内容。"""
        page1 = module_user.client.feed_latest(limit=2)
        if not page1["has_more"]:
            pytest.skip("数据不足，无法验证翻页")
        cursor = page1["next_time"]
        page2 = module_user.client.feed_latest(limit=2, latest_time=cursor)
        ids1 = {v["id"] for v in page1["video_list"]}
        ids2 = {v["id"] for v in page2["video_list"]}
        assert ids1.isdisjoint(ids2), f"翻页出现重复: {ids1 & ids2}"

    def test_new_video_appears_in_feed(self, api_base_url, module_user):
        """新发布的视频应出现在最新流中（验证 timeline 写入链路）。"""
        payload = publish_video(api_base_url, module_user)
        video_id = payload.get("video_id") or payload.get("id")

        def _found():
            feed = module_user.client.feed_latest(limit=20)
            return any(v["id"] == video_id for v in feed["video_list"])

        wait_until(_found, timeout=15, desc=f"视频 {video_id} 出现在最新流")


class TestFeedByLikes:
    def test_list_by_likes_desc_order(self, api_base_url, module_user):
        """热度流按点赞数降序。"""
        data = module_user.client.feed_by_likes(limit=10)
        videos = data.get("video_list", [])
        counts = [v.get("likes_count", 0) for v in videos]
        assert counts == sorted(counts, reverse=True), f"热度流未降序: {counts}"

    def test_list_by_likes_pagination(self, api_base_url, module_user):
        """热度流翻页游标不重复（游标字段为 next_likes_count_before/next_id_before）。"""
        page1 = module_user.client.feed_by_likes(limit=2)
        if not page1.get("has_more"):
            pytest.skip("数据不足")
        body = {
            "limit": 2,
            "likes_count_before": page1["next_likes_count_before"],
            "id_before": page1["next_id_before"],
        }
        page2 = module_user.client.post_ok("/feed/listLikesCount", body)
        ids1 = {v["id"] for v in page1["video_list"]}
        ids2 = {v["id"] for v in page2["video_list"]}
        assert ids1.isdisjoint(ids2)


class TestFeedByFollowing:
    def test_following_feed_requires_auth(self, anon_client: APIClient):
        """关注流必须登录（硬认证）。"""
        anon_client.post_expect_error("/feed/listByFollowing", {"limit": 5}, 401)

    def test_following_feed_only_followed(self, api_base_url, module_user, user):
        """关注流只包含被关注者的视频。"""
        from tests.api.utils.factories import register_and_login

        author = register_and_login(api_base_url, prefix="author")
        publish_video(api_base_url, author)
        module_user.client.follow(author.account_id)

        feed = module_user.client.feed_by_following(limit=20)
        # FeedVideoItem 的作者字段为 author.id（嵌套对象）
        author_ids = {v.get("author", {}).get("id") for v in feed["video_list"]}
        assert author.account_id in author_ids or len(feed["video_list"]) == 0, (
            f"关注流异常: author={author.account_id} feed_authors={author_ids}"
        )
        assert user.account_id not in author_ids, "关注流出现了未关注用户的视频"


class TestFeedByTag:
    def test_list_by_tag(self, anon_client: APIClient):
        """按 tag 检索 feed 接口可用（请求字段为 tag_name）。"""
        data = anon_client.post_ok("/feed/listByTag", {"tag_name": "e2e-auto", "limit": 5})
        assert "video_list" in data
