"""
data/settings_repo.py
---------------------
مستودع الإعدادات (جدول settings: key/value/description).

- get_all_settings : كل الإعدادات كقاموس key -> float.
- get_setting      : إعداد واحد مع قيمة افتراضية.
- set_setting      : upsert + تدقيق + إبطال كاش الإعدادات.
"""

from __future__ import annotations

from typing import Mapping

from core import cache
from core.logger import get_logger, log_audit
from core.utils import safe_float
from data.connection import execute, query_all, query_one

_log = get_logger("mixer.settings_repo")


def get_all_settings() -> dict[str, float]:
    """كل الإعدادات كقاموس (يتجاهل القيم غير الرقمية)."""
    rows = query_all("SELECT key, value FROM settings")
    result: dict[str, float] = {}
    for row in rows:
        key = str(row.get("key", ""))
        if not key:
            continue
        try:
            result[key] = float(row.get("value"))
        except (TypeError, ValueError):
            result[key] = 0.0
    return result


def get_setting(key: str, default: float = 0.0) -> float:
    """قيمة إعداد واحد، أو default عند غيابه."""
    name = str(key or "").strip()
    if not name:
        return default
    row = query_one("SELECT value FROM settings WHERE key = ?", (name,))
    if not row:
        return default
    return safe_float(row.get("value"), default)


def set_setting(key: str, value: float, description: str | None = None) -> float:
    """
    يضيف/يُحدّث إعداداً. يُعيد القيمة المخزّنة.
    يكتب سطر تدقيق ويبطل كاش الإعدادات.
    """
    name = str(key or "").strip()
    if not name:
        raise ValueError("مفتاح الإعداد مطلوب")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"قيمة الإعداد {name} يجب أن تكون رقماً") from exc

    old = query_one("SELECT * FROM settings WHERE key = ?", (name,))
    try:
        if old is None:
            execute(
                "INSERT INTO settings (key, value, description) VALUES (?, ?, ?)",
                (name, numeric, description),
            )
            log_audit(
                "INSERT",
                "settings",
                name,
                None,
                {"key": name, "value": numeric, "description": description},
            )
        else:
            if description is None:
                execute("UPDATE settings SET value = ? WHERE key = ?", (numeric, name))
            else:
                execute(
                    "UPDATE settings SET value = ?, description = ? WHERE key = ?",
                    (numeric, description, name),
                )
            log_audit(
                "UPDATE",
                "settings",
                name,
                {"value": safe_float(old.get("value"))},
                {"value": numeric},
            )
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر حفظ الإعداد %s: %s", name, exc)
        raise
    cache.invalidate_settings()
    return numeric


def set_settings(values: Mapping[str, float]) -> None:
    """يحفظ عدة إعدادات (يُبطل الكاش مرة واحدة في النهاية)."""
    for key, value in values.items():
        set_setting(key, value)
    cache.invalidate_settings()


def get_setting_row(key: str) -> dict | None:
    """صف الإعداد كاملاً (للعرض في تبويب الإعدادات)."""
    return query_one("SELECT * FROM settings WHERE key = ?", (str(key or ""),))
