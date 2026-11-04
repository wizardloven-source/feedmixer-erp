"""
ui/tabs/reports.py
------------------
تبويب «التقارير»: تقرير شهري (توريدات مقابل خلطات) + رسوم بيانية + تصدير.

المكونات:
    - اختيار الشهر (YYYY-MM combobox لآخر 24 شهراً) + زر توليد.
    - جدولان: ملخص المواد (مورد/مستهلك/صافي/تكلفة) والمجاميع العامة.
    - رسم matplotlib أفقي لشراء/استهلاك كل مادة (إن توفرت المكتبة؛
      وإلا تظهر رسالة توضيحة — نفس سلوك config.HAS_MATPLOTLIB).
    - أزرار تصدير CSV / Excel عبر reports.exporter للتقرير الحالي.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> ReportsController
"""

from __future__ import annotations

import datetime as _dt
import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from reports.exporter import export_table
from ui.tabs._common import TabUI, build_tab, fmt
from ui.tabs._report_data import monthly_report

_log = get_logger("ui.tabs.reports")


def recent_months(count: int = 24) -> list[str]:
    """قائمة أشهر بصيغة YYYY-MM من الأحدث إلى الأقدم."""
    today = _dt.date.today()
    months: list[str] = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return months


class ReportsController:
    """كنترولر تبويب التقارير الشهرية."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.month_var = tk.StringVar(master=parent, value=recent_months(1)[0])
        self.last_report: dict[str, Any] | None = None
        self._build(parent)
        self.generate()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="📊 التقارير الشهرية", font=settings.FONT_LARGE_BOLD)\
            .pack(side="right")

        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="الشهر:", font=settings.FONT_BASE).pack(side="right")
        combo = ttk.Combobox(bar, textvariable=self.month_var, width=10,
                             state="readonly", font=settings.FONT_BASE,
                             values=recent_months())
        combo.pack(side="right", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.generate())
        ttk.Button(bar, text="🔄 توليد التقرير", command=self.generate)\
            .pack(side="right", padx=4)
        if has_permission(self.app.user, "reports.export"):
            ttk.Button(bar, text="📤 CSV",
                       command=lambda: self.export_as("csv")).pack(side="left", padx=3)
            ttk.Button(bar, text="📗 Excel",
                       command=lambda: self.export_as("xlsx")).pack(side="left", padx=3)

        columns = ["name", "purchased_ton", "consumed_ton", "net_ton",
                   "purchase_cost", "mix_value"]
        headings = [
            ("name", "المادة", 160), ("purchased_ton", "مورّد (طن)", 110),
            ("consumed_ton", "مستهلك (طن)", 110), ("net_ton", "الصافي (طن)", 110),
            ("purchase_cost", "تكلفة الشراء", 130), ("mix_value", "قيمة الخلطات", 130),
        ]
        self.ui: TabUI = build_tab(parent, self.app, columns=columns, headings=headings,
                                   buttons=[], weights=[2, 1, 1, 1, 1.2, 1.2],
                                   search_placeholder="🔍 تصفية نتائج الجدول...")

        self.summary_var = tk.StringVar(master=parent, value="")
        ttk.Label(parent, textvariable=self.summary_var,
                  font=settings.FONT_BOLD).pack(fill="x", pady=(4, 2))

        # إطار الرسم البياني (matplotlib) أو رسالة غيابه
        self.chart_frame = ttk.LabelFrame(parent, text="الرسم البياني", padding=4)
        self.chart_frame.pack(fill="both", expand=True, pady=(2, 0))
        if not settings.HAS_MATPLOTLIB:
            ttk.Label(self.chart_frame,
                      text="مكتبة matplotlib غير مثبتة — الرسوم البيانية معطّلة "
                           "(pip install matplotlib)",
                      font=settings.FONT_SMALL, foreground="#c62828").pack(pady=12)

    # ------------------------------------------------------------ توليد
    def generate(self) -> None:
        """يبني تقرير الشهر المحدد ويعبّئ الجدول والرسم."""
        month = str(self.month_var.get()).strip()
        try:
            report = monthly_report(month)
        except ValueError as exc:
            self.app.toast(str(exc), "error")
            return
        except Exception:  # noqa: BLE001
            _log.exception("فشل توليد تقرير %s", month)
            self.app.toast("فشل توليد التقرير", "error")
            return
        self.last_report = report

        tree = self.ui.tree
        tree.delete(*tree.get_children())
        for row in report.get("materials", []):
            tree.insert("", "end", values=(
                row.get("name", ""), fmt(row.get("purchased_ton"), 2),
                fmt(row.get("consumed_ton"), 2), fmt(row.get("net_ton"), 2),
                fmt(row.get("purchase_cost")), fmt(row.get("mix_value")),
            ))
        totals = report.get("totals", {})
        self.summary_var.set(
            f"شهر {month}: توريدات {fmt(totals.get('purchase_qty'), 2)} طن "
            f"بتكلفة {fmt(totals.get('purchase_cost'))} | "
            f"خلطات {int(totals.get('mix_count') or 0)} فاتورة "
            f"علف {fmt(totals.get('feed_cost'))} | صافي إجمالي {fmt(totals.get('grand_net'))}"
        )
        self._draw_chart(report)

    # ------------------------------------------------------------ رسم
    def _draw_chart(self, report: dict[str, Any]) -> None:
        """يرسم أعمدة مورّد/مستهلك لكل مادة داخل chart_frame."""
        for child in self.chart_frame.winfo_children():
            child.destroy()
        if not settings.HAS_MATPLOTLIB:
            return
        materials = report.get("materials", [])
        if not materials:
            ttk.Label(self.chart_frame, text="لا توجد بيانات لهذا الشهر",
                      font=settings.FONT_SMALL).pack(pady=12)
            return
        try:
            import matplotlib

            matplotlib.use("TkAgg", force=False)
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure

            names = [str(m.get("name", ""))[:12] for m in materials]
            purchased = [float(m.get("purchased_ton") or 0) for m in materials]
            consumed = [float(m.get("consumed_ton") or 0) for m in materials]
            x = range(len(names))
            width = 0.4

            fig = Figure(figsize=(7, 3.2), dpi=100)
            ax = fig.add_subplot(111)
            ax.bar([i - width / 2 for i in x], purchased, width, label="مورّد (طن)",
                   color=settings.COLORS.get("primary", "#1565c0"))
            ax.bar([i + width / 2 for i in x], consumed, width, label="مستهلك (طن)",
                   color=settings.COLORS.get("accent", "#ef6c00"))
            ax.set_xticks(list(x))
            ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8)
            ax.grid(axis="y", color=settings.COLORS.get("chart_grid", "#dddddd"),
                    linewidth=0.6)
            handles, labels = ax.get_legend_handles_labels()
            ax.legend(handles[::-1], labels[::-1], loc="upper left", fontsize=8)
            fig.tight_layout()

            canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)
        except Exception:  # noqa: BLE001
            _log.exception("فشل رسم المخطط البياني")
            ttk.Label(self.chart_frame, text="تعذّر إنشاء الرسم البياني",
                      font=settings.FONT_SMALL, foreground="#c62828").pack(pady=12)

    # ------------------------------------------------------------ تصدير
    def export_as(self, kind: str) -> None:
        """يصدر جدول التقرير الحالي CSV أو xlsx عبر reports.exporter."""
        if not has_permission(self.app.user, "reports.export"):
            self.app.toast("لا تملك صلاحية تصدير التقارير", "error")
            return
        report = self.last_report
        if not report:
            self.app.toast("ولّد التقرير أولاً", "warning")
            return
        headers = ["المادة", "مورد (طن)", "مستهلك (طن)", "صافي (طن)",
                   "تكلفة الشراء", "قيمة الخلطات"]
        rows = [[m.get("name"), m.get("purchased_ton"), m.get("consumed_ton"),
                 m.get("net_ton"), m.get("purchase_cost"), m.get("mix_value")]
                for m in report.get("materials", [])]
        totals = report.get("totals", {})
        rows.append(["الإجمالي", totals.get("purchase_qty"), "", "",
                     totals.get("purchase_cost"), totals.get("feed_cost")])
        prefix = f"monthly_report_{report.get('month', '')}"
        try:
            path = export_table(headers, rows, filename_prefix=prefix,
                                as_excel=(kind == "xlsx"))
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل التصدير %s", kind)
            self.app.toast(str(exc) or "فشل التصدير", "error")
            return
        if path:
            self.app.toast(f"تم التصدير: {path}", "success")

    # ------------------------------------------------------------ واجهة عامة
    def refresh(self) -> None:
        self.generate()

    def export_current(self) -> None:
        self.export_as("csv")

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass


def build(parent: tk.Misc, app: Any) -> ReportsController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return ReportsController(parent, app)
