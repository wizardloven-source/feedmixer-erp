"""
data/materials_repo.py
----------------------
مستودع المواد (CRUD + منع حذف مادة مستخدمة).

الوحدات المدعومة: ton / kg / fixed (راجع config.settings.UNIT_TYPES).

قواعد:
- الاسم فريد.
- لا يُحذف نهائياً مادة مستخدمة في purchases / mix_items / recipe_items.
- تحديث السعر من آخر توريد (اختياري) عبر update_price_from_purchase.
"""

from __future__ import annotations

from core import cache
from core.logger import get_logger, log_audit
from core.utils import safe_float
from data.connection import execute, query_all, query_one
from config import settings

_log = get_logger("mixer.materials_repo")


# ============================================================
# القراءة
# ============================================================

def list_materials() -> list[dict]:
    """كل المواد مرتّبة بالاسم."""
    return query_all("SELECT * FROM materials ORDER BY name COLLATE NOCASE")


def get_material(material_id: int) -> dict | None:
    """مادة بالمعرّف."""
    return query_one("SELECT * FROM materials WHERE id = ?", (int(material_id),))


def get_material_by_name(name: str) -> dict | None:
    """مادة بالاسم."""
    return query_one(
        "SELECT * FROM materials WHERE name = ?", (str(name or "").strip(),)
    )


def material_usage(name: str) -> dict[str, int]:
    """أين تُستخدم المادة؟ (عدد السطور في كل جدول)."""
    row = query_one(
        "SELECT "
        " (SELECT COUNT(*) FROM purchases WHERE material_name = ?) AS purchases, "
        " (SELECT COUNT(*) FROM mix_items WHERE material_name = ?) AS mix_items, "
        " (SELECT COUNT(*) FROM recipe_items WHERE material_name = ?) AS recipe_items",
        (str(name or ""), str(name or ""), str(name or "")),
    )
    result = {"purchases": 0, "mix_items": 0, "recipe_items": 0}
    if row:
        for key in result:
            try:
                result[key] = int(row.get(key) or 0)
            except (TypeError, ValueError):
                result[key] = 0
    return result


def is_material_used(name: str) -> bool:
    """هل المادة مستخدمة في أي حركة/وصفة؟"""
    usage = material_usage(name)
    return any(value > 0 for value in usage.values())


# ============================================================
# الكتابة
# ============================================================

def _clean_unit(unit_type: str | None) -> str:
    unit = str(unit_type or "ton").strip()
    if unit not in settings.UNIT_TYPES:
        raise ValueError("نوع الوحدة غير صالح (ton / kg / fixed)")
    return unit


def add_material(
    name: str,
    base_price: float = 0.0,
    handling_fee: float = 0.0,
    loss_fee: float = 0.0,
    unit_type: str = "ton",
) -> int:
    """يضيف مادة ويعيد معرّفها."""
    clean_name = " ".join(str(name or "").split())
    if len(clean_name) < 1:
        raise ValueError("اسم المادة مطلوب")
    if get_material_by_name(clean_name):
        raise ValueError(f"اسم المادة «{clean_name}» مستخدم بالفعل")
    unit = _clean_unit(unit_type)

    try:
        cursor = execute(
            "INSERT INTO materials (name, base_price, handling_fee, loss_fee, unit_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                clean_name,
                max(0.0, safe_float(base_price)),
                max(0.0, safe_float(handling_fee)),
                max(0.0, safe_float(loss_fee)),
                unit,
            ),
        )
        material_id = int(cursor.lastrowid or 0)
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر إضافة المادة %s: %s", clean_name, exc)
        raise ValueError("تعذر إضافة المادة (قد يكون الاسم مكرراً)") from exc

    log_audit(
        "INSERT",
        "materials",
        material_id,
        None,
        {
            "name": clean_name,
            "base_price": safe_float(base_price),
            "handling_fee": safe_float(handling_fee),
            "loss_fee": safe_float(loss_fee),
            "unit_type": unit,
        },
    )
    cache.invalidate_materials()
    return material_id


def update_material(
    material_id: int,
    name: str | None = None,
    base_price: float | None = None,
    handling_fee: float | None = None,
    loss_fee: float | None = None,
    unit_type: str | None = None,
) -> bool:
    """تحديث جزئي للمادة (None = بدون تغيير)."""
    old = get_material(material_id)
    if not old:
        raise ValueError("المادة غير موجودة")

    fields: list[str] = []
    params: list[object] = []
    changes: dict[str, object] = {}

    if name is not None:
        clean_name = " ".join(str(name).split())
        if not clean_name:
            raise ValueError("اسم المادة مطلوب")
        duplicate = get_material_by_name(clean_name)
        if duplicate and int(duplicate["id"]) != int(material_id):
            raise ValueError(f"اسم المادة «{clean_name}» مستخدم بالفعل")
        fields.append("name = ?")
        params.append(clean_name)
        changes["name"] = clean_name

    for column, value in (
        ("base_price", base_price),
        ("handling_fee", handling_fee),
        ("loss_fee", loss_fee),
    ):
        if value is not None:
            numeric = max(0.0, safe_float(value))
            fields.append(f"{column} = ?")
            params.append(numeric)
            changes[column] = numeric

    if unit_type is not None:
        unit = _clean_unit(unit_type)
        fields.append("unit_type = ?")
        params.append(unit)
        changes["unit_type"] = unit

    if not fields:
        return False

    params.append(int(material_id))
    try:
        execute(f"UPDATE materials SET {', '.join(fields)} WHERE id = ?", tuple(params))
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث المادة %s: %s", material_id, exc)
        raise ValueError("تعذر تحديث المادة") from exc

    log_audit(
        "UPDATE",
        "materials",
        material_id,
        {key: old.get(key) for key in changes},
        changes,
    )
    cache.invalidate_materials()
    return True


def update_price_from_purchase(name: str, real_price_per_ton: float) -> bool:
    """
    يحدّث السعر الأساسي للمادة من السعر الحقيقي/طن لتوريد جديد
    (يُستخدم عند تفعيل auto_update_price_from_purchase).
    """
    material = get_material_by_name(name)
    if not material:
        return False
    price = max(0.0, safe_float(real_price_per_ton))
    return update_material(
        int(material["id"]),
        base_price=price,
        handling_fee=0.0,
        loss_fee=0.0,
    )


def delete_material(material_id: int) -> bool:
    """
    يحذف مادة غير مستخدمة. يرفع ValueError إذا كانت مستخدمة
    (حفاظاً على سلامة الفواتير والتوريدات والوصفات).
    """
    old = get_material(material_id)
    if not old:
        return False
    name = str(old.get("name") or "")
    usage = material_usage(name)
    if any(value > 0 for value in usage.values()):
        parts = []
        if usage["purchases"]:
            parts.append(f"{usage['purchases']} توريد")
        if usage["mix_items"]:
            parts.append(f"{usage['mix_items']} سطر خلطة")
        if usage["recipe_items"]:
            parts.append(f"{usage['recipe_items']} سطر وصفة")
        raise ValueError(
            f"لا يمكن حذف «{name}» لأنها مستخدمة في: {'، '.join(parts)}"
        )
    execute("DELETE FROM materials WHERE id = ?", (int(material_id),))
    log_audit("DELETE", "materials", material_id, {"name": name}, None)
    cache.invalidate_materials()
    return True
