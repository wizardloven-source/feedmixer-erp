"""
ui/tabs/dashboard.py
--------------------
تبويب "الرئيسية": بطاقات إحصائية + تنبيهات ذكية + إجراءات سريعة.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> DashboardController
    controller.refresh()          (F5)
    controller.export_current()   (Ctrl+C)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from ui.widgets import make_button, make_card

_log = get_logger("ui.tabs.dashboard")


class DashboardController:
    """يدير عناصر لوحة الرئيسية ويحدّثها من الخدمات."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.parent = parent
        self.app = app
        self.cards: dict[str, dict[str, Any]] = {}
        self._build()
        self.refresh()

    # ------------------------------------------------------------
    def _build(self) -> None:
        head = ttk.Frame(self.parent)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="لوحة التحكم", font=settings.FONT_LARGE_BOLD).pack(side="left")
        make_button(head, "🔄 تحديث", self.refresh, kind="flat")

        # صف البطاقات
        row1 = ttk.Frame(self.parent)
        row1.pack(fill="x", pady=4)
        for key, title in (("invoices_today", "فواتير اليوم"),
                           ("mix_tons_month", "أطنان هذا الشهر"),
                           ("purchases_month", "توريدات الشهر (﷼)"),
                           ("receivable", "مستحقات المزارع (﷼)")):
            card = make_card(row1, title)
            card["frame"].pack(side="left", expand=True, fill="both", padx=4)
            self.cards[key] = card

        row2 = ttk.Frame(self.parent)
        row2.pack(fill="x", pady=4)
        for key, title in (("low_stock", "أصناف < 5 طن"),
                           ("unpaid_count", "فواتير غير مدفوعة"),
                           ("materials_count", "عدد المواد"),
                           ("farms_count", "المزارع النشطة")):
            card = make_card(row2, title)
            card["frame"].pack(side="left", expand=True, fill="both", padx=4)
            self.cards[key] = card

        # التنبيهات
        lf = ttk.LabelFrame(self.parent, text=" ⚠️ التنبيهات الذكية ", padding=6)
        lf.pack(fill="both", expand=True, pady=6)
        self.alerts_text = tk.Text(lf, height=8, wrap="word",
                                   font=settings.FONT_BASE, state="disabled")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.alerts_text.yview)
        self.alerts_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.alerts_text.pack(fill="both", expand=True)

        # أزرار تنقل سريع
        nav = ttk.Frame(self.parent)
        nav.pack(fill="x", pady=6)
        for label, tab_key, perm in (
            ("🧪 بدء خلطة جديدة", "mix", "mix.create"),
            ("🚚 تسجيل توريد", "purchases", "purchases.create"),
            ("💰 تسجيل دفعة", "accounts", "payments.create"),
            ("📊 فتح التقارير", "reports", "view"),
        ):
            if self.app.can(perm):
                make_button(nav, label, lambda k=tab_key: self.app.open_tab(k),
                            kind="accent").pack(side="left", padx=4)

    # ------------------------------------------------------------
    def refresh(self) -> None:
        try:
            import datetime as _dt

            from core import cache
            from data import invoices_repo, purchases_repo
            from services import account_service, alert_service, inventory_service

            counters = alert_service.dashboard_counters()
            overview = account_service.totals_overview()

            today = _dt.date.today().isoformat()
            month = today[:7]

            todays = [r for r in invoices_repo.list_invoices(date_from=today)
                      if str(r.get("mix_date", "")) == today]
            month_rows = [r for r in invoices_repo.list_invoices(date_from=month + "-01")
                          if str(r.get("mix_date", "")).startswith(month)]
            tons_month = sum(float(r.get("total_weight") or 0) for r in month_rows)

            purch_month = 0.0
            for p in purchases_repo.list_purchases(date_from=month + "-01"):
                if str(p.get("purchase_date", "")).startswith(month):
                    purch_month += float(p.get("total_cost") or 0)

            low = inventory_service.low_stock_items()
            unpaid = invoices_repo.list_invoices(payment_status="unpaid")

            values = {
                "invoices_today": f"{len(todays)}",
                "mix_tons_month": f"{tons_month:,.1f} طن",
                "purchases_month": f"{purch_month:,.0f}",
                "receivable": f"{overview.get('outstanding', 0.0):,.0f}",
                "low_stock": f"{len(low)}",
                "unpaid_count": f"{counters.get('unpaid_count', len(unpaid))}",
                "materials_count": f"{len(cache.material_names())}",
                "farms_count": f"{len(cache.farm_names(include_archived=False))}",
            }
            for key, card in self.cards.items():
                try:
                    card["set_value"](values.get(key, "-"))
                except tk.TclError:
                    pass

            alerts = alert_service.collect_alerts()
            lines = []
            for a in alerts:
                icon = {"warning": "⚠️", "danger": "🛑", "info": "ℹ️"}.get(a.get("level", "info"), "•")
                lines.append(f"{icon} {a.get('title','')}: {a.get('message','')}")
            self.alerts_text.configure(state="normal")
            self.alerts_text.delete("1.0", "end")
            self.alerts_text.insert("1.0", "\n".join(lines) if lines else "✅ لا توجد تنبيهات حالياً")
            self.alerts_text.configure(state="disabled")
        except Exception:
            _log.exception("فشل تحديث لوحة الرئيسية")
            self.app.toast("تعذّر تحديث اللوحة الرئيسية", "error")

    # ------------------------------------------------------------
    def export_current(self) -> None:
        """يصدّر ملخص البطاقات إلى CSV في مجلد التصدير."""
        try:
            import csv

            from config.settings import EXPORT_DIR

            settings.ensure_directories()
            path = EXPORT_DIR / "dashboard_summary.csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["المقياس", "القيمة"])
                for key, card in self.cards.items():
                    w.writerow([key, card["value"].cget("text")])
            self.app.toast(f"تم التصدير: {path}", "success")
        except Exception:
            _log.exception("فشل تصدير اللوحة")
            self.app.toast("فشل التصدير", "error")


def build(parent: tk.Misc, app: Any) -> DashboardController:
    """نقطة الدخول المعيارية للتبويب."""
    return DashboardController(parent, app)
