"""
services/alert_service.py
-------------------------
التنبيهات الذكية للوحة الرئيسية (Dashboard) وشريط الحالة.

أنواع التنبيهات:
    1) مخزون منخفض : مادة متبقٍ منها أقل من LOW_STOCK_THRESHOLD_TONS (5 طن).
    2) رصيد سالب  : استهلاك تجاوز المورد (خطأ بيانات أو نقص حاد).
    3) ديون مزارع : مزرعة بمستحق > ALARM_DEBT_THRESHOLD (قابل للإعداد).
    4) بدون توريد : مادة مُسعرّة ولم يرد لها أي توريد منذ 60 يوماً.
    5) فاتورة غير مسددة لفترة طويلة (أكثر من 30 يوماً بحالة unpaid).

كل دالة تعيد قائمة قوامها:
    {level: 'danger'|'warning'|'info', title, message, table_hint}
حيث table_hint معرّف السجل للقفز إليه من اللوحة عند النقر على التنبيه.

عتبات العرض تُقرأ من جدول settings إن وُجدت، مع قيم افتراضية آمنة.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from config import settings
from core.logger import get_logger
from core.utils import round_money, safe_float
from data.connection import query_all, query_one
from data.settings_repo import get_setting
from services import account_service, inventory_service

log = get_logger("services.alert")

# عتبات افتراضية (تُجاوز عبر الإعدادات إن وُجدت مفاتيح مشابهة)
DEFAULT_DEBT_ALARM = 50_000.0        # تنبيه ديون فوق هذا المبلغ
DEFAULT_STALE_DAYS = 60              # مادة بلا توريد منذ N يوم
DEFAULT_UNPAID_AGE_DAYS = 30         # فاتورة unpaid منذ أكثر من N يوم


def _alert(level: str, title: str, message: str,
           table_hint: str = "") -> dict[str, Any]:
    """صانع موحّد لقاموس التنبيه."""
    return {"level": level, "title": title, "message": message,
            "table_hint": table_hint}


# ============================================================
# مخزون
# ============================================================

def low_stock_alerts() -> list[dict[str, Any]]:
    """تنبيهات الأصناف تحت الحد الأدنى (تحذير) والرصيد السالب (خطر)."""
    alerts: list[dict[str, Any]] = []
    try:
        for row in inventory_service.low_stock_items():
            name = str(row.get("name"))
            rem = safe_float(row.get("remaining_ton"))
            if rem < 0:
                alerts.append(_alert(
                    "danger", f"رصيد سالب: {name}",
                    f"المتبقي {rem:,.2f} طن — مراجعة التوريدات والخلطات.",
                    table_hint=f"inventory:{name}",
                ))
            else:
                alerts.append(_alert(
                    "warning", f"مخزون منخفض: {name}",
                    f"المتبقي {rem:,.2f} طن فقط (الحد {settings.LOW_STOCK_THRESHOLD_TONS} طن).",
                    table_hint=f"inventory:{name}",
                ))
    except Exception:
        log.exception("فشل حساب تنبيهات المخزون")
    return alerts


def stale_materials_alerts(days: int = DEFAULT_STALE_DAYS) -> list[dict[str, Any]]:
    """مواد لم يسجَّل لها أي توريد منذ `days` يوماً رغم وجود حركة صرف."""
    alerts: list[dict[str, Any]] = []
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = query_all(
            "SELECT m.name,"
            "       (SELECT MAX(p.purchase_date) FROM purchases p"
            "        WHERE p.material_name = m.name) AS last_buy"
            " FROM materials m ORDER BY m.name"
        )
        for r in rows:
            name = str(r.get("name") or "")
            last = str(r.get("last_buy") or "")
            if not last:
                continue  # لا يوجد توريد إطلاقاً => يغطيه تنبيه المخزون المنخفض
            if last < cutoff:
                bal = inventory_service.balance_of(name)
                if bal < settings.LOW_STOCK_THRESHOLD_TONS:
                    alerts.append(_alert(
                        "info", f"توريد متأخر: {name}",
                        f"آخر توريد في {last} والمتبقي {bal:,.2f} طن.",
                        table_hint=f"purchases:{name}",
                    ))
    except Exception:
        log.exception("فشل حساب تنبيهات التوريد المتأخر")
    return alerts


# ============================================================
# ديون المزارع
# ============================================================

def debt_alerts(threshold: float | None = None) -> list[dict[str, Any]]:
    """مزارع مستحقاتها فوق العتبة — danger فوق ضعفها، warning فوق العتبة."""
    limit = threshold if threshold is not None else safe_float(
        get_setting("debt_alarm_threshold", DEFAULT_DEBT_ALARM), DEFAULT_DEBT_ALARM)
    alerts: list[dict[str, Any]] = []
    try:
        for s in account_service.all_farms_summary():
            bal = safe_float(s.get("balance"))
            if bal <= limit:
                continue
            level = "danger" if bal >= limit * 2 else "warning"
            last = s.get("last_invoice_date") or "لا يوجد"
            alerts.append(_alert(
                level, f"دَين مرتفع: {s['farm_name']}",
                f"المستحق {round_money(bal):,.2f} ج.م (آخر خلطة: {last}).",
                table_hint=f"accounts:{s['farm_name']}",
            ))
    except Exception:
        log.exception("فشل حساب تنبيهات الديون")
    return alerts


def old_unpaid_alerts(days: int = DEFAULT_UNPAID_AGE_DAYS) -> list[dict[str, Any]]:
    """فواتير ما زالت unpaid منذ أكثر من `days` يوماً."""
    alerts: list[dict[str, Any]] = []
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = query_all(
            "SELECT mix_number, farm_name, mix_date, mixer_net_cost"
            " FROM mix_invoices"
            " WHERE COALESCE(is_deleted,0)=0 AND payment_status='unpaid'"
            "   AND mix_date < ?"
            " ORDER BY mix_date ASC LIMIT 50",
            (cutoff,),
        )
        for r in rows:
            alerts.append(_alert(
                "warning",
                f"فاتورة غير مسددة: {r.get('mix_number')}",
                f"{r.get('farm_name')} بتاريخ {r.get('mix_date')} — "
                f"مبلغ {safe_float(r.get('mixer_net_cost')):,.2f} ج.م.",
                table_hint=f"invoices:{r.get('mix_number')}",
            ))
    except Exception:
        log.exception("فشل حساب الفواتير القديمة غير المسددة")
    return alerts


# ============================================================
# التجميع للوحة الرئيسية
# ============================================================

def collect_alerts(include_unpaid_list: bool = False) -> list[dict[str, Any]]:
    """
    كل التنبيهات مجمّعة ومرتبة حسب الخطورة (danger ثم warning ثم info).
    تُستخدم في dashboard.refresh().
    """
    all_alerts: list[dict[str, Any]] = []
    all_alerts += low_stock_alerts()
    all_alerts += debt_alerts()
    all_alerts += stale_materials_alerts()
    if include_unpaid_list:
        all_alerts += old_unpaid_alerts()

    order = {"danger": 0, "warning": 1, "info": 2}
    all_alerts.sort(key=lambda a: order.get(str(a.get("level")), 9))
    return all_alerts


def status_line() -> str:
    """سطر مختصر لشريط الحالة: عدد التنبيهات الحرجة/الإنذارات."""
    try:
        alerts = collect_alerts()
    except Exception:
        log.exception("فشل توليد سطر الحالة")
        return "⚠ تعذّر حساب التنبيهات"
    danger = sum(1 for a in alerts if a["level"] == "danger")
    warn = sum(1 for a in alerts if a["level"] == "warning")
    if not alerts:
        return "✓ لا تنبيهات — النظام سليم"
    parts = []
    if danger:
        parts.append(f"🔴 {danger} حرج")
    if warn:
        parts.append(f"🟡 {warn} تحذير")
    rest = len(alerts) - danger - warn
    if rest:
        parts.append(f"🔵 {rest} معلوماتي")
    return "تنبيهات: " + " | ".join(parts)


def dashboard_counters() -> dict[str, float]:
    """بطاقات الأرقام أعلى اللوحة الرئيسية (يقرأها تبويب dashboard)."""
    counters: dict[str, float] = {}
    try:
        inv = inventory_service.summary_totals()
        counters["materials_count"] = inv["materials_count"]
        counters["stock_remaining_ton"] = inv["remaining_ton"]
        counters["low_stock_count"] = inv["low_count"]

        acc = account_service.totals_overview()
        counters["billed_total"] = acc["billed_total"]
        counters["paid_total"] = acc["paid_total"]
        counters["outstanding"] = acc["outstanding"]

        month_row = query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total_weight),0) AS w,"
            " COALESCE(SUM(mixer_net_cost),0) AS c FROM mix_invoices"
            " WHERE COALESCE(is_deleted,0)=0 AND substr(mix_date,1,7)=?"
            "   AND 1=1",
            (datetime.now().strftime("%Y-%m"),),
        ) or {}
        counters["month_mixes"] = safe_float(month_row.get("n"))
        counters["month_weight_kg"] = safe_float(month_row.get("w"))
        counters["month_cost"] = safe_float(month_row.get("c"))

        pur_row = query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(qty_ton),0) AS t,"
            " COALESCE(SUM(total_cost),0) AS c FROM purchases"
            " WHERE substr(purchase_date,1,7)=?",
            (datetime.now().strftime("%Y-%m"),),
        ) or {}
        counters["month_purchases"] = safe_float(pur_row.get("n"))
        counters["month_purchase_tons"] = safe_float(pur_row.get("t"))
        counters["month_purchase_cost"] = safe_float(pur_row.get("c"))
    except Exception:
        log.exception("فشل حساب عدّادات اللوحة الرئيسية")
    return counters
