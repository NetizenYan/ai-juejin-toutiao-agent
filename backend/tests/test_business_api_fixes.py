"""Business API regression tests. DB and auth dependencies are overridden; no MySQL needed."""
import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from backend.app import crud
from backend.app.crud import favorite as _favorite, history as _history, users as _users  # noqa: F401 - loads crud.<name>
from backend.app.db.session import get_db
from backend.app.services import news_service
from backend.app.main import app
from backend.app.models.favorite import Favorite
from backend.app.models.news import News
from backend.app.models.users import User, UserToken
from backend.app.api.deps import get_current_user
from backend.app.core.exception import integrity_error_detail


def _fake_user():
    return SimpleNamespace(
        id=7, username="alice", password="hashed", nickname=None,
        avatar=None, gender="unknown", bio=None,
    )


async def _fake_db():
    yield SimpleNamespace()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = 0

    async def execute(self, _stmt):
        self.executed += 1
        return _Result(self.rows)


class BusinessApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_db] = _fake_db
        app.dependency_overrides[get_current_user] = _fake_user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_news_list_rejects_non_positive_page(self):
        self.assertEqual(self.client.get("/api/news/list?categoryId=1&page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/news/list?categoryId=1&pageSize=0").status_code, 422)

    def test_wrong_old_password_is_client_error(self):
        with mock.patch.object(crud.users, "change_password", mock.AsyncMock(return_value=False)):
            resp = self.client.put("/api/user/password", json={"oldPassword": "bad", "newPassword": "123456"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "旧密码错误")

    def test_invalid_gender_is_rejected_before_db(self):
        resp = self.client.put("/api/user/update", json={"gender": "男"})
        self.assertEqual(resp.status_code, 422)

    def test_duplicate_favorite_is_rejected_with_clear_message(self):
        add = mock.AsyncMock()
        with mock.patch.object(crud.favorite, "is_news_favorite", mock.AsyncMock(return_value=True)), \
                mock.patch.object(crud.favorite, "add_news_favorite", add):
            resp = self.client.post("/api/favorite/add", json={"newsId": 3})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "已经收藏过这条新闻")
        add.assert_not_called()

    def test_history_delete_path_value_is_news_id(self):
        delete = mock.AsyncMock(return_value=True)
        with mock.patch.object(crud.history, "delete_history", delete):
            resp = self.client.delete("/api/history/delete/42")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(delete.await_args.args[1:], (7, 42))


class BusinessCrudTests(unittest.TestCase):
    def test_empty_profile_update_does_not_issue_update(self):
        db = _FakeSession()
        user = _fake_user()
        with mock.patch.object(crud.users, "get_user_by_username", mock.AsyncMock(return_value=user)):
            result = asyncio.run(crud.users.update_user(db, "alice", crud.users.UserUpdateRequest()))
        self.assertIs(result, user)
        self.assertEqual(db.executed, 0)

    def test_news_list_shape_is_the_same_on_cache_miss_and_hit(self):
        row = News(id=1, title="t", description="d", content="full body", image=None, author="a",
                   category_id=2, views=3, publish_time=datetime(2026, 1, 1))
        stored = {}

        async def fake_set(_cid, _page, _size, data):
            stored["data"] = data
            return True

        with mock.patch.object(news_service, "get_cache_news_list", mock.AsyncMock(return_value=None)), \
                mock.patch.object(news_service, "set_cache_news_list", fake_set):
            miss = asyncio.run(news_service.get_news_list(_FakeSession([row]), 2, 0, 10))
        with mock.patch.object(news_service, "get_cache_news_list", mock.AsyncMock(return_value=stored["data"])):
            hit = asyncio.run(news_service.get_news_list(_FakeSession(), 2, 0, 10))

        self.assertEqual(miss, hit)
        self.assertNotIn("content", miss[0])
        self.assertEqual(miss[0]["publishTime"], "2026-01-01T00:00:00")
        self.assertEqual(miss[0]["categoryId"], 2)


class ModelAndErrorTests(unittest.TestCase):
    def test_timestamp_defaults_are_evaluated_per_row(self):
        for column in (User.__table__.c.created_at, User.__table__.c.updated_at,
                       UserToken.__table__.c.created_at, Favorite.__table__.c.created_at):
            self.assertTrue(column.default.is_callable, column)
        self.assertTrue(User.__table__.c.updated_at.onupdate.is_callable)

    def test_integrity_errors_map_to_specific_messages(self):
        self.assertEqual(integrity_error_detail("Duplicate entry 'bob' for key 'user.username_UNIQUE'"), "用户名已存在")
        self.assertEqual(integrity_error_detail("Duplicate entry '1-3' for key 'favorite.user_news_unique'"),
                         "已经收藏过这条新闻")
        self.assertEqual(integrity_error_detail("Duplicate entry '138' for key 'user.phone_UNIQUE'"), "手机号已被使用")
        self.assertEqual(integrity_error_detail("Duplicate entry 'x' for key 'other'"), "数据已存在，请勿重复提交")
        self.assertEqual(integrity_error_detail("Cannot add or update a child row: a FOREIGN KEY constraint fails"),
                         "关联数据不存在")


if __name__ == "__main__":
    unittest.main()
