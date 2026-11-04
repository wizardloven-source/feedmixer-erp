"""
data/seed.py
------------
 seeding البيانات الافتراضية (idempotent):

- إعدادات (settings) من config.settings.DEFAULT_SETTINGS
- مستخدم admin / admin123
- 9 مزارع أساسية
- 12 مادة أساسية

كل إدراج يستخدم INSERT OR IGNORE / SELECT لتجنب التكرار.
"""

from __future__ import annotations

from core.auth import hash_password
from core.logger import get_logger
from data.connection import execute, query_one
from config import settings

_log = get_logger("mixer.seed")


def seed_defaults() -> None:
    """يزرع البيانات الافتراضية إن لم تكن موجودة."""
    try:
        _seed_settings()
        _seed_admin()
        _seed_farms()
        _seed_materials()
        _log.info("تم إكمال seeding البيانات الافتراضية")
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل seeding البيانات الافتراضية: %s", exc)
        raise


def _seed_settings() -> None:
    """يزرع/يُحدّث إعدادات DEFAULT_SETTINGS (لا يُغيّر قيماً مخصّصة)."""
    for key, (value, description) in settings.DEFAULT_SETTINGS.items():
        existing = query_one("SELECT key FROM settings WHERE key = ?", (key,))
        if existing is None:
            execute(
                "INSERT INTO settings (key, value, description) VALUES (?, ?, ?)",
                (key, float(value), description),
            )
        else:
            # حدّث الوصف فقط (القيمة قد تكون مخصّصة من المستخدم)
            execute(
                "UPDATE settings SET description = ? WHERE key = ? AND (description IS NULL OR description = '')",
                (description, key),
            )


def _seed_admin() -> None:
    """ينشئ admin/admin123 إن لم يكن موجوداً."""
    existing = query_one("SELECT id FROM users WHERE username = ?", ("admin",))
    if existing is not None:
        return
    password_hash, salt = hash_password("admin123")
    execute(
        "INSERT INTO users (username, password_hash, salt, role, full_name, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("admin", password_hash, salt, settings.ROLE_ADMIN, "مدير النظام", 1),
    )
    _log.info("تم إنشاء مستخدم admin افتراضي")


def _seed_farms() -> None:
    """يزرع المزارع الافتراضية (INSERT OR IGNORE)."""
    for farm in settings.DEFAULT_FARMS:
        execute(
            "INSERT OR IGNORE INTO farms (name, transport_fee, phone, notes) VALUES (?, ?, ?, ?)",
            (
                farm["name"],
                float(farm.get("transport_fee", 0.0)),
                farm.get("phone", "") or None,
                farm.get("notes", "") or None,
            ),
        )


def _seed_materials() -> None:
    """يزرع المواد الافتراضية (INSERT OR IGNORE)."""
    for name, base, handling, loss, unit in settings.DEFAULT_MATERIALS:
        execute(
            "INSERT OR IGNORE INTO materials (name, base_price, handling_fee, loss_fee, unit_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, float(base), float(handling), float(loss), unit),
        )
