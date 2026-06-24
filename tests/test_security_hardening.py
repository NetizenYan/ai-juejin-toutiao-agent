import asyncio
import importlib
import unittest
from datetime import datetime, timedelta


class DummyRequest:
    def __init__(self, url="http://testserver/path?secret=value"):
        self.url = url


class SecurityHardeningTests(unittest.TestCase):
    def test_exception_handler_omits_traceback_and_exception_detail_by_default(self):
        from utils.exception import general_exception_handler

        response = asyncio.run(general_exception_handler(DummyRequest(), RuntimeError("db password leaked")))

        self.assertEqual(response.status_code, 500)
        body = response.body.decode("utf-8")
        self.assertNotIn("traceback", body)
        self.assertNotIn("db password leaked", body)
        self.assertNotIn("testserver/path", body)

    def test_database_url_is_not_hardcoded_with_root_password(self):
        db_conf = importlib.import_module("config.db_conf")

        self.assertNotIn("root:123456", db_conf.ASYNC_DATABASE_URL)
        self.assertNotIn("123456", db_conf.ASYNC_DATABASE_URL)

    def test_redis_password_is_not_hardcoded_literal(self):
        cache_conf = importlib.import_module("config.cache_conf")

        self.assertNotEqual(cache_conf.REDIS_PASSWORD, "0813")

    def test_user_token_repr_redacts_token_value(self):
        from models.users import UserToken

        token = UserToken(
            user_id=1,
            token="secret-token-value",
            expires_at=datetime.now() + timedelta(days=1),
        )

        rendered = repr(token)
        self.assertNotIn("secret-token-value", rendered)
        self.assertIn("<redacted>", rendered)

    def test_cors_does_not_allow_wildcard_origin_with_credentials(self):
        import main

        cors_options = None
        for middleware in main.app.user_middleware:
            if getattr(middleware.cls, "__name__", "") == "CORSMiddleware":
                cors_options = middleware.kwargs
                break

        self.assertIsNotNone(cors_options)
        if cors_options.get("allow_credentials"):
            self.assertNotEqual(cors_options.get("allow_origins"), ["*"])


if __name__ == "__main__":
    unittest.main()
