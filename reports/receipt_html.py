"""
reports/receipt_html.py
-----------------------
توليد إيصال استلام توريد بصيغة HTML قابلة للطباعة (RTL).

الاستخدام:
    html = generate_receipt_html(purchase_id)
    app.show_html(f"إيصال استلام #{purchase_id}", html)

المحتوى:
    بيانات التوريد (تاريخ/مادة/كمية/مورد) + تفاصيل الأسعار والرسوم
    + السعر الحقيقي للطن + تواقيع (المورّد - المستلم - المحاسب).
"""

from __future__ import annotations

import logging
from typing import Any

from core.utils import safe_float
from data import purchases_repo
from reports._html_base import (doc_header, info_grid, map_of, money, num,
                                render_page, signatures, table, totals_table)

_log = logging.getLogger("reports.receipt")


def _receipt_body(p: dict[str, Any]) -> str:
    """يبني جسم صفحة الإيصال من سجل purchases."""
    parts: list[str] = [doc_header("إيصال استلام بضاعة")]
    parts.append(f'<div class="doc-title">📥 إيصال استلام توريد رقم '
                 f'{p.get("id", "")}</div>')

    parts.append(info_grid([
        ("التاريخ", p.get("purchase_date", "")),
        ("المادة", p.get("material_name", "")),
        ("المورّد", p.get("supplier", "") or "-"),
        ("الكمية", f'{num(p.get("qty_ton"), 3)} طن'),
    ]))

    details = str(p.get("details") or "").strip()
    if details:
        parts.append(f"<p><b>بيان:</b> {details}</p>")

    price = safe_float(p.get("price_per_ton"))
    qty = safe_float(p.get("qty_ton"))
    goods = price * qty

    fee_rows: list[list[Any]] = [[
        "سعر الطن", money(p.get("price_per_ton")),
        "قيمة البضاعة", money(goods),
    ]]
    parts.append(table(["البند", "القيمة", "البند", "القيمة"],
                       fee_rows, align_left_cols=(1, 3)))

    totals_rows = [
        ("قيمة البضاعة", money(goods)),
        ("رسوم تنزيل", money(p.get("unloading_fee"))),
        ("رسوم عتالة", money(p.get("handling_fee"))),
        ("رسوم نقل", money(p.get("transport_fee"))),
        ("رسوم أخرى", money(p.get("other_fees"))),
        ("مجموع الرسوم", money(p.get("fees_total"))),
    ]
    parts.append(totals_table(
        totals_rows,
        grand=("الإجمالي المدفوع", money(p.get("total_cost"))),
    ))

    real = safe_float(p.get("real_price_per_ton"))
    if real > 0 and qty > 0:
        parts.append(
            f"<p style='font-size:14px'><b>✅ السعر الحقيقي للطن "
            f"(شامل الرسوم):</b> {money(real)}</p>"
        )

    parts.append(signatures("المورّد", "أمين المستودع", "المحاسب"))
    return "".join(parts)


def generate_receipt_html(purchase_id: int) -> str:
    """
    يعيد نص HTML كاملاً لإيصال استلام التوريد المطلوب.

    يرفع ValueError عند معرف غير صالح أو عدم وجود السجل.
    """
    try:
        pid = int(purchase_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("معرّف التوريد غير صالح") from exc
    try:
        row = purchases_repo.get_purchase(pid)
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل قراءة التوريد %s", pid)
        raise ValueError(f"تعذّر قراءة بيانات التوريد: {exc}") from exc
    if row is None:
        raise ValueError(f"التوريد رقم {pid} غير موجود")

    body = _receipt_body(map_of(row))
    return render_page(f"إيصال استلام #{pid}", body)
