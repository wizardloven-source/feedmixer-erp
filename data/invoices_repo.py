"""
data/invoices_repo.py
---------------------
مستودع الخلطات / الفواتير (mix_invoices + mix_items).

الصيغة المحاسبية (راجع core.utils):
    billable_tons = int((total_weight_kg + 249) / 500) * 0.5
    feed_cost     = Σ (qty_kg * unit_price)
    elec_fee      = إعداد الكهرباء
    labor_fee     = billable_tons * إعداد أجرة العمال
    transport     = أجرة النقل للمزرعة المختارة
    total_cost    = feed_cost + elec_fee + labor_fee + transport
    mixer_net_cost= total_cost (إلا إذا تم تعديل الصافي يدوياً)

الخلطة تُحفظ ذرّياً: الفاتورة + كل عناصرها في معاملة واحدة.
soft delete: is_deleted + deleted_at (لا يُحذف نهائياً إلا للصيانة).
"""

from __future__ import annotations

from typing import Any

from core import cache
from core.logger import get_logger, log_audit
from core.utils import calc_billable_tons, kg_to_tons, safe_float, safe_int
from core.validators import validate_date, validate_name, validate_number
from data.connection import execute, query_all, query_one, transaction
from data import materials_repo, farms_repo

_log = get_logger("mixer.invoices_repo")


# ============================================================
# رقم الفاتورة التلقائي
# ============================================================

def _next_mix_number(mix_date: str) -> str:
    """
    يولّد رقم خلطة فريد بالصيغة: MIX-YYYYMMDD-NNNN
    بناءً على أكبر رقم موجود في نفس اليوم.
    """
    date_part = mix_date.replace("-", "")
    row = query_one(
        "SELECT mix_number FROM mix_invoices "
        "WHERE mix_number LIKE ? ORDER BY mix_number DESC LIMIT 1",
        (f"MIX-{date_part}-%",),
    )
    seq = 1
    if row:
        try:
            last = str(row["mix_number"]).rsplit("-", 1)[-1]
            seq = int(last) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"MIX-{date_part}-{seq:04d}"


# ============================================================
# القراءة
# ============================================================

def list_invoices(
    include_deleted: bool = False,
    search: str | None = None,
    farm: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    payment_status: str | None = None,
) -> list[dict]:
    """قائمة الفواتير مع فلاتر (الأساسية تُستبعد المكشوفة محذوفاً افتراضياً)."""
    sql = "SELECT * FROM mix_invoices WHERE 1=1"
    params: list[Any] = []
    if not include_deleted:
        sql += " AND (is_deleted = 0 OR is_deleted IS NULL)"
    if search:
        like = f"%{search.strip()}%"
        sql += " AND (mix_number LIKE ? OR farm_name LIKE ? OR worker_name LIKE ? OR notes LIKE ?)"
        params.extend([like, like, like, like])
    if farm:
        sql += " AND farm_name = ?"
        params.append(farm)
    if date_from:
        sql += " AND mix_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND mix_date <= ?"
        params.append(date_to)
    if payment_status:
        sql += " AND payment_status = ?"
        params.append(payment_status)
    sql += " ORDER BY mix_date DESC, mix_number DESC"
    return query_all(sql, tuple(params))


def get_invoice(mix_number: str) -> dict | None:
    """فاتورة بالمعرف مع بنودها."""
    invoice = query_one("SELECT * FROM mix_invoices WHERE mix_number = ?", (str(mix_number),))
    if not invoice:
        return None
    items = query_all(
        "SELECT * FROM mix_items WHERE mix_number = ? ORDER BY id ASC",
        (str(mix_number),),
    )
    invoice["items"] = items
    return invoice


def get_invoice_by_id(invoice_id: int) -> dict | None:
    """فاتورة بالمعرف الداخلي."""
    row = query_one("SELECT * FROM mix_invoices WHERE id = ?", (int(invoice_id),))
    if not row:
        return None
    items = query_all(
        "SELECT * FROM mix_items WHERE mix_number = ? ORDER BY id ASC",
        (str(row["mix_number"]),),
    )
    row["items"] = items
    return row


