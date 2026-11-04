"""
data/purchases_repo.py
----------------------
مستودع التوريدات (purchases) مع حساب التكاليف تلقائياً واستيراد CSV.

الصيغة المحاسبية:
    fees_total   = unloading + handling + transport + other
    total_cost   = price_per_ton * qty_ton + fees_total
    real_price_per_ton = total_cost / qty_ton (إن وُجد وزن)

عند تفعيل auto_update_price_from_purchase يُحدّث سعر المادة الأساسية من التوريد الجديد.
"""

from __future__ import annotations

import csv
from typing import Any

from core import cache
from core.logger import get_logger, log_audit
from core.utils import safe_float
from core.validators import validate_date, validate_name, validate_number
from data.connection import execute, query_all, query_one, transaction
from data import materials_repo

_log = get_logger("mixer.purchases_repo")

_FEE_COLUMNS = (
    "unloading_fee",
    "handling_fee",
    "transport_fee",
    "other_fees",
)


def _compute_purchase_totals(qty_ton: float, price_per_ton: float, fees: dict[str, float]) -> dict[str, float]:
    """يحسب fees_total و total_cost و real_price_per_ton."""
    qty = max(0.0, safe_float(qty_ton))
    price = max(0.0, safe_float(price_per_ton))
    fee_vals = {col: max(0.0, safe_float(fees.get(col))) for col in _FEE_COLUMNS}
    fees_total = sum(fee_vals.values())
    total_cost = round(price * qty + fees_total, 2)
    real_price = round(total_cost / qty, 4) if qty > 0 else 0.0
    return {
        "qty_ton": round(qty, 3),
        "price_per_ton": round(price, 2),
        "unloading_fee": fee_vals["unloading_fee"],
        "handling_fee": fee_vals["handling_fee"],
        "transport_fee": fee_vals["transport_fee"],
        "other_fees": fee_vals["other_fees"],
        "fees_total": round(fees_total, 2),
        "total_cost": round(total_cost, 2),
        "real_price_per_ton": round(real_price, 4),
    }


# ============================================================
# القراءة
# ============================================================

def list_purchases(
    search: str | None = None,
    material: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """قائمة التوريدات مع فلاتر بحث وتاريخ، أحدث أولاً."""
    sql = "SELECT * FROM purchases WHERE 1=1"
    params: list[Any] = []
    if search:
        like = f"%{search.strip()}%"
        sql += " AND (material_name LIKE ? OR supplier LIKE ? OR details LIKE ?)"
        params.extend([like, like, like])
    if material:
        sql += " AND material_name = ?"
        params.append(material)
    if date_from:
        sql += " AND purchase_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND purchase_date <= ?"
        params.append(date_to)
    sql += " ORDER BY purchase_date DESC, id DESC"
    return query_all(sql, tuple(params))


def get_purchase(purchase_id: int) -> dict | None:
    """توريد بالمعرّف."""
    return query_one("SELECT * FROM purchases WHERE id = ?", (int(purchase_id),))


def get_purchases_by_material(material_name: str) -> list[dict]:
    """كل توريدات مادة معينة (لحساب المخزون)."""
    return query_all(
        "SELECT * FROM purchases WHERE material_name = ? ORDER BY purchase_date ASC, id ASC",
        (str(material_name or ""),),
    )


# ============================================================
# الكتابة
# ============================================================

def add_purchase(
    purchase_date: str,
    material_name: str,
    qty_ton: float,
    supplier: str = "",
    details: str = "",
    price_per_ton: float = 0.0,
    unloading_fee: float = 0.0,
    handling_fee: float = 0.0,
    transport_fee: float = 0.0,
    other_fees: float = 0.0,
    created_by: str | None = None,
) -> int:
    """
    يضيف توريد جديد مع حساب تلقائي للتكاليف.
    يُحدّث سعر المادة إن كان الإعداد مفعلاً.
    يعيد معرّف التوريد.
    """
    date_text = validate_date(purchase_date, "تاريخ التوريد")
    clean_material = validate_name(material_name, "اسم المادة", min_length=1)
    qty = validate_number(qty_ton, "الكمية", minimum=0.001)
    price = validate_number(price_per_ton, "سعر الطن", minimum=0.0)
    fees = {
        "unloading_fee": validate_number(unloading_fee, "رسوم تنزيل", minimum=0.0),
        "handling_fee": validate_number(handling_fee, "عتالة", minimum=0.0),
        "transport_fee": validate_number(transport_fee, "نقل", minimum=0.0),
        "other_fees": validate_number(other_fees, "أخرى", minimum=0.0),
    }

    totals = _compute_purchase_totals(qty, price, fees)

    try:
        with transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO purchases "
                "(purchase_date, material_name, qty_ton, supplier, details, "
                "price_per_ton, total_cost, unloading_fee, handling_fee, "
                "transport_fee, other_fees, fees_total, real_price_per_ton) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    date_text,
                    clean_material,
                    totals["qty_ton"],
                    str(supplier or "").strip() or None,
                    str(details or "").strip() or None,
                    totals["price_per_ton"],
                    totals["total_cost"],
                    totals["unloading_fee"],
                    totals["handling_fee"],
                    totals["transport_fee"],
                    totals["other_fees"],
                    totals["fees_total"],
                    totals["real_price_per_ton"],
                ),
            )
            purchase_id = int(cursor.lastrowid or 0)
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر إضافة التوريد: %s", exc)
        raise ValueError("تعذر إضافة التوريد") from exc

    log_audit(
        "INSERT",
        "purchases",
        purchase_id,
        None,
        {
            "purchase_date": date_text,
            "material_name": clean_material,
            "qty_ton": totals["qty_ton"],
            "total_cost": totals["total_cost"],
            "real_price_per_ton": totals["real_price_per_ton"],
        },
        user=created_by,
    )
    cache.invalidate_materials()
    cache.invalidate_prefix("inventory")

    # تحديث سعر المادة تلقائياً إن كان الإعداد مفعلاً
    if cache.setting("auto_update_price_from_purchase", force=True) >= 1:
        try:
            materials_repo.update_price_from_purchase(clean_material, totals["real_price_per_ton"])
        except Exception as exc:  # noqa: BLE001
            _log.warning("تعذر تحديث سعر المادة تلقائياً: %s", exc)

    return purchase_id


