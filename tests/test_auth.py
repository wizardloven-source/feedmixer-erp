"""
test_auth
---------
اختبارات وحدة لطبقة المصادقة core/auth.py:
    - generate_salt / hash_password / verify_password (sha256 + salt عشوائي).
    - authenticate ضد قاعدة بيانات SQLite مؤقتة معزولة.
    - منع دخول المستخدم الموقوف، وسلامة البيانات المُعادة (لا تسرّب hash/salt).

التشغيل:
    cd mixer_erp && python -m unittest tests.test_auth -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from core.auth import authenticate, generate_salt, hash_password, verify_password


class TestHashing(unittest.TestCase):
    """تشفير sha256 مع salt عشوائي."""

    def test_roundtrip(self) -> None:
        digest, salt = hash_password("admin123")
        self.assertTrue(verify_password("admin123", digest, salt))

    def test_wrong_password_fails(self) -> None:
        digest, salt = hash_password("admin123")
        self.assertFalse(verify_password("admin124", digest, salt))

    def test_salt_is_random(self) -> None:
        # نفس كلمة المرور تعطي hash مختلفاً بسبب salt العشوائي
        d1, s1 = hash_password("same-pass")
        d2, s2 = hash_password("same-pass")
        self.assertNotEqual(s1, s2)
        self.assertNotEqual(d1, d2)
        self.assertTrue(verify_password("same-pass", d1, s1))
        self.assertTrue(verify_password("same-pass", d2, s2))

    def test_explicit_salt_reused(self) -> None:
        salt = generate_salt()
        d1, s1 = hash_password("x", salt)
        d2, s2 = hash_password("x", salt)
        self.assertEqual(d1, d2)
        self.assertEqual(s1, salt)

    def test_hash_shape(self) -> None:
        digest, salt = hash_password("abc")
        self.assertEqual(len(digest), 64)  # sha256 hexdigest
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))

    def test_verify_missing_inputs(self) -> None:
        self.assertFalse(verify_password("a", None, "salt"))
        self.assertFalse(verify_password("a", "hash", None))
        self.assertFalse(verify_password("a", "", ""))


class TestAuthenticate(unittest.TestCase):
    """مصادقة كاملة ضد قاعدة بيانات مؤقتة."""

    @classmethod
    def setUpClass(cls) -> None:
        # قاعدة بيانات معزولة في ملف مؤقت لا تلمس بيانات المستخدم الحقيقي
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls.db_path = cls._tmp.name

        from data.connection import set_database_path
        from data.schema import init_database
        from data.seed import seed_defaults

        set_database_path(cls.db_path)
        init_database()
        seed_defaults()
        cls._set_db = set_database_path

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    def _make_user(self, username: str, password: str, role: str = "viewer",
                   is_active: bool = True) -> int:
        from data.users_repo import create_user

        return create_user(username=username, password=password, role=role,
                           full_name="اختبار", is_active=is_active)

    def test_default_admin(self) -> None:
        user = authenticate("admin", "admin123")
        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user["username"], "admin")
        self.assertEqual(user["role"], "admin")

    def test_case_insensitive_username(self) -> None:
        self.assertIsNotNone(authenticate("ADMIN", "admin123"))

    def test_wrong_password(self) -> None:
        self.assertIsNone(authenticate("admin", "wrong-password"))

    def test_unknown_user(self) -> None:
        self.assertIsNone(authenticate("ghost-user", "whatever"))

    def test_empty_inputs(self) -> None:
        self.assertIsNone(authenticate("", "x"))
        self.assertIsNone(authenticate("admin", ""))
        self.assertIsNone(authenticate(None, None))  # type: ignore[arg-type]

    def test_no_hash_leakage(self) -> None:
        user = authenticate("admin", "admin123")
        assert user is not None
        self.assertNotIn("password_hash", user)
        self.assertNotIn("salt", user)

    def test_inactive_user_blocked(self) -> None:
        uid = self._make_user("op1", "Passw0rd!", role="operator")
        self.assertGreater(uid, 0)
        self.assertIsNotNone(authenticate("op1", "Passw0rd!"))

        from data.users_repo import set_active

        set_active(uid, False)
        self.assertIsNone(authenticate("op1", "Passw0rd!"))

    def test_password_change(self) -> None:
        uid = self._make_user("op2", "OldPass123!")
        self.assertIsNotNone(authenticate("op2", "OldPass123!"))

        from data.users_repo import change_password

        self.assertTrue(change_password(uid, "NewPass456!"))
        self.assertIsNone(authenticate("op2", "OldPass123!"))
        self.assertIsNotNone(authenticate("op2", "NewPass456!"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
