"""
reports/invoice_html.py
-----------------------
توليد فاتورة خلطة أعلاف بصيغة HTML احترافية قابلة للطباعة (RTL).

الاستخدام:
    html = generate_invoice_html("MIX-202611-0001")
    app.show_html(f"فاتورة {number}", html)

المحتوى:
    ترويسة + بيانات الفاتورة + جدول البنود (مادة/كمية/سعر/إجمالي)
    + جدول المجاميع (علف، كهرباء، عمال، نقل، صافي) + ملاحظات + تواقيع.
"""

from __future__ import annotations

import logging
from typing import Any

from core.utils import safe_float
from data import invoices_repo
from reports._html_base import (doc_header, info_grid, map_of, money, num,
                                render_page, signatures, status_badge, table,
                                totals_table)

_log = logging.getLogger("reports.invoice")


def _invoice_body(inv: dict[str, Any]) -> str:
    """يبني جسم صفحة الفاتورة من سجل mix_invoices مع بنوده."""
    mix_number = str(inv.get("mix_number", ""))
    items = inv.get("items") or []

    feed_total = sum(safe_float(it.get("total_price")) for it in items)
    elec = safe_float(inv.get("elec_fee"))
    labor = safe_float(inv.get("labor_fee"))
    transport = safe_float(inv.get("transport_fee"))
    total_cost = safe_float(inv.get("total_cost")) or (feed_total + elec + labor + transport)
    # الصافي لا يسقط إلى صفر: إن كان 0 نعرض الإجمالي (سلوك الحفظ الطبيعي)
    net = safe_float(inv.get("mixer_net_cost"))
    if net <= 0:
        net = total_cost
    weight_kg = safe_float(inv.get("total_weight"))
    billable = safe_float(inv.get("billable_tons"))
    edited = bool(safe_float(inv.get("net_cost_manually_edited")))

    parts: list[str] = [doc_header("فاتورة خلطة أعلاف")]
    parts.append(f'<div class="doc-title">🧾 فاتورة خلطة رقم {mix_number}</div>')

    parts.append(info_grid([
        ("التاريخ", inv.get("mix_date", "")),
        ("المزرعة", inv.get("farm_name", "")),
        ("عامل الخلط", inv.get("worker_name", "") or "-"),
        ("الحالة", status_badge(inv.get("payment_status", ""))),
        ("وزن الخلطة", f"{num(weight_kg)} كغ ({num(weight_kg / 1000.0, 2)} طن)"),
        ("أنصاف الأطنان المحاسوبة", f"{num(billable, 1)} طن"),
    ]))

    rows: list[list[Any]] = []
    for idx, it in enumerate(items, start=1):
        rows.append([
            idx,
            it.get("material_name", ""),
            num(it.get("qty_kg")),
            money(it.get("unit_price")),
            money(it.get("total_price")),
        ])
    parts.append(table(["#", "المادة", "الكمية (كغ)", "سعر الكغ", "الإجمالي"],
                       rows, align_left_cols=(2, 3, 4)))

    totals_rows = [
        ("تكلفة العلف", money(feed_total)),
        ("أجرة الكهرباء", money(elec)),
        ("أجور العمال", money(labor)),
        ("أجرة النقل", money(transport)),
    ]
    grand_label = "صافي الخلطة" + (" (معدّل يدوياً ✍)" if edited else "")
    parts.append(totals_table(totals_rows, grand=(grand_label, money(net))))

    notes = str(inv.get("notes") or "").strip()
    if notes:
        parts.append(f"<p><b>ملاحظات:</b> {notes}</p>")
    created_by = str(inv.get("created_by") or "")
    if created_by:
        parts.append(f"<p style='font-size:12px;color:#667'>صدرت بواسطة: {created_by}</p>")

    parts.append(signatures("المحاسب", "أمين المخزن", "المستلم"))
    return "".join(parts)


def generate_invoice_html(mix_number: str) -> str:
    """
    يعيد نص HTML كاملاً لفاتورة الخلطة المطلوبة.

    يرفع ValueError إذا لم توجد الفاتورة (ليعرضه التبويب في Toast).
    """
    number = str(mix_number or "").strip()
    if not number:
        raise ValueError("رقم الفاتورة مطلوب")
    try:
        inv = invoices_repo.get_invoice(number)
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل قراءة الفاتورة %s", number)
        raise ValueError(f"تعذّر قراءة الفاتورة: {exc}") from exc
    if inv is None:
        raise ValueError(f"الفاتورة {number} غير موجودة")

    body = _invoice_body(map_of(inv))
    return render_page(f"فاتورة خلطة {number}", body)