def get_deleted_invoices() -> list[dict]:
    """كل الفواتير المحذوفة ناعماً (للسلة)."""
    return query_all(
        "SELECT * FROM mix_invoices WHERE is_deleted = 1 ORDER BY deleted_at DESC, mix_number DESC"
    )


# ============================================================
# المساعدة المحاسبية
# ============================================================

def _compute_invoice_totals(
    items: list[dict],
    farm_name: str,
    electricity_fee: float,
    labor_fee_per_ton: float,
) -> dict[str, float]:
    """
    يحسب تكاليف الخلطة من البنود والإعدادات.
    """
    feed_cost = 0.0
    total_weight_kg = 0.0
    for item in items:
        qty = safe_float(item.get("qty_kg"))
        price = safe_float(item.get("unit_price"))
        total_weight_kg += qty
        feed_cost += qty * price

    billable = calc_billable_tons(total_weight_kg)
    labor = billable * safe_float(labor_fee_per_ton)
    transport = 0.0
    farm = farms_repo.get_farm_by_name(farm_name)
    if farm:
        transport = safe_float(farm.get("transport_fee"))

    total_cost = round(feed_cost + safe_float(electricity_fee) + labor + transport, 2)
    return {
        "total_weight": round(total_weight_kg, 3),
        "feed_cost": round(feed_cost, 2),
        "elec_fee": round(safe_float(electricity_fee), 2),
        "labor_fee": round(labor, 2),
        "transport_fee": round(transport, 2),
        "billable_tons": billable,
        "total_cost": total_cost,
    }


def _validate_items(items: list[dict]) -> list[dict]:
    """يتحقق من البنود ويعيدها مطوّرة، يرفع ValueError عند خطأ."""
    if not items:
        raise ValueError("يجب إضافة مادة واحدة على الأقل للخلطة")
    material_names = cache.material_names()
    cleaned: list[dict] = []
    for idx, item in enumerate(items, start=1):
        name = validate_name(item.get("material_name"), f"المادة في السطر {idx}", min_length=1)
        if name not in material_names:
            raise ValueError(f"المادة «{name}» غير موجودة في قاعدة المواد (السطر {idx})")
        qty = validate_number(item.get("qty_kg"), f"كمية السطر {idx}", minimum=0.001)
        price = validate_number(item.get("unit_price"), f"سعر السطر {idx}", minimum=0.0)
        total = round(qty * price, 2)
        cleaned.append({
            "material_name": name,
            "qty_kg": round(qty, 3),
            "unit_price": round(price, 2),
            "total_price": total,
        })
    return cleaned


def _check_inventory(mix_number: str, items: list[dict], created_by: str | None) -> None:
    """
    يفحص توفر المخزون لكل مادة قبل الحفظ.
    المورد = Σ التوريدات، المستهلك = Σ الخلطات غير المحذوفة (باستثناء الحالية).
    """
    for item in items:
        name = item["material_name"]
        needed_kg = safe_float(item["qty_kg"])
        needed_ton = kg_to_tons(needed_kg)

        supply_rows = query_all(
            "SELECT qty_ton FROM purchases WHERE material_name = ?",
            (name,),
        )
        supply = sum(safe_float(r.get("qty_ton")) for r in supply_rows)

        consumed_rows = query_all(
            "SELECT mi.qty_kg FROM mix_items mi "
            "JOIN mix_invoices m ON mi.mix_number = m.mix_number "
            "WHERE mi.material_name = ? AND (m.is_deleted = 0 OR m.is_deleted IS NULL) "
            "AND m.mix_number <> ?",
            (name, mix_number),
        )
        consumed = sum(kg_to_tons(safe_float(r.get("qty_kg"))) for r in consumed_rows)

        remaining = supply - consumed
        if remaining < needed_ton - 1e-9:
            raise ValueError(
                f"عجز في المخزون للمادة «{name}\": المتاح {remaining:.3f} طن، "
                f"المطلوب {needed_ton:.3f} طن"
            )