def update_purchase(
    purchase_id: int,
    purchase_date: str | None = None,
    material_name: str | None = None,
    qty_ton: float | None = None,
    supplier: str | None = None,
    details: str | None = None,
    price_per_ton: float | None = None,
    unloading_fee: float | None = None,
    handling_fee: float | None = None,
    transport_fee: float | None = None,
    other_fees: float | None = None,
) -> bool:
    """تحديث جزئي للتوريد مع إعادة حساب التكاليف."""
    old = get_purchase(purchase_id)
    if not old:
        raise ValueError("التوريد غير موجود")

    new_date = validate_date(purchase_date, "تاريخ التوريد") if purchase_date is not None else str(old.get("purchase_date") or "")
    new_material = validate_name(material_name, "اسم المادة", min_length=1) if material_name is not None else str(old.get("material_name") or "")
    new_qty = validate_number(qty_ton, "الكمية", minimum=0.001) if qty_ton is not None else safe_float(old.get("qty_ton"))
    new_price = validate_number(price_per_ton, "سعر الطن", minimum=0.0) if price_per_ton is not None else safe_float(old.get("price_per_ton"))

    fees_input: dict[str, float] = {}
    if unloading_fee is not None:
        fees_input["unloading_fee"] = validate_number(unloading_fee, "رسوم تنزيل", minimum=0.0)
    if handling_fee is not None:
        fees_input["handling_fee"] = validate_number(handling_fee, "عتالة", minimum=0.0)
    if transport_fee is not None:
        fees_input["transport_fee"] = validate_number(transport_fee, "نقل", minimum=0.0)
    if other_fees is not None:
        fees_input["other_fees"] = validate_number(other_fees, "أخرى", minimum=0.0)

    merged_fees = {col: fees_input.get(col, safe_float(old.get(col))) for col in _FEE_COLUMNS}
    totals = _compute_purchase_totals(new_qty, new_price, merged_fees)

    fields: list[str] = []
    params: list[Any] = []
    changes: dict[str, Any] = {}

    mapped: dict[str, Any] = {
        "purchase_date": new_date,
        "material_name": new_material,
        "qty_ton": totals["qty_ton"],
        "supplier": str(supplier).strip() if supplier is not None else old.get("supplier"),
        "details": str(details).strip() if details is not None else old.get("details"),
        "price_per_ton": totals["price_per_ton"],
        "total_cost": totals["total_cost"],
        "unloading_fee": totals["unloading_fee"],
        "handling_fee": totals["handling_fee"],
        "transport_fee": totals["transport_fee"],
        "other_fees": totals["other_fees"],
        "fees_total": totals["fees_total"],
        "real_price_per_ton": totals["real_price_per_ton"],
    }

    for col, new_val in mapped.items():
        old_val = old.get(col)
        if col in ("price_per_ton", "total_cost", "fees_total", "real_price_per_ton", "qty_ton"):
            new_val = round(safe_float(new_val), 4)
            old_val = round(safe_float(old_val), 4)
        if str(new_val) != str(old_val):
            fields.append(f"{col} = ?")
            params.append(new_val)
            changes[col] = {"old": old_val, "new": new_val}

    if not fields:
        return False

    params.append(int(purchase_id))
    try:
        execute(f"UPDATE purchases SET {', '.join(fields)} WHERE id = ?", tuple(params))
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث التوريد %s: %s", purchase_id, exc)
        raise ValueError("تعذر تحديث التوريد") from exc

    log_audit("UPDATE", "purchases", purchase_id, changes, {"id": purchase_id})
    cache.invalidate_materials()
    cache.invalidate_prefix("inventory")
    return True


