"""
ui/tabs/payments.py
-------------------
تبويب «المدفوعات»: جدول مدفوعات المزارع (payments) مع فلاتر.

الأعمدة: # | المزرعة | التاريخ | المبلغ | الطريقة | المرجع | ملاحظات | المستخدم
الفلاتر: مزرعة + طريقة الدفع. الوظائف: ➕ دفعة / ✏️ تعديل / 🗑️ حذف (payments.*)
كل دفعة مرتبطة بكشوف الحسابات تلقائياً عبر services.account_service.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> PaymentsController
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data import farms_repo, payments_repo
from ui.tabs._common import TabUI, build_tab, fmt

_log = get_logger("ui.tabs.payments")


class PaymentsController:
    """كنترولر تبويب المدفوعات."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.farm_filter_var = tk.StringVar(master=parent, value="")
        self.method_filter_var = tk.StringVar(master=parent, value="")
        self.total_var = tk.StringVar(master=parent, value="")
        self._build(parent)
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="💵 المدفوعات", font=settings.FONT_LARGE_BOLD).pack(side="right")
        ttk.Label(head, textvariable=self.total_var, font=settings.FONT_BASE).pack(side="left")

        can_edit = has_permission(self.app.user, "payments.create")
        buttons: list[tuple[str, str, Any]] = []
        if can_edit:
            buttons += [("➕ دفعة جديدة", "primary", self.new_record),
                        ("✏️ تعديل", "accent", self.edit_selected)]
        if has_permission(self.app.user, "payments.delete"):
            buttons.append(("🗑️ حذف", "danger", self.delete_selected))
        buttons.append(("🔄 تحديث", "flat", self.refresh))

        columns = ["id", "farm", "date", "amount", "method", "reference", "notes", "user"]
        headings = [
            ("id", "#", 45), ("farm", "المزرعة", 160), ("date", "التاريخ", 100),
            ("amount", "المبلغ", 120), ("method", "الطريقة", 90),
            ("reference", "المرجع", 130), ("notes", "ملاحظات", 200), ("user", "بواسطة", 100),
        ]
        self.ui: TabUI = build_tab(parent, self.app, columns=columns, headings=headings,
                                   buttons=buttons, weights=[0, 1.8, 1, 1.2, 0.8, 1.2, 2, 0.9])
        self.ui.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.ui.tree.bind("<Delete>", lambda _e: self.delete_selected())

        filters = ttk.Frame(parent)
        filters.pack(fill="x", pady=(4, 0))
        ttk.Label(filters, text="مزرعة:", font=settings.FONT_BASE).pack(side="right")
        self.farm_combo = ttk.Combobox(filters, textvariable=self.farm_filter_var,
                                       width=18, state="readonly", font=settings.FONT_BASE)
        self.farm_combo.pack(side="right", padx=4)
        ttk.Label(filters, text="الطريقة:", font=settings.FONT_BASE).pack(side="right")
        self.method_combo = ttk.Combobox(filters, textvariable=self.method_filter_var,
                                         width=10, state="readonly", font=settings.FONT_BASE,
                                         values=["", *settings.PAYMENT_METHODS])
        self.method_combo.pack(side="right", padx=4)
        for combo in (self.farm_combo, self.method_combo):
            combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Button(filters, text="مسح الفلاتر", command=self._clear_filters)\
            .pack(side="left", padx=4)

    def _clear_filters(self) -> None:
        self.farm_filter_var.set("")
        self.method_filter_var.set("")
        self.refresh()

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        """يعيد تحميل المدفوعات مع تطبيق الفلاتر وملخص المجاميع."""
        farm = str(self.farm_filter_var.get()).strip() or None
        method = str(self.method_filter_var.get()).strip() or None
        try:
            rows = payments_repo.list_payments(farm=farm, method=method)
            names = [str(f["name"]) for f in farms_repo.list_farms(include_archived=True)]
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحميل المدفوعات")
            self.app.toast("فشل تحميل المدفوعات", "error")
            return
        if "" not in names:
            self.farm_combo.configure(values=["", *names])
        tree = self.ui.tree
        tree.delete(*tree.get_children())
        total = 0.0
        for r in rows:
            amount = float(r.get("amount") or 0.0)
            total += amount
            tree.insert("", "end", iid=str(r["id"]), values=(
                r["id"], r.get("farm_name", ""), str(r.get("payment_date", ""))[:10],
                fmt(amount), r.get("method", ""), r.get("reference", "") or "",
                r.get("notes", "") or "", r.get("created_by", "") or "",
            ))
        scope = f"لمزرعة {farm}" if farm else "للجميع"
        self.total_var.set(f"إجمالي المدفوعات ({scope}): {fmt(total)}")

    # ------------------------------------------------------------ إجراءات
    def _selected_id(self) -> int:
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر دفعة من الجدول", "warning")
            return 0
        try:
            return int(sel[0])
        except (TypeError, ValueError):
            return 0

    def _open_dialog(self, payment: dict | None, farm_name: str = "") -> None:
        from ui.dialogs.payment_dialog import PaymentDialog

        dlg = PaymentDialog(self.app, self.app, payment=payment, farm_name=farm_name)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()
            self.app.refresh_all()

    def new_record(self) -> None:
        if not has_permission(self.app.user, "payments.create"):
            self.app.toast("لا تملك صلاحية تسجيل المدفوعات", "error")
            return
        farm = str(self.farm_filter_var.get()).strip()
        self._open_dialog(None, farm_name=farm)

    def edit_selected(self) -> None:
        if not has_permission(self.app.user, "payments.create"):
            self.app.toast("لا تملك صلاحية تعديل المدفوعات", "error")
            return
        pid = self._selected_id()
        if not pid:
            return
        payment = payments_repo.get_payment(pid)
        if not payment:
            self.app.toast("الدفعة غير موجودة", "error")
            return
        self._open_dialog(payment)

    def delete_selected(self) -> None:
        if not has_permission(self.app.user, "payments.delete"):
            self.app.toast("لا تملك صلاحية حذف المدفوعات", "error")
            return
        pid = self._selected_id()
        if not pid:
            return
        payment = payments_repo.get_payment(pid) or {}
        if not messagebox.askyesno(
                "حذف دفعة",
                f"سيُحذف سجل دفعة بمبلغ {fmt(payment.get('amount'))} "
                f"لمزرعة «{payment.get('farm_name', '')}» نهائياً.\nمتأكد؟",
                parent=self.app):
            return
        try:
            ok = payments_repo.delete_payment(pid)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل حذف الدفعة %s", pid)
            self.app.toast(str(exc), "error")
            return
        if ok:
            self.app.toast("تم حذف الدفعة", "success")
            self.refresh()
            self.app.refresh_all()

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        self.ui.export("payments")

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass


def build(parent: tk.Misc, app: Any) -> PaymentsController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return PaymentsController(parent, app)
