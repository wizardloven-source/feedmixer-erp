"""
data/recipes_repo.py
--------------------
مستودع الوصفات الجاهزة (recipes + recipe_items).

- حفظ مجموعة مكونات باسم وتطبيقها على شاشة الخلطة.
- نسخ وصفة موجودة.
- منع حذف وصفة غير موجودة فقط (الوصفات قابلة للحذف حتى لو استُخدمت،
  لأن الفاتورة تحتفظ بنسخة من البنود وليس رابطاً حياً).
"""

from __future__ import annotations

from typing import Any

from core import cache
from core.logger import get_logger, log_audit
from core.validators import validate_name, validate_number
from data.connection import execute, query_all, query_one, transaction

_log = get_logger("mixer.recipes_repo")


# ============================================================
# القراءة
# ============================================================

def list_recipes() -> list[dict]:
    """كل الوصفات مرتّبة بالاسم."""
    return query_all("SELECT * FROM recipes ORDER BY name COLLATE NOCASE")


def get_recipe(recipe_id: int) -> dict | None:
    """وصفة بالمعرّف مع بنودها."""
    recipe = query_one("SELECT * FROM recipes WHERE id = ?", (int(recipe_id),))
    if not recipe:
        return None
    items = query_all(
        "SELECT * FROM recipe_items WHERE recipe_id = ? ORDER BY id ASC",
        (int(recipe_id),),
    )
    recipe["items"] = items
    return recipe


def get_recipe_by_name(name: str) -> dict | None:
    """وصفة بالاسم."""
    return query_one("SELECT * FROM recipes WHERE name = ?", (str(name or "").strip(),))


# ============================================================
# الكتابة
# ============================================================

def _validate_recipe_items(items: list[dict]) -> list[dict]:
    """يتحقق من بنود الوصفة ويعيدها مطوّرة."""
    if not items:
        raise ValueError("يجب إضافة مكون واحد على الأقل للوصفة")
    material_names = cache.material_names()
    cleaned: list[dict] = []
    for idx, item in enumerate(items, start=1):
        name = validate_name(item.get("material_name"), f"المكون في السطر {idx}", min_length=1)
        if name not in material_names:
            raise ValueError(f"المادة «{name}» غير موجودة (السطر {idx})")
        qty = validate_number(item.get("qty_kg"), f"كمية السطر {idx}", minimum=0.001)
        cleaned.append({"material_name": name, "qty_kg": round(qty, 3)})
    return cleaned


def add_recipe(
    name: str,
    farm_name: str = "",
    notes: str = "",
    items: list[dict] | None = None,
) -> int:
    """
    يضيف وصفة جديدة مع بنودها ويعيد معرّفها.
    """
    clean_name = validate_name(name, "اسم الوصفة", min_length=1)
    if get_recipe_by_name(clean_name):
        raise ValueError(f"اسم الوصفة «{clean_name}» مستخدم بالفعل")

    cleaned_items = _validate_recipe_items(items or [])

    try:
        with transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO recipes (name, farm_name, notes) VALUES (?, ?, ?)",
                (clean_name, str(farm_name or "").strip() or None, str(notes or "").strip() or None),
            )
            recipe_id = int(cursor.lastrowid or 0)
            for item in cleaned_items:
                conn.execute(
                    "INSERT INTO recipe_items (recipe_id, material_name, qty_kg) VALUES (?, ?, ?)",
                    (recipe_id, item["material_name"], item["qty_kg"]),
                )
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر إضافة الوصفة %s: %s", clean_name, exc)
        raise ValueError("تعذر إضافة الوصفة") from exc

    log_audit(
        "INSERT",
        "recipes",
        recipe_id,
        None,
        {"name": clean_name, "farm_name": farm_name, "items_count": len(cleaned_items)},
    )
    return recipe_id


def update_recipe(
    recipe_id: int,
    name: str | None = None,
    farm_name: str | None = None,
    notes: str | None = None,
    items: list[dict] | None = None,
) -> bool:
    """تحديث وصفة موجودة (تستبدل البنود إذا أُرسلت)."""
    old = get_recipe(recipe_id)
    if not old:
        raise ValueError("الوصفة غير موجودة")

    fields: list[str] = []
    params: list[Any] = []
    changes: dict[str, Any] = {}

    if name is not None:
        clean_name = validate_name(name, "اسم الوصفة", min_length=1)
        duplicate = get_recipe_by_name(clean_name)
        if duplicate and int(duplicate["id"]) != int(recipe_id):
            raise ValueError(f"اسم الوصفة «{clean_name}» مستخدم بالفعل")
        fields.append("name = ?")
        params.append(clean_name)
        changes["name"] = {"old": old.get("name"), "new": clean_name}

    if farm_name is not None:
        fields.append("farm_name = ?")
        params.append(str(farm_name).strip() or None)
        changes["farm_name"] = {"old": old.get("farm_name"), "new": farm_name}

    if notes is not None:
        fields.append("notes = ?")
        params.append(str(notes).strip() or None)
        changes["notes"] = {"old": old.get("notes"), "new": notes}

    try:
        with transaction() as conn:
            if fields:
                params.append(int(recipe_id))
                conn.execute(f"UPDATE recipes SET {', '.join(fields)} WHERE id = ?", tuple(params))
            if items is not None:
                cleaned_items = _validate_recipe_items(items)
                conn.execute("DELETE FROM recipe_items WHERE recipe_id = ?", (int(recipe_id),))
                for item in cleaned_items:
                    conn.execute(
                        "INSERT INTO recipe_items (recipe_id, material_name, qty_kg) VALUES (?, ?, ?)",
                        (int(recipe_id), item["material_name"], item["qty_kg"]),
                    )
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث الوصفة %s: %s", recipe_id, exc)
        raise ValueError("تعذر تحديث الوصفة") from exc

    log_audit("UPDATE", "recipes", recipe_id, changes, {"id": recipe_id})
    return True


def copy_recipe(recipe_id: int, new_name: str) -> int:
    """
    ينسخ وصفة موجودة باسم جديد ويعيد معرّف النسخة.
    """
    old = get_recipe(recipe_id)
    if not old:
        raise ValueError("الوصفة الأصلية غير موجودة")
    return add_recipe(
        name=new_name,
        farm_name=old.get("farm_name") or "",
        notes=old.get("notes") or "",
        items=old.get("items", []),
    )


def delete_recipe(recipe_id: int) -> bool:
    """يحذف وصفاً وبنودها (CASCADE)."""
    old = get_recipe(recipe_id)
    if not old:
        return False
    execute("DELETE FROM recipes WHERE id = ?", (int(recipe_id),))
    log_audit(
        "DELETE",
        "recipes",
        recipe_id,
        {"name": old.get("name")},
        None,
    )
    return True