def delete_purchase(purchase_id: int) -> bool:
    """يحذف توريد نهائياً إن لم تكن المادة مستخدمة في خلطات غير محذوفة."""
    old = get_purchase(purchase_id)
    if not old:
        return False
    name = str(old.get("material_name") or "")
    used = query_one(
        "SELECT COUNT(*) AS c FROM mix_items mi "
        "JOIN mix_invoices m ON mi.mix_number = m.mix_number "
        "WHERE mi.material_name = ? AND m.is_deleted = 0",
        (name,),
    )
    try:
        used_count = int((used or {}).get("c") or 0)
    except (TypeError, ValueError):
        used_count = 0
    if used_count > 0:
        raise ValueError(
            f"لا يمكن حذف التوريد لأن المادة «{name}» مستخدمة في {used_count} سطر خلطة"
        )
    execute("DELETE FROM purchases WHERE id = ?", (int(purchase_id),))
    log_audit(
        "DELETE",
        "purchases",
        purchase_id,
        {"material_name": name, "qty_ton": old.get("qty_ton"), "total_cost": old.get("total_cost")},
        None,
    )
    cache.invalidate_materials()
    cache.invalidate_prefix("inventory")
    return True


# ============================================================
# استيراد CSV
# ============================================================

def import_csv(file_path: str, created_by: str | None = None) -> dict[str, int]:
    """
    يستورد توريدات من ملف CSV.
    الأعمدة المتوقعة: purchase_date, material_name, qty_ton, supplier,
    details, price_per_ton, unloading_fee, handling_fee, transport_fee, other_fees
    يعيد ملخص: imported, skipped, errors.
    """
    imported = 0
    skipped = 0
    errors: list[str] = []

    try:
        with open(file_path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row_num, row in enumerate(reader, start=2):
                try:
                    add_purchase(
                        purchase_date=row.get("purchase_date", ""),
                        material_name=row.get("material_name", ""),
                        qty_ton=row.get("qty_ton", "0"),
                        supplier=row.get("supplier", ""),
                        details=row.get("details", ""),
                        price_per_ton=row.get("price_per_ton", "0"),
                        unloading_fee=row.get("unloading_fee", "0"),
                        handling_fee=row.get("handling_fee", "0"),
                        transport_fee=row.get("transport_fee", "0"),
                        other_fees=row.get("other_fees", "0"),
                        created_by=created_by,
                    )
                    imported += 1
                except (ValueError, KeyError) as exc:
                    skipped += 1
                    errors.append(f"السطر {row_num}: {exc}")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"الملف غير موجود: {file_path}") from exc
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل استيراد CSV: %s", exc)
        raise ValueError(f"فشل فتح الملف: {exc}") from exc

    return {"imported": imported, "skipped": skipped, "errors": errors}


def export_csv_template() -> str:
    """يعيد نص رأس أعمدة CSV للتوريدات."""
    return (
        "purchase_date,material_name,qty_ton,supplier,details,"
        "price_per_ton,unloading_fee,handling_fee,transport_fee,other_fees\n"
    )