# ============================================================
# الكتابة
# ============================================================

def add_invoice(
    mix_date: str,
    farm_name: str,
    worker_name: str = "",
    items: list[dict] | None = None,
    notes: str = "",
    payment_status: str = "unpaid",
    net_cost_override: float | None = None,
    recipe_id: int | None = None,
    created_by: str | None = None,
) -> str:
    """
    يضيف خلطة جديدة ذرية (فاتورة + بنود).
    يعيد mix_number.
    """
    date_text = validate_date(mix_date, "تاريخ الخلطة")
    clean_farm = validate_name(farm_name, "المزرعة", min_length=1)
    if farms_repo.get_farm_by_name(clean_farm) is None:
        raise ValueError(f"المزرعة «{clean_farm}» غير موجودة")

    cleaned_items = _validate_items(items or [])

    electricity_fee = cache.setting("electricity_fee", force=True)
    labor_fee_per_ton = cache.setting("labor_fee_per_ton", force=True)
    totals = _compute_invoice_totals(cleaned_items, clean_farm, electricity_fee, labor_fee_per_ton)

    # فحص المخزون قبل الحفظ
    mix_number = _next_mix_number(date_text)
    _check_inventory(mix_number, cleaned_items, created_by)

    net_cost = safe_float(net_cost_override) if net_cost_override is not None else totals["total_cost"]
    manually_edited = 1 if net_cost_override is not None else 0

    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO mix_invoices "
                "(mix_number, mix_date, farm_name, worker_name, total_weight, total_cost, "
                "mixer_net_cost, payment_status, notes, elec_fee, labor_fee, transport_fee, "
                "billable_tons, net_cost_manually_edited, is_deleted, deleted_at, recipe_id, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)",
                (
                    mix_number,
                    date_text,
                    clean_farm,
                    str(worker_name or "").strip() or None,
                    totals["total_weight"],
                    totals["total_cost"],
                    round(net_cost, 2),
                    payment_status,
                    str(notes or "").strip() or None,
                    totals["elec_fee"],
                    totals["labor_fee"],
                    totals["transport_fee"],
                    totals["billable_tons"],
                    manually_edited,
                    recipe_id,
                    created_by,
                ),
            )
            for item in cleaned_items:
                conn.execute(
                    "INSERT INTO mix_items "
                    "(mix_number, material_name, qty_kg, unit_price, total_price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        mix_number,
                        item["material_name"],
                        item["qty_kg"],
                        item["unit_price"],
                        item["total_price"],
                    ),
                )
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر إضافة الفاتورة %s: %s", mix_number, exc)
        raise ValueError("تعذر إضافة الفاتورة") from exc

    log_audit(
        "INSERT",
        "mix_invoices",
        mix_number,
        None,
        {
            "mix_number": mix_number,
            "mix_date": date_text,
            "farm_name": clean_farm,
            "total_cost": totals["total_cost"],
            "net_cost": round(net_cost, 2),
            "items_count": len(cleaned_items),
        },
        user=created_by,
    )
    cache.invalidate_prefix("farms:")
    cache.invalidate_prefix("inventory")
    cache.invalidate("mix_invoices")
    return mix_number


