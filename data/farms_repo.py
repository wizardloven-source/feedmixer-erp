"""
data/farms_repo.py
------------------
مستودع المزارع (CRUD + أرشفة).

قواعد:
- الاسم فريد (يُتحقق قبل الإدراج برسالة عربية واضحة).
- لا يُحذف نهائياً مزرعة لها فواتير/مدفوعات (استخدم الأرشفة).
- كل عملية كتابة تُسجَّل في audit_log وتُبطل كاش المزارع.
"""

from __future__ import annotations

from core import cache
from core.logger import get_logger, log_audit
from core.utils import safe_float
from data.connection import execute, query_all, query_one

_log = get_logger("mixer.farms_repo")


# ============================================================
# القراءة
# ============================================================

def list_farms(include_archived: bool = False) -> list[dict]:
    """قائمة المزارع مرتّبة بالاسم (النشطة فقط افتراضياً)."""
    sql = "SELECT * FROM farms"
    if not include_archived:
        sql += " WHERE is_archived = 0"
    sql += " ORDER BY name COLLATE NOCASE"
    return query_all(sql)


def get_farm(farm_id: int) -> dict | None:
    """مزرعة بالمعرّف."""
    return query_one("SELECT * FROM farms WHERE id = ?", (int(farm_id),))


def get_farm_by_name(name: str) -> dict | None:
    """مزرعة بالاسم (مقارنة دقيقة)."""
    return query_one("SELECT * FROM farms WHERE name = ?", (str(name or "").strip(),))


def farm_transaction_count(name: str) -> dict[str, int]:
    """
    عدد الارتباطات المالية والمرجعية للمزرعة (كل الحالات).

    تحصين المرحلة 4: كانت الدالة تعيد عدداً صحيحاً لمجموع الفواتير +
    المدفوعات فقط، ولا تفحص recipes.farm_name — فيُحذف مزرعة وتبقى
    وصفاتها معلّقة بلا مرجع. الآن يعيد قاموساً:
        {"financial": فواتير + مدفوعات,   ← يمنع الحذف إذا > 0
         "recipes":   عدد الوصفات}        ← يُسمح مع تسجيل audit تحذيري
    """
    text = str(name or "")
    row = query_one(
        "SELECT "
        " (SELECT COUNT(*) FROM mix_invoices WHERE farm_name = ?) + "
        " (SELECT COUNT(*) FROM payments WHERE farm_name = ?) AS financial, "
        " (SELECT COUNT(*) FROM recipes WHERE farm_name = ?) AS recipes",
        (text, text, text),
    )
    data = row or {}
    try:
        financial = int(data.get("financial") or 0)
    except (TypeError, ValueError):
        financial = 0
    try:
        recipes = int(data.get("recipes") or 0)
    except (TypeError, ValueError):
        recipes = 0
    return {"financial": financial, "recipes": recipes}


# ============================================================
# الكتابة
# ============================================================

def add_farm(
    name: str,
    transport_fee: float = 0.0,
    phone: str = "",
    notes: str = "",
) -> int:
    """يضيف مزرعة ويعيد معرّفها. يرفع ValueError عند تكرار الاسم."""
    clean_name = " ".join(str(name or "").split())
    if len(clean_name) < 2:
        raise ValueError("اسم المزرعة مطلوب (حرفان على الأقل)")
    if get_farm_by_name(clean_name):
        raise ValueError(f"اسم المزرعة «{clean_name}» مستخدم بالفعل")

    try:
        cursor = execute(
            "INSERT INTO farms (name, transport_fee, phone, notes) VALUES (?, ?, ?, ?)",
            (
                clean_name,
                max(0.0, safe_float(transport_fee)),
                str(phone or "").strip() or None,
                str(notes or "").strip() or None,
            ),
        )
        farm_id = int(cursor.lastrowid or 0)
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر إضافة المزرعة %s: %s", clean_name, exc)
        raise ValueError("تعذر إضافة المزرعة (قد يكون الاسم مكرراً)") from exc

    log_audit(
        "INSERT",
        "farms",
        farm_id,
        None,
        {
            "name": clean_name,
            "transport_fee": safe_float(transport_fee),
            "phone": phone,
            "notes": notes,
        },
    )
    cache.invalidate_farms()
    return farm_id


