"""
data/users_repo.py
------------------
مستودع المستخدمين (admin / operator / viewer).

- CRUD كامل مع تشفير كلمات المرور (hash_password).
- منع حذف/تعطيل/تخفيض آخر admin نشط.
- دوال تغيير كلمة المرور (بواسطة admin أو بواسطة صاحب الحساب).
- كل عمليات الكتابة تُسجَّل في audit_log دون أي hash/salt.
"""

from __future__ import annotations

from typing import Any

from config import settings
from core.auth import hash_password, verify_password
from core.logger import get_logger, log_audit
from core.validators import validate_password, validate_username
from data.connection import execute, query_all, query_one

_log = get_logger("mixer.users_repo")

_PUBLIC_COLUMNS = "id, username, role, full_name, is_active, created_at"


# ============================================================
# القراءة
# ============================================================

def list_users(include_inactive: bool = True) -> list[dict]:
    """قائمة المستخدمين (بدون hash/salt) مرتّبة بالاسم."""
    sql = f"SELECT {_PUBLIC_COLUMNS} FROM users"
    if not include_inactive:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY username COLLATE NOCASE"
    return query_all(sql)


def get_user(user_id: int) -> dict | None:
    """بيانات مستخدم عامة (بدون hash/salt)."""
    return query_one(
        f"SELECT {_PUBLIC_COLUMNS} FROM users WHERE id = ?", (int(user_id),)
    )


def get_user_by_username(username: str) -> dict | None:
    """
    صف المستخدم الكامل (بما فيه password_hash و salt).
    تُستخدم فقط من core.auth.authenticate.
    """
    return query_one(
        "SELECT * FROM users WHERE username = ?",
        (str(username or "").strip().lower(),),
    )


def count_admins(active_only: bool = True) -> int:
    """عدد مديري النظام (النشطين افتراضياً)."""
    sql = "SELECT COUNT(*) AS total FROM users WHERE role = ?"
    params: list[Any] = [settings.ROLE_ADMIN]
    if active_only:
        sql += " AND is_active = 1"
    row = query_one(sql, tuple(params))
    try:
        return int((row or {}).get("total") or 0)
    except (TypeError, ValueError):
        return 0


def _is_last_active_admin(user_id: int) -> bool:
    """هل هذا المستخدم هو آخر admin نشط؟"""
    user = get_user(user_id)
    if not user or user.get("role") != settings.ROLE_ADMIN:
        return False
    if not bool(user.get("is_active", 1)):
        return False
    return count_admins(active_only=True) <= 1


# ============================================================
# الكتابة
# ============================================================

def create_user(
    username: str,
    password: str,
    role: str = settings.ROLE_VIEWER,
    full_name: str = "",
    is_active: bool = True,
) -> int:
    """ينشئ مستخدماً جديداً ويعيد معرّفه."""
    clean_username = validate_username(username)
    clean_password = validate_password(password)
    if role not in settings.ROLES:
        raise ValueError("الدور غير صالح (admin / operator / viewer)")
    if get_user_by_username(clean_username):
        raise ValueError(f"اسم المستخدم «{clean_username}» مستخدم بالفعل")

    digest, salt = hash_password(clean_password)
    try:
        cursor = execute(
            "INSERT INTO users (username, password_hash, salt, role, full_name, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                clean_username,
                digest,
                salt,
                role,
                str(full_name or "").strip() or clean_username,
                1 if is_active else 0,
            ),
        )
        user_id = int(cursor.lastrowid or 0)
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر إنشاء المستخدم %s: %s", clean_username, exc)
        raise ValueError("تعذر إنشاء المستخدم (قد يكون الاسم مكرراً)") from exc

    log_audit(
        "INSERT",
        "users",
        user_id,
        None,
        {
            "username": clean_username,
            "role": role,
            "full_name": full_name,
            "is_active": int(is_active),
        },
    )
    return user_id


def update_user(
    user_id: int,
    full_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> bool:
    """
    تحديث جزئي للمستخدم.
    يرفع ValueError عند محاولة تخفيض/تعطيل آخر admin نشط.
    """
    old = get_user(user_id)
    if not old:
        raise ValueError("المستخدم غير موجود")

    if role is not None and role not in settings.ROLES:
        raise ValueError("الدور غير صالح (admin / operator / viewer)")

    losing_admin = (
        old.get("role") == settings.ROLE_ADMIN
        and (
            (role is not None and role != settings.ROLE_ADMIN)
            or (is_active is not None and not is_active)
        )
        and bool(old.get("is_active", 1))
    )
    if losing_admin and _is_last_active_admin(user_id):
        raise ValueError("لا يمكن تعطيل أو تخفيض آخر مدير نظام نشط")

    fields: list[str] = []
    params: list[object] = []
    changes: dict[str, object] = {}

    if full_name is not None:
        name = str(full_name).strip() or str(old.get("username") or "")
        fields.append("full_name = ?")
        params.append(name)
        changes["full_name"] = name

    if role is not None:
        fields.append("role = ?")
        params.append(role)
        changes["role"] = role

    if is_active is not None:
        fields.append("is_active = ?")
        params.append(1 if is_active else 0)
        changes["is_active"] = int(is_active)

    if password is not None:
        clean_password = validate_password(password)
        digest, salt = hash_password(clean_password)
        fields.append("password_hash = ?")
        params.append(digest)
        fields.append("salt = ?")
        params.append(salt)
        changes["password"] = "changed"

    if not fields:
        return False

    params.append(int(user_id))
    try:
        execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", tuple(params))
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث المستخدم %s: %s", user_id, exc)
        raise ValueError("تعذر تحديث المستخدم") from exc

    log_audit(
        "UPDATE",
        "users",
        user_id,
        {key: old.get(key) for key in changes if key != "password"},
        changes,
    )
    return True


def set_active(user_id: int, active: bool) -> bool:
    """تنشيط/إيقاف مستخدم مع حماية آخر admin."""
    return update_user(user_id, is_active=active)


def change_password(
    user_id: int,
    new_password: str,
    old_password: str | None = None,
) -> bool:
    """
    تغيير كلمة المرور.
    - admin: يمكنه التغيير دون كلمة قديمة (old_password=None).
    - المستخدم نفسه: تمرير old_password للتحقق قبل التغيير.
    """
    user = get_user(user_id)
    if not user:
        raise ValueError("المستخدم غير موجود")

    if old_password is not None:
        row = get_user_by_username(str(user.get("username") or ""))
        if not row or not verify_password(
            old_password, row.get("password_hash"), row.get("salt")
        ):
            raise ValueError("كلمة المرور الحالية غير صحيحة")

    return update_user(user_id, password=new_password)


def delete_user(user_id: int, acting_user_id: int | None = None) -> bool:
    """
    يحذف مستخدماً. يرفع ValueError إذا:
    - كان آخر admin نشط.
    - حاول المستخدم حذف حسابه الحالي.
    """
    user = get_user(user_id)
    if not user:
        return False
    if acting_user_id is not None and int(acting_user_id) == int(user_id):
        raise ValueError("لا يمكنك حذف حسابك الحالي")
    if _is_last_active_admin(user_id):
        raise ValueError("لا يمكن حذف آخر مدير نظام نشط")

    execute("DELETE FROM users WHERE id = ?", (int(user_id),))
    log_audit(
        "DELETE",
        "users",
        user_id,
        {"username": user.get("username"), "role": user.get("role")},
        None,
    )
    return True