def update_invoice(
    mix_number: str,
    farm_name: str | None = None,
    worker_name: str | None = None,
    items: list[dict] | None = None,
    notes: str | None = None,
    payment_status: str | None = None,
    net_cost_override: float | None = None,
    net_cost_manually_edited: int | None = None,
) -> bool:
    """تحديث فاتورة موجودة مع إعادة حساب البنود إن تغيرت."""
    old = get_invoice(mix_number)
    if not old:
        raise ValueError("الفاتورة غير موجودة")
    if bool(old.get("is_deleted")):
        raise ValueError("لا يمكن تعديل فاتورة محذوفة (استعدها أولاً)")

    electricity_fee = cache.setting("electricity_fee", force=True)
    labor_fee_per_ton = cache.setting("labor_fee_per_ton", force=True)

    new_farm = validate_name(farm_name, "المزرعة", min_length=1) if farm_name is not None else str(old.get("farm_name") or "")
    if farms_repo.get_farm_by_name(new_farm) is None:
        raise ValueError(f"المزرعة «{new_farm}» غير موجودة")

    cleaned_items = _validate_items(items) if items is not None else old.get("items", [])
    totals = _compute_invoice_totals(cleaned_items, new_farm, electricity_fee, labor_fee_per_ton)

    # إعادة فحص المخزون للفاتورة المحدثة
    _check_invoice_inventory_after_update(mix_number, cleaned_items)

    net_cost = (
        safe_float(net_cost_override)
        if net_cost_override is not None
        else totals["total_cost"]
    )
    manually = (
        int(net_cost_manually_edited)
        if net_cost_manually_edited is not None
        else int(old.get("net_cost_manually_edited") or 0)
    )
    if net_cost_override is not None and manually == 0:
        manually = 1

    fields: list[str] = []
    params: list[Any] = []
    changes: dict[str, Any] = {}

    mapped: dict[str, Any] = {
        "mix_date": str(old.get("mix_date")),
        "farm_name": new_farm,
        "worker_name": str(worker_name).strip() if worker_name is not None else old.get("worker_name"),
        "total_weight": totals["total_weight"],
        "total_cost": totals["total_cost"],
        "mixer_net_cost": round(net_cost, 2),
        "payment_status": payment_status if payment_status is not None else old.get("payment_status"),
        "notes": str(notes).strip() if notes is not None else old.get("notes"),
        "elec_fee": totals["elec_fee"],
        "labor_fee": totals["labor_fee"],
        "transport_fee": totals["transport_fee"],
        "billable_tons": totals["billable_tons"],
        "net_cost_manually_edited": manually,
    }

    for col, new_val in mapped.items():
        old_val = old.get(col)
        if col in ("total_weight", "total_cost", "mixer_net_cost", "elec_fee", "labor_fee", "transport_fee", "billable_tons"):
            new_val = round(safe_float(new_val), 4)
            old_val = round(safe_float(old_val), 4)
        if str(new_val) != str(old_val):
            fields.append(f"{col} = ?")
            params.append(new_val)
            changes[col] = {"old": old_val, "new": new_val}

    try:
        with transaction() as conn:
            if fields:
                params.append(str(mix_number))
                conn.execute(f"UPDATE mix_invoices SET {', '.join(fields)} WHERE mix_number = ?", tuple(params))
            # استبدال البنود
            conn.execute("DELETE FROM mix_items WHERE mix_number = ?", (str(mix_number),))
            for item in cleaned_items:
                conn.execute(
                    "INSERT INTO mix_items (mix_number, material_name, qty_kg, unit_price, total_price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(mix_number), item["material_name"], item["qty_kg"], item["unit_price"], item["total_price"]),
                )
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث الفاتورة %s: %s", mix_number, exc)
        raise ValueError("تعذر تحديث الفاتورة") from exc

    log_audit("UPDATE", "mix_invoices", mix_number, changes, {"id": mix_number})
    cache.invalidate_prefix("farms:")
    cache.invalidate_prefix("inventory")
    cache.invalidate("mix_invoices")
    return True


