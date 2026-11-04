"""
services/mix_service.py
-----------------------
منطق حساب تكاليف الخلطة وفحص المخزون قبل الحفظ.

القواعد المحاسبية المطبَّقة (مطابقة لمواصفات النظام):
    1) سعر الكيلو من المادة حسب وحدة القياس:
         ton   : (base_price + handling_fee + loss_fee) / 1000
         kg    :  base_price + handling_fee + loss_fee
         fixed :  base_price
       (يُنفَّذ في core.utils.material_kg_price)
    2) تكلفة العلف = Σ (qty_kg × سعر_الكيلو)
    3) أنصاف الأطنان القابلة للفوترة = int((kg_total + 249) / 500) * 0.5
    4) أجور العمال = billable_tons × labor_fee_per_ton
    5) الكهرباء     = billable_tons × electricity_fee
    6) النقل        = transport_fee للمزرعة × billable_tons
    7) الإجمالي = علف + كهرباء + عمال + نقل
    8) الصافي   = الإجمالي إلا إذا عدِّل يدوياً (net_cost_manually_edited)

تجميد السعر (Price Snapshot):
    - عند الإنشاء: السعر يُقرأ حيًّا من materials ويُخزَّن في mix_items.unit_price.
    - عند التعديل/العرض: يُستخدم unit_price المجمّد — لا يُعاد حسابه.
    - هذا يضمن أن تغيير سعر مادة لا يؤثر على الخلطات السابقة.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from config import settings
from core import cache
from core.logger import get_logger
from core.utils import (
    calc_billable_tons,
    material_kg_price,
    round_money,
    round_qty,
    safe_float,
    tons_to_kg,
)
from data import farms_repo, invoices_repo, settings_repo

log = get_logger("services.mix")


# ============================================================
# تسعير البنود
# ============================================================

def price_item(material_name: str, qty_kg: float,
               override_price: float | None = None) -> dict[str, Any]:
    """
    يحسب بنداً واحداً بسعر *حيّ* من قاعدة البيانات.
    يُستخدم عند الإنشاء الجديد فقط، أو عند إضافة بند جديد لخلطة قائمة.

    override_price: سعر الكيلو الذي أدخله المستخدم يدوياً؛ إن كان > 0
    يُستخدم بدل سعر المادة المحسوب من قاعدة البيانات.
    """
    kg = safe_float(qty_kg, 0.0)
    material = cache.material_map().get(str(material_name or "").strip()) or {}
    unit_price = safe_float(override_price, 0.0)
    if unit_price <= 0:
        unit_price = material_kg_price(material)
    total = round_money(kg * unit_price)
    return {
        "material_name": str(material_name or ""),
        "qty_kg": round_qty(kg),
        "unit_price": round(unit_price, 6),
        "total_price": total,
        "source": "يدوي" if safe_float(override_price, 0.0) > 0 else "قاعدة بيانات",
    }


def price_item_frozen(material_name: str, qty_kg: float,
                      unit_price: float) -> dict[str, Any]:
    """
    يبني بنداً بسعر *مجمّد* (صريح) — لا يقرأ من materials إطلاقاً.
    يُستخدم عند عرض/تعديل فاتورة قائمة.
    """
    kg = safe_float(qty_kg, 0.0)
    up = max(safe_float(unit_price, 0.0), 0.0)
    return {
        "material_name": str(material_name or "").strip(),
        "qty_kg":        round_qty(kg),
        "unit_price":    round(up, 6),
        "total_price":   round_money(kg * up),
        "source":        "مجمّد",
    }


def price_items(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    تسعير كامل بنود الخلطة بسعر حيّ (للإنشاء الجديد فقط).
    """
    priced: list[dict[str, Any]] = []
    for it in items:
        name = str(it.get("material_name", "") or "").strip()
        if not name:
            continue
        priced.append(price_item(
            name,
            it.get("qty_kg", 0.0),
            it.get("unit_price_override"),
        ))
    return priced


