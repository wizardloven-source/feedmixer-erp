"""
ui/tabs/accounts.py
-------------------
تبويب «حسابات المزارع»: ملخص مالي لكل مزرعة وكشف حساب HTML قابل للطباعة.

الأعمدة: المزرعة | إجمالي الفواتير | المدفوعات | المستحق | الحالة | عدد الفواتير
الوظائف:
    - تحديث الأرقام من services.account_service (فواتير - مدفوعات = مستحق).
    - 🖨️ كشف حساب للمزرعة المحددة عبر reports.statement_html.
    - 💵 إضافة دفعة جديدة عبر PaymentDialog (operator/admin).
    - تصدير CSV/Excel وبحث فوري واختصارات عامة.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> AccountsController
    controller.refresh() / export_current() / focus_search()
"""

from __future__ import annotations

import datetime as _dt
import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data import farms_repo
from services import account_service
from ui.tabs._common import TabUI, build_tab, clear_tree, fmt

_log = get_logger("ui.tabs.accounts")


class AccountsController:
    """جدول أرصدة المزارع + إجراءات الدفع وكشوف الحساب."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.show_archived_var = tk.BooleanVar(master=parent, value=True)
        self._build(parent)
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="💰 حسابات المزارع", font=settings.FONT_LARGE_BOLD)\
            .pack(side="right")
        self.summary_var = tk.StringVar(master=head, value="")
        ttk.Label(head, textvariable=self.summary_var, font=settings.FONT_BASE)\
            .pack(side="left")

        can_pay = has_permission(self.app.user, "payments.create")
        buttons: list[tuple[str, str, Any]] = [
            ("🖨️ كشف حساب", "accent", self.print_statement),
        ]
        if can_pay:
            buttons.insert(0, ("💵 دفعة جديدة", "primary", self.add_payment))
        buttons.append(("🔄 تحديث", "flat", self.refresh))

        columns = ["farm", "billed", "paid", "balance", "status", "count"]
        headings = [
            ("farm", "المزرعة", 180), ("billed", "إجمالي الفواتير", 130),
            ("paid", "المدفوعات", 120), ("balance", "المستحق", 130),
            ("status", "الحالة", 90), ("count", "الفواتير", 80),
        ]
        self.ui: TabUI = build_tab(
            parent, self.app, columns=columns, headings=headings,
            buttons=buttons, weights=[2, 1, 1, 1, 0.7, 0.6],
        )
        for col in ("billed", "paid", "balance"):
            self.ui.tree.column(col, anchor="center")
        self.ui.tree.column("status", anchor="center")
        self.ui.tree.column("count", anchor="center")

        opts = ttk.Frame(parent)
        opts.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(opts, text="إظهار المزارع المؤرشفة",
                        variable=self.show_archived_var,
                        command=self.refresh).pack(side="right")

        self.ui.tree.bind("<Control-p>", lambda _e: self.print_statement())
        self.ui.tree.bind("<Double-1>", lambda _e: self.print_statement())
        try:
            self.ui.tree.tag_configure("owe", foreground="#c62828")
            self.ui.tree.tag_configure("credit", foreground="#2e7d32")
            self.ui.tree.tag_configure("settled", foreground="#546e7a")
        except tk.TclError:
            pass

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        """يعيد حساب كل المزارع ويعبّئ الجدول."""
        try:
            rows = account_service.all_farms_summary(
                include_archived=bool(self.show_archived_var.get()))
        except Exception:  # noqa: BLE001
            _log.exception("فشل حساب ملخصات المزارع")
            self.app.toast("فشل تحميل الحسابات", "error")
            return

        clear_tree(self.ui.tree)
        total_balance = 0.0
        for r in rows:
            balance = float(r.get("balance") or 0.0)
            total_balance += balance
            tag = "owe" if balance > 0.005 else ("credit" if balance < -0.005 else "settled")
            name = str(r.get("farm_name", ""))
            if r.get("is_archived"):
                name += " 📦"
            self.ui.tree.insert("", "end", iid=name, tags=(tag,), values=(
                name, fmt(r.get("billed_total")), fmt(r.get("paid_total")),
                fmt(balance), r.get("status", ""), r.get("invoices_count", 0),
            ))
        self.summary_var.set(f"إجمالي المستحقات على المزارع: {fmt(total_balance)}")

    # ------------------------------------------------------------ إجراءات
    def _selected_farm(self) -> str:
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر مزرعة من الجدول", "warning")
            return ""
        return str(sel[0])

    def add_payment(self) -> None:
        """يفتح PaymentDialog مع اسم المزرعة المحددة مسبقاً."""
        farm = self._selected_farm()
        if not farm:
            return
        try:
            from ui.dialogs.payment_dialog import PaymentDialog
            # إصلاح حرج: كان refresh() يُنفَّذ فور فتح الحوار (قبل إدخال أي
            # بيانات). الآن ننتظر إغلاق النافذة بـ wait_window ثم نتحقق من
            # dlg.saved — نفس نمط ui/tabs/farms.py و ui/tabs/payments.py.
            dlg = PaymentDialog(self.app, self.app, farm_name=farm)
            self.app.wait_window(dlg)
            if getattr(dlg, "saved", False):
                self.refresh()
                self.app.refresh_all()
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل فتح نافذة الدفعة")
            self.app.toast(f"خطأ: {exc}", "error")

    def print_statement(self) -> None:
        """يولّد كشف حساب HTML للمزرعة المحددة ويفتحه للطباعة."""
        farm = self._selected_farm()
        if not farm:
            return
        try:
            from reports.statement_html import generate_statement_html
            html = generate_statement_html(farm)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل توليد كشف الحساب")
            self.app.toast(f"تعذّر الطباعة: {exc}", "error")
            return
        self.app.show_html(f"كشف حساب {farm}", html)

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        self.ui.export("accounts")

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass

    def new_record(self) -> None:
        """Ctrl+N يفتح دفعة جديدة للمزرعة المحددة، أو يعرض قائمة اختيار."""
        if not has_permission(self.app.user, "payments.create"):
            self.app.toast("صلاحية عرض فقط - لا يمكن إضافة دفعة", "error")
            return
        farm = self._selected_farm()
        if farm:
            self.add_payment()
            return
        try:
            names = [str(f["name"]) for f in farms_repo.list_farms()]
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحميل أسماء المزارع")
            names = []
        if not names:
            self.app.toast("لا توجد مزارع — أضف مزرعة أولاً", "warning")
            return
        self._pick_farm_and_pay(names)

    def _pick_farm_and_pay(self, names: list[str]) -> None:
        """نافذة مصغرة لاختيار مزرعة ثم فتح PaymentDialog لها."""
        win = tk.Toplevel(self.app)
        win.title("اختر مزرعة لتسجيل دفعة")
        win.geometry("340x380")
        try:
            from ui import styles

            styles.apply_theme(win)
        except Exception:  # noqa: BLE001
            pass
        ttk.Label(win, text="المزرعة:", font=settings.FONT_BASE).pack(anchor="e", padx=10, pady=(8, 2))
        combo = ttk.Combobox(win, values=names, state="readonly", font=settings.FONT_BASE)
        combo.pack(fill="x", padx=10)
        combo.current(0)
        today = _dt.date.today().isoformat()
        ttk.Label(win, text=f"تاريخ اليوم: {today}", font=settings.FONT_SMALL)\
            .pack(anchor="e", padx=10, pady=6)

        def go() -> None:
            farm = str(combo.get()).strip()
            win.destroy()
            if farm:
                try:
                    from ui.dialogs.payment_dialog import PaymentDialog

                    # إصلاح حرج (نفس نمط add_payment): انتظار إغلاق الحوار
                    # قبل التحديث، والتحقق من dlg.saved — وإلا كان refresh()
                    # يُنفَّذ فوراً قبل أن يُدخل المستخدم أي بيانات.
                    dlg = PaymentDialog(self.app, self.app, farm_name=farm)
                    self.app.wait_window(dlg)
                    if getattr(dlg, "saved", False):
                        self.refresh()
                        self.app.refresh_all()
                except Exception as exc:  # noqa: BLE001
                    _log.exception("فشل فتح نافذة الدفعة")
                    self.app.toast(f"خطأ: {exc}", "error")

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="💵 تسجيل دفعة", command=go).pack(side="right")
        ttk.Button(bar, text="إلغاء", command=win.destroy).pack(side="left")


def build(parent: tk.Misc, app: Any) -> AccountsController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return AccountsController(parent, app)
