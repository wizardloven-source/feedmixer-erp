"""
data/invoices_repo.py
---------------------
مستودع الخلطات / الفواتير (mix_invoices + mix_items).

الصيغة المحاسبية (راجع core.utils):
    billable_tons = int((total_weight_kg + 249) / 500) * 0.5
    feed_cost     = Σ (qty_kg * unit_price)
    elec_fee      = إعداد الكهرباء                      ← قيمة ثابتة لكل خلطة
    labor_fee     = billable_tons * إعداد أجرة العمال   ← متغيرة مع الوزن
    transport     = أجرة النقل للمزرعة المختارة          ← قيمة ثابتة لكل فاتورة
    total_cost    = feed_cost + elec_fee + labor_fee + transport
    mixer_net_cost= total_cost (إلا إذا تم تعديل الصافي يدوياً)

الخلطة تُحفظ ذرّياً: الفاتورة + كل عناصرها في معاملة واحدة.
soft delete: is_deleted + deleted_at (لا يُحذف نهائياً إلا للصيانة).

تحصين المرحلة 4 (Defense in Depth):
    1) add_invoice/set_payment_status يتحققان من payment_status عبر
       validate_choice ضد settings.PAYMENT_STATUSES (منع تلوث البيانات).
    2) soft_delete_invoice يفحص الدفعات قبل الحذف ويرفضه إذا كان سيؤدي
       إلى رصيد سالب للمزرعة (دفعة يتيمة بلا فاتورة مرجعية).
    3) update_invoice تستخدم diff للبنود بدل DELETE+INSERT الكامل —
       الحفاظ على id و price_snapshot_at مهم للتدقيق.
"""

from __future__ import annotations

from typing import Any

