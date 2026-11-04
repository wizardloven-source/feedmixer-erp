"""
ui/tabs/_report_data.py
-----------------------
دوال تجميع بيانات التقارير الشهرية (توريدات مقابل خلطات).

تُستخدم من تبويب التقارير (ui/tabs/reports.py) لبناء الجداول والرسوم
البيانية وملفات التصدير. لا تعتمد على Tk إطلاقاً حتى تُختبر بدون واجهة.

الدوال العامة:
    month_bounds(yyyy_mm)          -> (first_iso, last_iso)
    monthly_report(yyyy_mm)        -> dict ملخص شهر واحد
    yearly_series(year)            -> قائمة 12 شهراً للرسوم البيانية
"""

from __future__ import annotations

import calendar
import logging
from typing import Any

from core.utils import safe_float
from data import invoices_repo, purchases_repo

_log = logging.getLogger("ui.tabs.report_data")


def month_bounds(yyyy_mm: str) -> tuple[str, str]:
    """
    يحول 'YYYY-MM' إلى أول وآخر يوم بصيغة ISO 'YYYY-MM-DD'.

    يرفع ValueError عند صيغة غير صحيحة.
    """
    text = str(yyyy_mm or "").strip()
    parts = text.split("-")
    if len(parts) != 2:
        raise ValueError(f"صيغة الشهر يجب أن تكون YYYY-MM وليست «{text}»")
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"صيغة الشهر يجب أن تكون YYYY-MM وليست «{text}»") from exc
    if not 1 <= month <= 12 or year < 1900:
        raise ValueError(f"شهر غير منطقي: {text}")
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def monthly_report(yyyy_mm: str) -> dict[str, Any]:
    """
    تقرير شهر واحد: توريدات مقابل خلطات لكل مادة + مجاميع.

    يعيد:
        month, date_from, date_to,
        purchases: [{material, qty_ton, total_cost, real_price_per_ton}],
        mixes:     [{material, qty_kg, total_price}],
        materials: [{name, purchased_ton, consumed_ton, net_ton,
                     purchase_cost, mix_value}],
        totals: {purchase_qty, purchase_cost, mix_kg, feed_cost,
                 mix_count, grand_net},
    """
    date_from, date_to = month_bounds(yyyy_mm)
    pur_rows = purchases_repo.list_purchases(date_from=date_from, date_to=date_to)
    inv_rows = invoices_repo.list_invoices(date_from=date_from, date_to=date_to)

    # تجميع التوريدات لكل مادة
    by_mat_purchase: dict[str, dict[str, float]] = {}
    for p in pur_rows:
        name = str(p.get("material_name", "")).strip() or "(بدون اسم)"
        agg = by_mat_purchase.setdefault(name, {"qty_ton": 0.0, "cost": 0.0})
        agg["qty_ton"] += safe_float(p.get("qty_ton"))
        agg["cost"] += safe_float(p.get("total_cost"))

    # تجميع بنود الخلطات لكل مادة (استعلام مجمّع واحد للأداء)
    from data.connection import query_all
    by_mat_mix: dict[str, dict[str, float]] = {}
    item_rows = query_all(
        """SELECT mi.material_name AS material_name,
                  SUM(mi.qty_kg)      AS qty_kg,
                  SUM(mi.total_price) AS total_price
           FROM mix_items mi
           JOIN mix_invoices mv ON mv.mix_number = mi.mix_number
           WHERE mv.mix_date BETWEEN ? AND ?
             AND COALESCE(mv.is_deleted, 0) = 0
           GROUP BY mi.material_name""",
        (date_from, date_to),
    )
    for r in item_rows:
        name = str(r.get("material_name", "")).strip() or "(بدون اسم)"
        agg = by_mat_mix.setdefault(name, {"qty_kg": 0.0, "value": 0.0})
        agg["qty_kg"] += safe_float(r.get("qty_kg"))
        agg["value"] += safe_float(r.get("total_price"))

    all_names = sorted(set(by_mat_purchase) | set(by_mat_mix))
    materials: list[dict[str, Any]] = []
    for name in all_names:
        pur = by_mat_purchase.get(name, {"qty_ton": 0.0, "cost": 0.0})
        mix = by_mat_mix.get(name, {"qty_kg": 0.0, "value": 0.0})
        consumed_ton = mix["qty_kg"] / 1000.0
        materials.append({
            "material": name,
            "purchased_ton": round(pur["qty_ton"], 3),
            "consumed_ton": round(consumed_ton, 3),
            "net_ton": round(pur["qty_ton"] - consumed_ton, 3),
            "purchase_cost": round(pur["cost"], 2),
            "mix_value": round(mix["value"], 2),
        })

    purchase_qty = round(sum(m["purchased_ton"] for m in materials), 3)
    purchase_cost = round(sum(m["purchase_cost"] for m in materials), 2)
    mix_kg = round(sum(safe_float(i.get("total_weight")) for i in inv_rows), 1)
    feed_cost = round(sum(m["mix_value"] for m in materials), 2)
    grand_net = round(sum(safe_float(i.get("mixer_net_cost")) for i in inv_rows), 2)

    return {
        "month": yyyy_mm,
        "date_from": date_from,
        "date_to": date_to,
        "purchases": [
            {"material": k, "qty_ton": round(v["qty_ton"], 3),
             "total_cost": round(v["cost"], 2)}
            for k, v in sorted(by_mat_purchase.items())
        ],
        "mixes": [
            {"material": k, "qty_kg": round(v["qty_kg"], 1),
             "total_price": round(v["value"], 2)}
            for k, v in sorted(by_mat_mix.items())
        ],
        "materials": materials,
        "totals": {
            "purchase_qty": purchase_qty,
            "purchase_cost": purchase_cost,
            "mix_kg": mix_kg,
            "feed_cost": feed_cost,
            "mix_count": len(inv_rows),
            "grand_net": grand_net,
        },
    }


def yearly_series(year: int) -> list[dict[str, Any]]:
    """
    سلسلة 12 شهراً لسنة معينة لعرضها في رسم matplotlib أو جدول.

    كل عنصر: {month:'YYYY-MM', label, purchase_cost, feed_cost, mix_count}
    """
    out: list[dict[str, Any]] = []
    for m in range(1, 13):
        ym = f"{int(year):04d}-{m:02d}"
        try:
            rep = monthly_report(ym)
            totals = rep["totals"]
        except Exception:  # noqa: BLE001 - شهر بلا بيانات ليس خطأً
            _log.exception("فشل تجميع شهر %s (سيُصفَّر)", ym)
            totals = {"purchase_cost": 0.0, "feed_cost": 0.0, "mix_count": 0}
        out.append({
            "month": ym,
            "label": ym[-2:],
            "purchase_cost": round(safe_float(totals.get("purchase_cost")), 2),
            "feed_cost": round(safe_float(totals.get("feed_cost")), 2),
            "mix_count": int(totals.get("mix_count") or 0),
        })
    return out