def _check_invoice_inventory_after_update(mix_number: str, items: list[dict]) -> None:
    """يفحص المخزون عند تعديل فاتورة موجودة (باستثناء نفسها)."""
    for item in items:
        name = item["material_name"]
        needed_kg = safe_float(item["qty_kg"])
        needed_ton = kg_to_tons(needed_kg)

        supply_rows = query_all("SELECT qty_ton FROM purchases WHERE material_name = ?", (name,))
        supply = sum(safe_float(r.get("qty_ton")) for r in supply_rows)

        consumed_rows = query_all(
            "SELECT mi.qty_kg FROM mix_items mi "
            "JOIN mix_invoices m ON mi.mix_number = m.mix_number "
            "WHERE mi.material_name = ? AND (m.is_deleted = 0 OR m.is_deleted IS NULL) "
            "AND m.mix_number <> ?",
            (name, mix_number),
        )
        consumed = sum(kg_to_tons(safe_float(r.get("qty_kg"))) for r in consumed_rows)

        remaining = supply - consumed
        if remaining < needed_ton - 1e-9:
            raise ValueError(
                f"عجز في المخزون للمادة «{name}»: المتاح {remaining:.3f} طن، "
                f"المطلوب {needed_ton:.3f} طن"
            )


def soft_delete_invoice(mix_number: str, created_by: str | None = None) -> bool:
    """يُعلّم الفاتورة كمحذوفة (soft delete) دون حذف الفعلي."""
    invoice = get_invoice(mix_number)
    if not invoice:
        return False
    if bool(invoice.get("is_deleted")):
        return False
    execute(
        "UPDATE mix_invoices SET is_deleted = 1, deleted_at = datetime('now','localtime') WHERE mix_number = ?",
        (str(mix_number),),
    )
    log_audit(
        "DELETE",
        "mix_invoices",
        mix_number,
        {"is_deleted": 0},
        {"is_deleted": 1, "deleted_at": invoice.get("mix_date")},
        user=created_by,
    )
    cache.invalidate_prefix("inventory")
    cache.invalidate("mix_invoices")
    return True


def restore_invoice(mix_number: str, created_by: str | None = None) -> bool:
    """يُعيد فاتورة من سلة المحذوفات."""
    invoice = get_invoice(mix_number)
    if not invoice:
        return False
    if not bool(invoice.get("is_deleted")):
        return False
    # إعادة فحص المخزون قبل الاستعادة
    items = invoice.get("items", [])
    _check_invoice_inventory_after_update(mix_number, items)
    execute(
        "UPDATE mix_invoices SET is_deleted = 0, deleted_at = NULL WHERE mix_number = ?",
        (str(mix_number),),
    )
    log_audit(
        "UPDATE",
        "mix_invoices",
        mix_number,
        {"is_deleted": 1},
        {"is_deleted": 0},
        user=created_by,
    )
    cache.invalidate_prefix("inventory")
    cache.invalidate("mix_invoices")
    return True


def delete_invoice_permanent(mix_number: str) -> bool:
    """حذف نهائي لفاتورة (صيانة فقط). يُحذف بنودها تلقائياً عبر CASCADE."""
    invoice = get_invoice(mix_number)
    if not invoice:
        return False
    execute("DELETE FROM mix_invoices WHERE mix_number = ?", (str(mix_number),))
    log_audit(
        "DELETE",
        "mix_invoices",
        mix_number,
        {"mix_number": mix_number, "permanent": True},
        None,
    )
    cache.invalidate_prefix("inventory")
    cache.invalidate("mix_invoices")
    return True


def set_payment_status(mix_number: str, status: str, created_by: str | None = None) -> bool:
    """يحدث حالة الدفع للفاتورة."""
    from config import settings as app_settings
    status = str(status or "").strip()
    if status not in app_settings.PAYMENT_STATUSES:
        raise ValueError("حالة دفع غير صالحة")
    invoice = get_invoice(mix_number)
    if not invoice:
        return False
    if bool(invoice.get("is_deleted")):
        raise ValueError("لا يمكن تعديل فاتورة محذوفة")
    execute(
        "UPDATE mix_invoices SET payment_status = ? WHERE mix_number = ?",
        (status, str(mix_number)),
    )
    log_audit(
        "UPDATE",
        "mix_invoices",
        mix_number,
        {"payment_status": invoice.get("payment_status")},
        {"payment_status": status},
        user=created_by,
    )
    return True