def update_farm(
    farm_id: int,
    name: str | None = None,
    transport_fee: float | None = None,
    phone: str | None = None,
    notes: str | None = None,
) -> bool:
    """يُحدّث حقولاً محددة فقط (None = بدون تغيير)."""
    old = get_farm(farm_id)
    if not old:
        raise ValueError("المزرعة غير موجودة")

    fields: list[str] = []
    params: list[object] = []
    changes: dict[str, object] = {}

    if name is not None:
        clean_name = " ".join(str(name).split())
        if len(clean_name) < 2:
            raise ValueError("اسم المزرعة مطلوب (حرفان على الأقل)")
        duplicate = get_farm_by_name(clean_name)
        if duplicate and int(duplicate["id"]) != int(farm_id):
            raise ValueError(f"اسم المزرعة «{clean_name}» مستخدم بالفعل")
        fields.append("name = ?")
        params.append(clean_name)
        changes["name"] = clean_name

    if transport_fee is not None:
        fee = max(0.0, safe_float(transport_fee))
        fields.append("transport_fee = ?")
        params.append(fee)
        changes["transport_fee"] = fee

    if phone is not None:
        fields.append("phone = ?")
        params.append(str(phone).strip() or None)
        changes["phone"] = phone

    if notes is not None:
        fields.append("notes = ?")
        params.append(str(notes).strip() or None)
        changes["notes"] = notes

    if not fields:
        return False

    params.append(int(farm_id))
    try:
        execute(f"UPDATE farms SET {', '.join(fields)} WHERE id = ?", tuple(params))
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث المزرعة %s: %s", farm_id, exc)
        raise ValueError("تعذر تحديث المزرعة") from exc

    log_audit(
        "UPDATE",
        "farms",
        farm_id,
        {key: old.get(key) for key in changes},
        changes,
    )
    cache.invalidate_farms()
    return True


def archive_farm(farm_id: int, archived: bool = True) -> bool:
    """يؤرشف/يُعيد تنشيط مزرعة (الأرشفة تُخفيها من القوائم)."""
    old = get_farm(farm_id)
    if not old:
        raise ValueError("المزرعة غير موجودة")
    if bool(old.get("is_archived")) == bool(archived):
        return False
    execute(
        "UPDATE farms SET is_archived = ? WHERE id = ?",
        (1 if archived else 0, int(farm_id)),
    )
    log_audit(
        "UPDATE",
        "farms",
        farm_id,
        {"is_archived": int(old.get("is_archived") or 0)},
        {"is_archived": 1 if archived else 0},
    )
    cache.invalidate_farms()
    return True


def delete_farm(farm_id: int) -> bool:
    """
    يحذف مزرعة بلا حركات مالية فقط.
    يرفع ValueError إذا كانت مرتبطة بفواتير/مدفوعات (استخدم الأرشفة).

    تحصين المرحلة 4: الوصفات (recipes.farm_name نصية بلا FK) لا تمنع
    الحذف — بل يُسمح به مع تسجيل تحذير في audit_log لتتبع البيانات
    المعلّقة، لأن منعها يعيق المستخدم دون مكسب سلامة فعلي.
    """
    old = get_farm(farm_id)
    if not old:
        return False
    name = str(old.get("name") or "")
    counts = farm_transaction_count(name)
    if counts["financial"] > 0:
        raise ValueError(
            f"لا يمكن حذف «{name}» لوجود فواتير أو مدفوعات مرتبطة بها. استخدم الأرشفة."
        )
    execute("DELETE FROM farms WHERE id = ?", (int(farm_id),))
    audit_details: dict[str, object] = {"name": name}
    if counts["recipes"] > 0:
        # بيانات مرجعية معلّقة مقبولة — تُسجَّل للمساءلة فقط
        audit_details["orphaned_recipes"] = counts["recipes"]
        _log.warning("حذف مزرعة «%s» ولها %d وصفة أصبحت معلّقة", name, counts["recipes"])
    log_audit("DELETE", "farms", farm_id, {"name": name}, audit_details)
    cache.invalidate_farms()
    return True


def set_transport_fee(name: str, fee: float) -> bool:
    """تحديث سريع لأجرة النقل بالاسم (من شاشة الخلطة)."""
    farm = get_farm_by_name(name)
    if not farm:
        return False
    return update_farm(int(farm["id"]), transport_fee=fee)