def price_items_frozen(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    يحترم unit_price المجمّد في البند إن وُجد (> 0)، وإلا يعود للسعر الحي.
    يُستخدم في: calculate_mix (المعاينة) + update_invoice (التعديل).
    """
    priced: list[dict[str, Any]] = []
    for it in items:
        name = str(it.get("material_name", "") or "").strip()
        if not name:
            continue
        frozen = safe_float(it.get("unit_price"), 0.0)
        if frozen > 0:
            priced.append(price_item_frozen(name, it.get("qty_kg", 0.0), frozen))
        else:
            priced.append(price_item(name, it.get("qty_kg", 0.0),
                                     it.get("unit_price_override")))
    return priced


# ============================================================
# حساب الخلطة الكاملة
# ============================================================

def calculate_mix(
    items: Sequence[Mapping[str, Any]],
    farm_name: str,
    net_cost_override: float | None = None,
) -> dict[str, Any]:
    """
    الحساب الكامل للخلطة قبل الحفظ أو أثناء المعاينة الحيّة.

    يستخدم price_items_frozen — أي أنه يحترم unit_price المجمّد
    في البنود إن وُجد (فاتورة قائمة)، وإلا يحسب حيًّا (نموذج جديد).
    """
    priced = price_items_frozen(items)
    total_weight_kg = sum(float(p["qty_kg"]) for p in priced)
    billable = calc_billable_tons(total_weight_kg)

    # أسعار الإعدادات (مع fallback إلى القيم الافتراضية)
    elec_rate = safe_float(settings_repo.get_setting(
        "electricity_fee", settings.DEFAULT_SETTINGS["electricity_fee"]))
    labor_rate = safe_float(settings_repo.get_setting(
        "labor_fee_per_ton", settings.DEFAULT_SETTINGS["labor_fee_per_ton"]))

    feed_cost = round_money(sum(float(p["total_price"]) for p in priced))
    elec_cost = round_money(billable * elec_rate)
    labor_cost = round_money(billable * labor_rate)

    # أجرة النقل خاصة بالمزرعة (لكل طن قابل للفوترة)
    farm = farms_repo.get_farm_by_name(farm_name) or {}
    farm_transport_rate = safe_float(farm.get("transport_fee"), 0.0)
    transport_cost = round_money(billable * farm_transport_rate)

    total_cost = round_money(feed_cost + elec_cost + labor_cost + transport_cost)

    manually_edited = net_cost_override is not None and safe_float(net_cost_override) > 0
    mixer_net = round_money(net_cost_override) if manually_edited else total_cost

    return {
        "priced_items": priced,
        "total_weight_kg": round_qty(total_weight_kg),
        "billable_tons": billable,
        "feed_cost": feed_cost,
        "elec_rate": elec_rate,
        "labor_rate": labor_rate,
        "farm_transport_fee": farm_transport_rate,
        "elec_cost": elec_cost,
        "labor_cost": labor_cost,
        "transport_cost": transport_cost,
        "total_cost": total_cost,
        "mixer_net_cost": mixer_net,
        "manually_edited": bool(manually_edited),
    }


def preview_totals_for_ui(items: Sequence[Mapping[str, Any]],
                          farm_name: str) -> dict[str, str]:
    """نسخة منسّقة كنصوص عربية جاهزة لخانات المعاينة في تبويب الخلطة."""
    c = calculate_mix(items, farm_name)
    return {
        "weight": f"{c['total_weight_kg']:,.0f} كغ",
        "billable": f"{c['billable_tons']:.1f} طن",
        "feed": f"{c['feed_cost']:,.2f}",
        "elec": f"{c['elec_cost']:,.2f}",
        "labor": f"{c['labor_cost']:,.2f}",
        "transport": f"{c['transport_cost']:,.2f}",
        "total": f"{c['total_cost']:,.2f}",
    }


# ============================================================
# فحص المخزون (تقرير مبكر قبل الحفظ)
# ============================================================

def check_items_availability(items: Sequence[Mapping[str, Any]],
                             mix_number: str | None = None) -> list[dict[str, Any]]:
    """
    يفحص عجز كل مادة في البنود مقابل المتاح في المخزون.
    """
    from services import inventory_service

    needed_map: dict[str, float] = {}
    for it in items:
        name = str(it.get("material_name", "") or "").strip()
        if name:
            needed_map[name] = needed_map.get(name, 0.0) + safe_float(it.get("qty_kg"))

    deficits: list[dict[str, Any]] = []
    balances = {str(r.get("name")): r for r in inventory_service.inventory_balances()}

    current_consumption: dict[str, float] = {}
    if mix_number:
        try:
            inv = invoices_repo.get_invoice(str(mix_number)) or {}
            for row in inv.get("items", []) or []:
                n = str(row.get("material_name", ""))
                current_consumption[n] = (current_consumption.get(n, 0.0)
                                          + safe_float(row.get("qty_kg")))
        except Exception:
            log.exception("تعذّر قراءة فاتورة للتحليل")

    for name, need_kg in needed_map.items():
        row = balances.get(name)
        avail_kg = safe_float((row or {}).get("remaining_ton")) * settings.KG_PER_TON
        avail_kg += current_consumption.get(name, 0.0)
        if need_kg > avail_kg + 1e-6:
            deficit = round_qty(need_kg - avail_kg)
            deficits.append({
                "material_name": name,
                "needed_kg": round_qty(need_kg),
                "available_kg": round_qty(max(avail_kg, 0.0)),
                "deficit_kg": deficit,
                "deficit_ton": round_qty(deficit / settings.KG_PER_TON),
            })
    return deficits


def format_deficits_report(deficits: Sequence[Mapping[str, Any]]) -> str:
    """نص عربي متعدد الأسطر لعرضه في رسالة تأكيد/تحذير."""
    if not deficits:
        return ""
    lines = ["⚠️ عجز في المخزون:"]
    for d in deficits:
        lines.append(
            f"   • {d['material_name']}: مطلوب {d['needed_kg']:,.0f} كغ، "
            f"متاح {d['available_kg']:,.0f} كغ، العجز {d['deficit_ton']:,.2f} طن"
        )
    return "\n".join(lines)


# ============================================================
# تطبيق الوصفة على شاشة الخلطة
# ============================================================

def recipe_to_items(recipe_id: int) -> list[dict[str, Any]]:
    """يحوّل وصفة محفوظة إلى بنود جاهزة لشاشة الخلطة."""
    from data import recipes_repo

    recipe = recipes_repo.get_recipe(int(recipe_id)) or {}
    items: list[dict[str, Any]] = []
    for row in recipe.get("items", []) or []:
        name = str(row.get("material_name", "") or "").strip()
        if not name:
            continue
        qty = safe_float(row.get("qty_kg"))
        material = cache.material_map().get(name) or {}
        if str(material.get("unit_type", "ton")) == "ton" and 0 < qty < 1:
            qty = tons_to_kg(qty)
        items.append({"material_name": name, "qty_kg": round_qty(qty)})
    return items


def save_mix(
    mix_date: str,
    farm_name: str,
    worker_name: str,
    items: Sequence[Mapping[str, Any]],
    notes: str = "",
    payment_status: str = "unpaid",
    net_cost_override: float | None = None,
    recipe_id: int | None = None,
    created_by: str | None = None,
) -> str:
    """
    الحفظ النهائي لخلطة *جديدة* عبر طبقة البيانات.
    يستخدم price_items (سعر حيّ) — لأنها خلطة جديدة.
    """
    priced = price_items(items)
    mix_number = invoices_repo.add_invoice(
        mix_date=mix_date,
        farm_name=farm_name,
        worker_name=worker_name,
        items=priced,
        notes=notes,
        payment_status=payment_status,
        net_cost_override=net_cost_override,
        recipe_id=recipe_id,
        created_by=created_by,
    )
    try:
        from services import inventory_service
        inventory_service.invalidate()
        cache.invalidate_materials()
        cache.invalidate_settings()
    except Exception:
        log.exception("إبطال الكاش بعد الحفظ فشل (غير حرج)")
    log.info("تم حفظ الخلطة %s بمزرعة %s بواسطة %s", mix_number, farm_name, created_by)
    return mix_number