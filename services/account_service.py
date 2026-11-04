"""
services/account_service.py
---------------------------
حسابات المزارع ومستحقاتها.

القاعدة المعتمدة:
    المستحق على المزرعة = Σ صافي فواتير الخلطات غير المحذوفة - Σ المدفوعات

يوفّر هذا الملف:
    * farm_summary(farm)         : ملخص مزرعة واحدة.
    * all_farms_summary()        : جدول الحسابات لكل المزارع (لتبويب Accounts).
    * account_statement(farm, from, to) : حركة كشف حساب مفصّل للفاتورة HTML.
    * totals_overview()          : إجماليات عامة (مستحق/مسدد/متأخر).

تُستثنى الفواتير المكشوفة محذوفاً (is_deleted=1) من كل الحسابات.
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger
from core.utils import round_money, safe_float
from data import farms_repo, invoices_repo, payments_repo
from data.connection import query_all, query_one

log = get_logger("services.account")


# ============================================================
# غلاف استعلام آمن (قراءة تقارير لا يجب أن تُسقط الواجهة)
# ============================================================

def query_one_safe(sql: str, params: tuple[Any, ...] | None = None) -> dict | None:
    """غلّف query_one بمعالجة أخطاء تُرجع None بدل الرمي."""
    try:
        return query_one(sql, params or ())
    except Exception:
        log.exception("فشل استعلام: %s", sql[:80])
        return None


# ============================================================
# ملخص مزرعة واحدة
# ============================================================

def farm_invoices_total(farm_name: str) -> float:
    """Σ mixer_net_cost لفواتير المزرعة غير المحذوفة."""
    row = query_one_safe(
        "SELECT COALESCE(SUM(mixer_net_cost), 0) AS total"
        " FROM mix_invoices WHERE farm_name = ? AND COALESCE(is_deleted, 0) = 0",
        (str(farm_name or ""),),
    )
    return round_money(safe_float((row or {}).get("total")))


def farm_summary(farm_name: str) -> dict[str, Any]:
    """
    ملخص حسابي كامل لمزرعة:
        billed_total , paid_total , balance (المستحق) , invoices_count ,
        unpaid_count , last_invoice_date , last_payment_date
    """
    name = str(farm_name or "")
    billed = farm_invoices_total(name)
    paid = round_money(payments_repo.total_payments_by_farm(name))
    balance = round_money(billed - paid)

    inv_row = query_one_safe(
        "SELECT COUNT(*) AS n,"
        " SUM(CASE WHEN payment_status = 'unpaid' THEN 1 ELSE 0 END) AS unpaid,"
        " MAX(mix_date) AS last_date"
        " FROM mix_invoices WHERE farm_name = ? AND COALESCE(is_deleted,0) = 0",
        (name,),
    ) or {}
    pay_row = query_one_safe(
        "SELECT MAX(payment_date) AS last_date FROM payments WHERE farm_name = ?",
        (name,),
    ) or {}

    farm = farms_repo.get_farm_by_name(name) or {}
    return {
        "farm_name": name,
        "phone": str(farm.get("phone", "") or ""),
        "transport_fee": safe_float(farm.get("transport_fee")),
        "is_archived": bool(farm.get("is_archived")),
        "billed_total": billed,
        "paid_total": paid,
        "balance": balance,
        "invoices_count": int(inv_row.get("n") or 0),
        "unpaid_count": int(inv_row.get("unpaid") or 0),
        "last_invoice_date": str(inv_row.get("last_date") or ""),
        "last_payment_date": str(pay_row.get("last_date") or ""),
        "status": ("عليه" if balance > 0.005 else
                   "له" if balance < -0.005 else "مسدد"),
    }


# ============================================================
# جدول الحسابات لكل المزارع
# ============================================================

def all_farms_summary(include_archived: bool = True) -> list[dict[str, Any]]:
    """
    قائمة ملخصات لكل المزارع مرتبة تنازلياً حسب المستحق (الأعلى دَيناً أولاً).
    تُضمَّن كذلك مزارع لها فواتير/مدفوعات رغم أرشفتها أو حذفها من الجدول.
    """
    names: list[str] = []
    for f in farms_repo.list_farms(include_archived=include_archived):
        names.append(str(f.get("name")))

    # أسماء وردت في الحركات المالية لكنها ليست في جدول المزارع
    extra_rows = query_all(
        "SELECT DISTINCT farm_name FROM mix_invoices WHERE COALESCE(is_deleted,0)=0"
        " UNION SELECT DISTINCT farm_name FROM payments"
    )
    for r in extra_rows:
        n = str(r.get("farm_name") or "")
        if n and n not in names:
            names.append(n)

    summaries = [farm_summary(n) for n in names if n]
    summaries.sort(key=lambda s: s["balance"], reverse=True)
    return summaries


def totals_overview() -> dict[str, float]:
    """إجماليات عامة للوحة التحكم وشريط حالة تبويب الحسابات."""
    rows = all_farms_summary()
    billed = sum(float(r["billed_total"]) for r in rows)
    paid = sum(float(r["paid_total"]) for r in rows)
    due = sum(float(r["balance"]) for r in rows if float(r["balance"]) > 0)
    credit = sum(-float(r["balance"]) for r in rows if float(r["balance"]) < 0)
    debtors = sum(1 for r in rows if float(r["balance"]) > 0.005)
    return {
        "billed_total": round_money(billed),
        "paid_total": round_money(paid),
        "outstanding": round_money(due),
        "advance_credits": round_money(credit),
        "debtors_count": float(debtors),
    }


# ============================================================
# كشف الحساب المفصّل (يُغذّي reports/statement_html.py)
# ============================================================

def account_statement(farm_name: str,
                      date_from: str | None = None,
                      date_to: str | None = None) -> dict[str, Any]:
    """
    حركة كشف حساب مرتبة زمنياً:
       كل سطر = {date, kind: 'invoice'|'payment', ref, desc, debit, credit}
    debit  = على المزرعة (فاتورة)   credit = مدفوع (دفعة)
    يعيد أيضاً رصيداً تراكمياً running_balance وسجل الفترة.
    """
    name = str(farm_name or "")
    entries: list[dict[str, Any]] = []

    for inv in invoices_repo.list_invoices(farm=name, date_from=date_from,
                                           date_to=date_to):
        entries.append({
            "date": str(inv.get("mix_date", "")),
            "kind": "invoice",
            "ref": str(inv.get("mix_number", "")),
            "desc": f"خلطة رقم {inv.get('mix_number')} - "
                    f"{safe_float(inv.get('total_weight_kg') or inv.get('total_weight')):,.0f} كغ",
            "debit": round_money(inv.get("mixer_net_cost")),
            "credit": 0.0,
            "payment_status": str(inv.get("payment_status", "")),
        })

    for pay in payments_repo.payments_by_farm(name):
        pdate = str(pay.get("payment_date", ""))
        if date_from and pdate < date_from:
            continue
        if date_to and pdate > date_to:
            continue
        entries.append({
            "date": pdate,
            "kind": "payment",
            "ref": str(pay.get("reference", "") or f"سند-{pay.get('id')}"),
            "desc": f"دفعة ({pay.get('method', '')})",
            "debit": 0.0,
            "credit": round_money(pay.get("amount")),
            "payment_status": "",
        })

    entries.sort(key=lambda e: (e["date"], 0 if e["kind"] == "invoice" else 1))

    running = 0.0
    for e in entries:
        running += e["debit"] - e["credit"]
        e["running_balance"] = round_money(running)

    total_debit = round_money(sum(e["debit"] for e in entries))
    total_credit = round_money(sum(e["credit"] for e in entries))

    summary = farm_summary(name)
    return {
        "farm": summary,
        "entries": entries,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "period_balance": round_money(total_debit - total_credit),
        "overall_balance": summary["balance"],
        "date_from": date_from or "",
        "date_to": date_to or "",
    }
