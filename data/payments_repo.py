"""
data/payments_repo.py
---------------------
مستودع المدفوعات (payments) المرتبطة بالمزارع.

- CRUD كامل مع توثيق من أنشأ العملية (created_by).
- كل دفعة تُسجَّل في audit_log وتؤثر على مستحقات المزرعة تلقائياً.
"""

from __future__ import annotations

from typing import Any

from core import cache
from core.logger import get_logger, log_audit
from core.utils import safe_float
from core.validators import validate_date, validate_money, validate_name, validate_choice
from data.connection import execute, query_all, query_one
from config import settings

_log = get_logger("mixer.payments_repo")


# ============================================================
# القراءة
# ============================================================

def list_payments(
    farm: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    method: str | None = None,
) -> list[dict]:
    """قائمة المدفوعات مع فلاتر، أحدث أولاً."""
    sql = "SELECT * FROM payments WHERE 1=1"
    params: list[Any] = []
    if farm:
        sql += " AND farm_name = ?"
        params.append(farm)
    if date_from:
        sql += " AND payment_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND payment_date <= ?"
        params.append(date_to)
    if method:
        sql += " AND method = ?"
        params.append(method)
    sql += " ORDER BY payment_date DESC, id DESC"
    return query_all(sql, tuple(params))


def get_payment(payment_id: int) -> dict | None:
    """دفعة بالمعرّف."""
    return query_one("SELECT * FROM payments WHERE id = ?", (int(payment_id),))


def payments_by_farm(farm_name: str) -> list[dict]:
    """كل مدفوعات مزرعة معينة."""
    return query_all(
        "SELECT * FROM payments WHERE farm_name = ? ORDER BY payment_date DESC, id DESC",
        (str(farm_name or ""),),
    )


def total_payments_by_farm(farm_name: str) -> float:
    """مجموع مدفوعات مزرعة."""
    row = query_one(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE farm_name = ?",
        (str(farm_name or ""),),
    )
    return safe_float((row or {}).get("total"))


# ============================================================
# الكتابة
# ============================================================

def add_payment(
    farm_name: str,
    payment_date: str,
    amount: float,
    method: str = "cash",
    reference: str = "",
    notes: str = "",
    created_by: str | None = None,
) -> int:
    """
    يضيف دفعة جديدة ويعيد معرّفها.
    يتحقق من وجود المزرعة ومن أن الطريقة ضمن القيم المسموحة.
    """
    clean_farm = validate_name(farm_name, "المزرعة", min_length=1)
    from data.farms_repo import get_farm_by_name

    if get_farm_by_name(clean_farm) is None:
        raise ValueError(f"المزرعة «{clean_farm}» غير موجودة")

    date_text = validate_date(payment_date, "تاريخ الدفعة")
    amt = validate_money(amount, "المبلغ", allow_zero=False)
    clean_method = validate_choice(method, settings.PAYMENT_METHODS, "طريقة الدفع")

    try:
        cursor = execute(
            "INSERT INTO payments (farm_name, payment_date, amount, method, reference, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                clean_farm,
                date_text,
                round(amt, 2),
                clean_method,
                str(reference or "").strip() or None,
                str(notes or "").strip() or None,
                created_by,
            ),
        )
        payment_id = int(cursor.lastrowid or 0)
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر إضافة الدفعة: %s", exc)
        raise ValueError("تعذر إضافة الدفعة") from exc

    log_audit(
        "INSERT",
        "payments",
        payment_id,
        None,
        {
            "farm_name": clean_farm,
            "payment_date": date_text,
            "amount": round(amt, 2),
            "method": clean_method,
        },
        user=created_by,
    )
    cache.invalidate_prefix("farms:")
    cache.invalidate_prefix("inventory")
    return payment_id


def update_payment(
    payment_id: int,
    farm_name: str | None = None,
    payment_date: str | None = None,
    amount: float | None = None,
    method: str | None = None,
    reference: str | None = None,
    notes: str | None = None,
) -> bool:
    """تحديث دفعة موجودة."""
    old = get_payment(payment_id)
    if not old:
        raise ValueError("الدفعة غير موجودة")

    fields: list[str] = []
    params: list[Any] = []
    changes: dict[str, Any] = {}

    if farm_name is not None:
        clean_farm = validate_name(farm_name, "المزرعة", min_length=1)
        from data.farms_repo import get_farm_by_name

        if get_farm_by_name(clean_farm) is None:
            raise ValueError(f"المزرعة «{clean_farm}» غير موجودة")
        fields.append("farm_name = ?")
        params.append(clean_farm)
        changes["farm_name"] = {"old": old.get("farm_name"), "new": clean_farm}

    if payment_date is not None:
        fields.append("payment_date = ?")
        params.append(validate_date(payment_date, "تاريخ الدفعة"))
        changes["payment_date"] = {"old": old.get("payment_date"), "new": payment_date}

    if amount is not None:
        amt = validate_money(amount, "المبلغ", allow_zero=False)
        fields.append("amount = ?")
        params.append(round(amt, 2))
        changes["amount"] = {"old": old.get("amount"), "new": round(amt, 2)}

    if method is not None:
        clean_method = validate_choice(method, settings.PAYMENT_METHODS, "طريقة الدفع")
        fields.append("method = ?")
        params.append(clean_method)
        changes["method"] = {"old": old.get("method"), "new": clean_method}

    if reference is not None:
        fields.append("reference = ?")
        params.append(str(reference).strip() or None)
        changes["reference"] = {"old": old.get("reference"), "new": reference}

    if notes is not None:
        fields.append("notes = ?")
        params.append(str(notes).strip() or None)
        changes["notes"] = {"old": old.get("notes"), "new": notes}

    if not fields:
        return False

    params.append(int(payment_id))
    try:
        execute(f"UPDATE payments SET {', '.join(fields)} WHERE id = ?", tuple(params))
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث الدفعة %s: %s", payment_id, exc)
        raise ValueError("تعذر تحديث الدفعة") from exc

    log_audit("UPDATE", "payments", payment_id, changes, {"id": payment_id})
    cache.invalidate_prefix("farms:")
    cache.invalidate_prefix("inventory")
    return True


def delete_payment(payment_id: int) -> bool:
    """يحذف دفعة نهائياً."""
    old = get_payment(payment_id)
    if not old:
        return False
    execute("DELETE FROM payments WHERE id = ?", (int(payment_id),))
    log_audit(
        "DELETE",
        "payments",
        payment_id,
        {
            "farm_name": old.get("farm_name"),
            "amount": old.get("amount"),
            "payment_date": old.get("payment_date"),
        },
        None,
    )
    cache.invalidate_prefix("farms:")
    cache.invalidate_prefix("inventory")
    return True
