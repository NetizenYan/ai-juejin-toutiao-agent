import asyncio
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from schemas.users import RegisterRequest, UserRequest
from utils import auth


class UserRequestTests(unittest.TestCase):
    def test_register_rejects_blank_short_and_oversized_input(self):
        for username, password in (("", "Secret123"), ("  ab ", "Secret123"), ("u" * 51, "Secret123"),
                                   ("alice", ""), ("alice", "12345"), ("alice", "x" * 129)):
            with self.assertRaises(ValidationError, msg=(username, password)):
                RegisterRequest(username=username, password=password)
        self.assertEqual(RegisterRequest(username="  alice ", password="123456").username, "alice")

    def test_login_keeps_accepting_accounts_made_before_the_rules(self):
        self.assertEqual(UserRequest(username="ab", password="1").username, "ab")
        with self.assertRaises(ValidationError):
            UserRequest(username="u" * 51, password="x")

    def test_missing_authorization_header_is_401(self):
        for header in (None, "", "   "):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.get_current_user(authorization=header, db=None))
            self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
