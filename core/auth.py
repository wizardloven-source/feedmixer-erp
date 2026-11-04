"""
core/auth.py
------------
تشفير كلمات المرور والمصادقة.

- hash_password : SHA-256 مع salt عشوائي لكل مستخدم (secrets.token_hex).
- verify_password : مقارنة ثابتة الزمن عبر hmac.compare_digest.
- authenticate : قراءة المستخدم من users_repo والتحقق من كلمة المرور
  وحالة التنشيط، وإرجاع قاموس المستخدم (بدون hash/salt).

لا تُخزَّن كلمات المرور الصريحة في أي مكان.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from core.logger import get_logger

_log = get_logger("mixer.auth")

HASH_NAME = "sha256"
SALT_BYTES = 16
SALT_HEX_LENGTH = SALT_BYTES * 2


def generate_salt() -> str:
    """ينشئ salt عشوائياً (32 حرف hex)."""
    return secrets.token_hex(SALT_BYTES)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """
    يعيد (password_hash, salt).

    >>> digest, salt = hash_password("admin123")
    >>> verify_password("admin123", digest, salt)
    True
    """
    if not isinstance(password, str):
        password = str(password or "")
    if not salt:
        salt = generate_salt()
    digest = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return digest, salt


def verify_password(password: str, password_hash: str | None, salt: str | None) -> bool:
    """يتحقق من كلمة المرور بمقارنة ثابتة الزمن."""
    if not password_hash or not salt:
        return False
    try:
        candidate, _ = hash_password(str(password or ""), str(salt))
        return hmac.compare_digest(candidate, str(password_hash))
    except Exception as exc:  # noqa: BLE001
        _log.warning("verify_password failed: %s", exc)
        return False


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    """
    يصادق مستخدماً نشطاً ويعيد بياناته العامة، أو None عند الفشل.

    البيانات المُعادة: id, username, role, full_name, is_active
    (لا تحتوي password_hash ولا salt).
    """
    clean_username = str(username or "").strip().lower()
    if not clean_username or not password:
        return None

    try:
        from data.users_repo import get_user_by_username  # lazy import

        row = get_user_by_username(clean_username)
    except Exception as exc:  # noqa: BLE001
        _log.exception("تعذر قراءة المستخدم %s: %s", clean_username, exc)
        return None

    if not row:
        _log.info("محاولة دخول باسم مستخدم غير موجود: %s", clean_username)
        return None

    if not bool(row.get("is_active", 1)):
        _log.info("محاولة دخول لمستخدم موقوف: %s", clean_username)
        return None

    if not verify_password(password, row.get("password_hash"), row.get("salt")):
        _log.info("كلمة مرور خاطئة للمستخدم: %s", clean_username)
        return None

    user = {
        "id": row.get("id"),
        "username": row.get("username"),
        "role": row.get("role", "viewer"),
        "full_name": row.get("full_name") or row.get("username"),
        "is_active": bool(row.get("is_active", 1)),
    }
    _log.info("دخول ناجح: %s (%s)", user["username"], user["role"])
    return user
