"""
core/logger.py
--------------
التسجيل المركزي للتطبيق + سجل التدقيق (audit trail).

- setup_logging() : يهيئ تسجيلاً على الملف (RotatingFileHandler) والطرفية.
- get_logger()    : يعيد logger باسم الوحدة.
- log_audit()     : يكتب سطراً في جدول audit_log لكل INSERT/UPDATE/DELETE.
- set_current_user()/get_current_user() : المستخدم الحالي للجلسة،
  يُستخدم كقيمة افتراضية لحقل user في سجل التدقيق.

ملاحظة: يتم استيراد طبقة البيانات داخل الدوال (lazy import)
لتجنب الاستيراد الدوري بين data ↔ core.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from typing import Any

from config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-24s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_AUDIT_TEXT = 4000

_configured: bool = False
_current_user: str = "system"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    يهيئ نظام التسجيل مرة واحدة فقط ويعيد الجذر (root logger).
    عند فشل إنشاء الملف يتراجع إلى التسجيل على الطرفية.
    """
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    try:
        settings.ensure_directories()
        root.setLevel(level)
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        file_handler = logging.handlers.RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        root.addHandler(console)

        # تقليل ضجيج مكتبات الطرف الثالث
        logging.getLogger("matplotlib").setLevel(logging.WARNING)
        logging.getLogger("openpyxl").setLevel(logging.WARNING)

        _configured = True
        root.info("تم بدء التسجيل -> %s", settings.LOG_FILE)
    except Exception:  # noqa: BLE001 - التسجيل يجب ألا يُسقط التطبيق
        logging.basicConfig(level=level, format=_LOG_FORMAT, datefmt=_DATE_FORMAT)
        _configured = True
        logging.getLogger("mixer.logger").warning(
            "تعذر إنشاء ملف السجل، تم التحويل إلى التسجيل الطرفي"
        )
    return logging.getLogger()


def get_logger(name: str = "mixer_erp") -> logging.Logger:
    """يعيد logger باسم الوحدة المطلوبة."""
    return logging.getLogger(name)


def set_current_user(username: str | None) -> None:
    """يسجّل المستخدم الحالي للجلسة (يُستخدم في التدقيق)."""
    global _current_user
    _current_user = (username or "").strip() or "system"


def get_current_user() -> str:
    """يعيد اسم المستخدم الحالي للجلسة."""
    return _current_user


def _serialize(value: Any) -> str | None:
    """يحوّل أي قيمة إلى نص JSON آمن للتخزين في audit_log."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            text = value
        elif isinstance(value, (int, float, bool)):
            text = str(value)
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = repr(value)
    if len(text) > _MAX_AUDIT_TEXT:
        text = text[:_MAX_AUDIT_TEXT] + "...<truncated>"
    return text


def log_audit(
    action: str,
    table_name: str,
    record_id: int | str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    user: str | None = None,
) -> None:
    """
    يكتب سطر تدقيق واحد. لا يرفع استثناء أبداً:
    فشل التدقيق لا يجب أن يمنع حفظ العملية الأصلية.
    """
    actor = (user or _current_user or "system").strip() or "system"
    try:
        from data.connection import execute  # lazy import

        execute(
            "INSERT INTO audit_log "
            "(action, table_name, record_id, old_value, new_value, timestamp, user) "
            "VALUES (?, ?, ?, ?, ?, datetime('now','localtime'), ?)",
            (
                str(action or "").upper(),
                str(table_name or ""),
                None if record_id is None else str(record_id),
                _serialize(old_value),
                _serialize(new_value),
                actor,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        get_logger("mixer.audit").warning("تعذر كتابة سجل التدقيق: %s", exc)