from config import settings
from core import cache
from core.logger import get_logger, log_audit
from core.utils import calc_billable_tons, kg_to_tons, safe_float, safe_int
from core.validators import validate_choice, validate_date, validate_name, validate_number
from data.connection import execute, query_all, query_one, transaction
from data import farms_repo

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

    # تحصين المرحلة 4: التحقق من حالة الدفع قبل الحفظ (Defense in Depth)
    # — سابقاً كانت أي قيمة عشوائية تُحفظ وتلوّث البيانات.
    status = validate_choice(payment_status, settings.PAYMENT_STATUSES, "حالة الدفع")

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
                    status,
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
                # price_snapshot_at يُكتب عند الإدراج فقط (طابع زمني محلي)
                conn.execute(
                    "INSERT INTO mix_items "
                    "(mix_number, material_name, qty_kg, unit_price, total_price, price_snapshot_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))",
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


def _diff_mix_items(conn: Any, mix_number: str, new_items: list[dict]) -> dict[str, int]:
    """
    يطبّق diff بين بنود الفاتورة القديمة والجديدة بدل حذف الكل وإعادة إدراجه.

    تحصين المرحلة 4: الحذف الكلي كان يفقد id الأصلي لكل بند ويطمس
    price_snapshot_at — ما يكسر تتبع التدقيق («هذا البند تغيّر متى؟»).
    القواعد:
        - بند مطابق (نفس المادة + الكمية + السعر): يُترك كما هو (unchanged).
        - بند بنفس المادة وكمية/سعر مختلف: UPDATE — يحتفظ بـ id
          وبـ price_snapshot_at الأصلي (لا يُعاد كتابته عند التعديل).
        - بند جديد لا يوجد له مقابل: INSERT مع طابع سعري جديد.
        - بند قديم لم يعد في القائمة: DELETE بحسب id الخاص به فقط.
    يعيد عدّادات {'inserted', 'updated', 'deleted', 'unchanged'} لتسجيلها
    في audit_log بدقة.
    """
    old = conn.execute(
        "SELECT id, material_name, qty_kg, unit_price, total_price "
        "FROM mix_items WHERE mix_number = ? ORDER BY id ASC",
        (str(mix_number),),
    ).fetchall()

    def _key(name: str, qty: float, price: float) -> tuple[str, float, float]:
        # تقريب موحد لطريقة التخزين: كمية 3 خانات وسعر خانتان (كما في _validate_items)
        return (str(name), round(safe_float(qty), 3), round(safe_float(price), 2))

    old_by_key: dict[tuple[str, float, float], list[Any]] = {}
    for row in old:
        old_by_key.setdefault(_key(row[1], row[2], row[3]), []).append(row)

    used_ids: set[int] = set()
    inserted = updated = unchanged = 0
    for it in new_items:
        key = _key(it["material_name"], it["qty_kg"], it["unit_price"])
        candidates = [r for r in old_by_key.get(key, []) if int(r[0]) not in used_ids]
        if candidates:
            # مطابق تماماً — لا لمس للصفحة الأصلية (يحفظ id والطابع الزمني)
            used_ids.add(int(candidates[0][0]))
            unchanged += 1
            continue
        # هل يوجد بند قديم بنفس المادة (كمية/سعر تغيّرا)؟ → UPDATE يحفظ id
        same_material = [r for r in old
                         if str(r[1]) == str(it["material_name"]) and int(r[0]) not in used_ids]
        if same_material:
            row = same_material[0]
            conn.execute(
                "UPDATE mix_items SET qty_kg = ?, unit_price = ?, total_price = ? "
                "WHERE id = ?",
                (it["qty_kg"], it["unit_price"], it["total_price"], int(row[0])),
            )
            used_ids.add(int(row[0]))
            updated += 1
        else:
            conn.execute(
                "INSERT INTO mix_items "
                "(mix_number, material_name, qty_kg, unit_price, total_price, price_snapshot_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))",
                (str(mix_number), it["material_name"], it["qty_kg"],
                 it["unit_price"], it["total_price"]),
            )
            inserted += 1

    # احذف البنود القديمة التي لم تعد موجودة في القائمة الجديدة (بالid فقط)
    deleted = 0
    for row in old:
        if int(row[0]) not in used_ids:
            conn.execute("DELETE FROM mix_items WHERE id = ?", (int(row[0]),))
            deleted += 1

    return {"inserted": inserted, "updated": updated,
            "deleted": deleted, "unchanged": unchanged}


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

    # تحصين المرحلة 4: لا تُقبل حالة دفع عشوائية حتى في المسار الجزئي
    # (None = إبقاء الحالة القديمة دون تغيير كما كان السلوك).
    new_status: Any = None
    if payment_status is not None:
        new_status = validate_choice(payment_status, settings.PAYMENT_STATUSES, "حالة الدفع")

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
        "payment_status": new_status if new_status is not None else old.get("payment_status"),
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
            # تحصين المرحلة 4: diff بدل DELETE كامل + INSERT — يحافظ على
            # id البنود غير المتغيرة وعلى price_snapshot_at الأصلي للتدقيق.
            if items is not None:
                item_stats = _diff_mix_items(conn, str(mix_number), cleaned_items)
            else:
                item_stats = {"inserted": 0, "updated": 0, "deleted": 0,
                              "unchanged": len(cleaned_items)}
    except Exception as exc:  # noqa: BLE001
        _log.error("تعذر تحديث الفاتورة %s: %s", mix_number, exc)
        raise ValueError("تعذر تحديث الفاتورة") from exc

    # تحصين المرحلة 4: audit_log يعكس عدد البنود المُدرجة/المعدلة/المحذوفة
    # بدقة. ملاحظة بنيوية: سجل التدقيق يخزّن old_value فقط (new_value ثابت
    # لدى المناديات القديمة كـ {"id": ...}) — لذا يُدمج ملخص الـ diff داخل
    # old_value ليظهر في سجل التدقيق دون تغيير توقيع log_audit.
    changes["items_diff"] = item_stats
    log_audit("UPDATE", "mix_invoices", mix_number, changes, {"id": str(mix_number)})
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


def _farm_payments_total(farm_name: str) -> float:
    """مجموع مدفوعات المزرعة (الدفعات مرتبطة بالاسم لا برقم الفاتورة)."""
    row = query_one(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE farm_name = ?",
        (str(farm_name or ""),),
    )
    return safe_float((row or {}).get("total"))


def _farm_other_net_total(farm_name: str, exclude_mix_number: str) -> float:
    """مجموع صافي الفواتير النشطة الأخرى للمزرعة (باستثناء المستثناة)."""
    row = query_one(
        "SELECT COALESCE(SUM(mixer_net_cost), 0) AS total FROM mix_invoices "
        "WHERE farm_name = ? AND (is_deleted = 0 OR is_deleted IS NULL) "
        "AND mix_number <> ?",
        (str(farm_name or ""), str(exclude_mix_number)),
    )
    return safe_float((row or {}).get("total"))


def soft_delete_invoice(mix_number: str, created_by: str | None = None) -> bool:
    """
    يُعلّم الفاتورة كمحذوفة (soft delete) دون حذف فعلي.

    تحصين المرحلة 4: الدفعات تُسجَّل على اسم المزرعة ولا ترتبط برقم فاتورة،
    لذا حذف فاتورة مسددَة يجعل الرصيد سالباً (دفعة يتيمة). نفحص ذلك قبل
    الحذف ونرفض برسالة عربية واضحة؛ الواجهة (ui/tabs/invoices.py) تعرض
    str(exc) في Toast عند ValueError — لا حاجة لتعديلها.
    """
    invoice = get_invoice(mix_number)
    if not invoice:
        return False
    if bool(invoice.get("is_deleted")):
        return False

    farm_name = str(invoice.get("farm_name") or "")
    paid_total = _farm_payments_total(farm_name)
    other_net = 0.0
    balance_before = 0.0
    balance_after = 0.0
    if paid_total > 0:
        other_net = _farm_other_net_total(farm_name, str(mix_number))
        balance_before = other_net + safe_float(invoice.get("mixer_net_cost")) - paid_total
        balance_after = other_net - paid_total
        if paid_total > other_net + 1e-9:
            # الرصيد بعد الحذف سيصبح سالباً — ارفض وسجّل المحاولة للمراجعة
            log_audit(
                "DELETE_BLOCKED",
                "mix_invoices",
                mix_number,
                {"is_deleted": 0},
                {
                    "reason": "مدفوعات تتجاوز صافي الفواتير الأخرى",
                    "payments_total": round(paid_total, 2),
                    "other_net_total": round(other_net, 2),
                    "balance_before": round(balance_before, 2),
                    "balance_after": round(balance_after, 2),
                },
                user=created_by,
            )
            raise ValueError(
                f"⚠️ تحذير: الفاتورة لها دفعات مسجلة على المزرعة «{farm_name}». "
                f"حذفها سيجعل رصيد المزرعة سالباً "
                f"(الرصيد الحالي: {balance_before:,.2f} ← بعد الحذف: {balance_after:,.2f}). "
                f"راجع الوضع أولاً: احذف/عدّل الدفعات المرتبطة قبل حذف الفاتورة، "
                f"أو استخدم الأرشفة بدل الحذف."
            )

    execute(
        "UPDATE mix_invoices SET is_deleted = 1, deleted_at = datetime('now','localtime') WHERE mix_number = ?",
        (str(mix_number),),
    )
    details: dict[str, Any] = {"is_deleted": 1, "deleted_at": invoice.get("mix_date")}
    if paid_total > 0:
        # حذف مسموح لكن توجد دفعات — سجّل الأرصدة للمساءلة (audit trail)
        details.update({
            "payments_total": round(paid_total, 2),
            "other_net_total": round(other_net, 2),
            "balance_before": round(balance_before, 2),
            "balance_after": round(balance_after, 2),
        })
    log_audit(
        "DELETE",
        "mix_invoices",
        mix_number,
        {"is_deleted": 0},
        details,
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
    # تحصين المرحلة 4: توحيد الآلية مع add_invoice عبر validate_choice
    # (كان الفحص اليدوي هنا يعمل، لكن برسالة أقل تفصيلاً من المدقق الموحد).
    status = validate_choice(status, settings.PAYMENT_STATUSES, "حالة الدفع")
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
