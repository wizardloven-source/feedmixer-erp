"""
reports/statement_html.py
-------------------------
توليد كشف حساب مزرعة بصيغة HTML قابل للطباعة (RTL).

الاستخدام:
    html = generate_statement_html("مزرعة السلام")
    html = generate_statement_html("مزرعة السلام", date_from="2026-01-01",
                                   date_to="2026-12-31")

المحتوى:
    ملخص المزرعة (إجمالي الفواتير / المدفوعات / المستحق)
    + جدول الحركات الزمنية مع الرصيد التراكمي.
"""

from __future__ import annotations

import logging
from typing import Any

from core.utils import safe_float
from reports._html_base import (doc_header, info_grid, money, render_page,
                                signatures, table)
from services import account_service

_log = logging.getLogger("reports.statement")


def _statement_body(data: dict[str, Any]) -> str:
    """يبني جسم صفحة كشف الحساب من بيانات account_service.account_statement."""
    summary: dict[str, Any] = data.get("farm") or {}
    entries: list[dict[str, Any]] = data.get("entries") or []
    name = str(summary.get("farm_name", ""))

    parts: list[str] = [doc_header("كشف حساب مزرعة")]
    parts.append(f'<div class="doc-title">💰 كشف حساب: {name}</div>')

    period = ""
    d_from, d_to = str(data.get("date_from") or ""), str(data.get("date_to") or "")
    if d_from or d_to:
        period = f"الفترة من {d_from or 'البداية'} إلى {d_to or 'اليوم'}"
    else:
        period = "جميع الفترات"

    grid_pairs: list[tuple[str, Any]] = [
        ("المزرعة", name),
        ("الهاتف", summary.get("phone") or "-"),
        ("الفترة", period),
        ("عدد الفواتير", summary.get("invoices_count", 0)),
        ("فواتير غير مسددة", summary.get("unpaid_count", 0)),
        ("آخر فاتورة", summary.get("last_invoice_date") or "-"),
        ("آخر دفعة", summary.get("last_payment_date") or "-"),
    ]
    parts.append(info_grid(grid_pairs))

    rows: list[list[Any]] = []
    for e in entries:
        kind_label = "🧾 فاتورة خلطة" if e.get("kind") == "invoice" else "💵 دفعة"
        debit = safe_float(e.get("debit"))
        credit = safe_float(e.get("credit"))
        rows.append([
            e.get("date", ""),
            kind_label,
            e.get("ref", ""),
            e.get("desc", ""),
            money(debit) if debit else "-",
            money(credit) if credit else "-",
            money(e.get("running_balance", 0.0)),
        ])
    parts.append(table(["التاريخ", "النوع", "المرجع", "البيان",
                        "عليه (مدين)", "له (دائن)", "الرصيد"],
                       rows, align_left_cols=(4, 5, 6)))

    balance = safe_float(data.get("overall_balance"))
    status_word = str(summary.get("status") or "")
    parts.append(_totals_block(data, balance, status_word))
    parts.append(signatures("المحاسب", "مدير الخلاطة", "توقيع المزرعة"))
    return "".join(parts)


def _totals_block(data: dict[str, Any], balance: float, status_word: str) -> str:
    """جدول مجاميع الكشف مع شريط المستحق النهائي."""
    color = "#a32020" if balance > 0.005 else ("#1c7a34" if balance < -0.005 else "#2b4c3f")
    rows_html = (
        "<table class='totals'>"
        f"<tr><th>إجمالي الفواتير</th><td style='text-align:left'>{money(data.get('total_debit'))}</td></tr>"
        f"<tr><th>إجمالي المدفوعات</th><td style='text-align:left'>{money(data.get('total_credit'))}</td></tr>"
        f"<tr><th>رصيد الفترة</th><td style='text-align:left'>{money(data.get('period_balance'))}</td></tr>"
        f"<tr class='grand'><td>المستحق النهائي ({status_word})</td>"
        f"<td style='text-align:left;color:{color};font-size:15px'>{money(balance)}</td></tr>"
        "</table>"
    )
    return rows_html


def generate_statement_html(farm_name: str,
                            date_from: str | None = None,
                            date_to: str | None = None) -> str:
    """
    يعيد نص HTML كاملاً لكشف حساب المزرعة.

    Args:
        farm_name: اسم المزرعة كما هو مسجّل.
        date_from/date_to: حدود الفترة ISO (اختياري).

    يرفع ValueError عند اسم فارغ أو عدم وجود حركات مع فشل القراءة.
    """
    name = str(farm_name or "").strip()
    if not name:
        raise ValueError("اسم المزرعة مطلوب لتوليد كشف الحساب")
    try:
        data = account_service.account_statement(name, date_from=date_from,
                                                 date_to=date_to)
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل توليد كشف حساب %s", name)
        raise ValueError(f"تعذّر توليد كشف الحساب: {exc}") from exc

    body = _statement_body(data)
    return render_page(f"كشف حساب {name}", body)
