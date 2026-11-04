"""
ui/tabs/invoices.py
-------------------
تبويب «الفواتير»: قائمة فواتير الخلطة مع الفلاتر والحالة،
تغيير حالة الدفع، الحذف الناعم (سلة محذوفات + استعادة)،
فتح الفاتورة في تبويب الخلطة للتعديل، والطباعة HTML.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> InvoicesController
    controller.new_record()     (Ctrl+N) -> يفتح تبويب الخلطة بنموذج جديد
    controller.print_current()  (Ctrl+P) -> طباعة الفاتورة المحددة
    controller.refresh()        (F5)
    controller.export_current() (Ctrl+C)
    controller.focus_search()   (Ctrl+F)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from config import settings
from core import cache
from core.logger import get_logger
from core.permissions import has_permission
from data import invoices_repo
from ui.tabs._common import TabUI, build_tab, clear_tree, fmt

_log = get_logger("ui.tabs.invoices")

STATUS_AR = {"unpaid": "غير مدفوعة", "partial": "جزئية", "paid": "مدفوعة"}


class InvoicesController:
    """جدول الفواتير + سلة المحذوفات."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self._built = False
        self.ui: TabUI | None = None
        self.farm_var = tk.StringVar(master=parent, value="all")
        self.status_var = tk.StringVar(master=parent, value="all")
        self.show_deleted_var = tk.BooleanVar(master=parent, value=False)
        self.summary_var = tk.StringVar(master=parent, value="")
        self._build(parent)
        self._built = True
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="🧾 فواتير الخلطة", font=settings.FONT_LARGE_BOLD)\
            .pack(side="right")
        ttk.Label(head, textvariable=self.summary_var, font=settings.FONT_BASE)\
            .pack(side="left")

        filters = ttk.Frame(parent)
        filters.pack(fill="x", pady=(0, 4))
        ttk.Label(filters, text="المزرعة:", width=9).pack(side="right")
        self.farm_combo = ttk.Combobox(filters, textvariable=self.farm_var,
                                       width=16, state="readonly", values=["all"])
        self.farm_combo.pack(side="right", padx=3)
        self.farm_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        ttk.Label(filters, text="الحالة:", width=8).pack(side="right", padx=(12, 0))
        status_map = {"all": "الكل", "unpaid": "غير مدفوعة",
                      "partial": "جزئية", "paid": "مدفوعة"}
        self.status_combo = ttk.Combobox(
            filters, values=list(status_map.values()), width=12, state="readonly")
        self.status_combo.set("الكل")
        self.status_combo.pack(side="right", padx=3)

        def _on_status(*_a: Any) -> None:
            inv = {v: k for k, v in status_map.items()}
            self.status_var.set(inv.get(self.status_combo.get(), "all"))
            self.refresh()

        self.status_combo.bind("<<ComboboxSelected>>", _on_status)

        chk = ttk.Checkbutton(filters, text="عرض سلة المحذوفات",
                              variable=self.show_deleted_var,
                              command=self.refresh)
        chk.pack(side="right", padx=14)

        buttons: list[tuple[str, str, Any]] = [
            ("🔄 تحديث", "flat", self.refresh),
            ("📤 تصدير", "flat", self.export_current),
            ("🖨️ طباعة", "flat", self.print_current),
            ("✏️ تعديل بالخلطة", "flat", self.edit_in_mix_tab),
        ]
        if has_permission(self.app.user, "invoices.delete"):
            buttons += [("🗑️ حذف ناعم", "danger", self.soft_delete)]
        if has_permission(self.app.user, "invoices.restore"):
            buttons += [("♻️ استعادة", "success", self.restore_selected),
                        ("❌ حذف نهائي", "danger", self.permanent_delete)]

        self.ui = build_tab(
            parent, self.app,
            columns=["number", "date", "farm", "worker", "weight", "billable",
                     "feed", "elec", "labor", "transport", "net", "status",
                     "manual", "notes"],
            headings=[
                ("number", "رقم الخلطة", 110),
                ("date", "التاريخ", 90),
                ("farm", "المزرعة", 120),
                ("worker", "العامل", 90),
                ("weight", "الوزن كغ", 85),
                ("billable", "أطنان", 70),
                ("feed", "العلف", 95),
                ("elec", "كهرباء", 75),
                ("labor", "عمال", 80),
                ("transport", "نقل", 80),
                ("net", "الصافي", 100),
                ("status", "الدفع", 90),
                ("manual", "يدوي", 55),
                ("notes", "ملاحظات", 140),
            ],
            buttons=buttons,
        )
        try:
            self.ui.tree.tag_configure("unpaid",
                                       foreground=settings.COLORS.get("danger", "#b00020"))
            self.ui.tree.tag_configure("partial",
                                       foreground=settings.COLORS.get("warning", "#b8860b"))
            self.ui.tree.tag_configure("paid",
                                       foreground=settings.COLORS.get("success", "#1a7f37"))
            self.ui.tree.tag_configure("deleted",
                                       foreground=settings.COLORS.get("muted", "#888888"))
        except tk.TclError:
            pass
        self.ui.tree.bind("<Double-1>", lambda _e: self.show_items_popup())
        self.ui.tree.bind("<Control-p>", lambda _e: self.print_current())

    # ------------------------------------------------------------ تحديث
    def refresh(self) -> None:
        if not self._built or self.ui is None:
            return
        try:
            farms = ["all"] + cache.farm_names(include_archived=True, force=True)
            self.farm_combo.configure(values=farms)
            rows = invoices_repo.list_invoices(
                include_deleted=bool(self.show_deleted_var.get()),
                farm=None if self.farm_var.get() in ("", "all") else self.farm_var.get(),
                payment_status=None if self.status_var.get() == "all"
                else self.status_var.get(),
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل قراءة الفواتير")
            self.app.set_status(f"فشل قراءة الفواتير: {exc}")
            return

        tree = self.ui.tree
        clear_tree(tree)
        total_net = 0.0
        unpaid_n = 0
        for r in rows:
            deleted = bool(r.get("is_deleted"))
            status = str(r.get("payment_status", "unpaid"))
            net = float(r.get("mixer_net_cost", 0) or 0)
            if not deleted:
                total_net += net
                if status != "paid":
                    unpaid_n += 1
            tag = "deleted" if deleted else status
            values = (
                r.get("mix_number", ""),
                r.get("mix_date", ""),
                r.get("farm_name", ""),
                r.get("worker_name", ""),
                fmt(float(r.get("total_weight", 0) or 0), -1),
                fmt(r.get("billable_tons", 0.0), 1),
                fmt(r.get("total_cost", 0.0)),
                fmt(r.get("elec_fee", 0.0)),
                fmt(r.get("labor_fee", 0.0)),
                fmt(r.get("transport_fee", 0.0)),
                fmt(net),
                ("🗑️ " if deleted else "") + STATUS_AR.get(status, status),
                "✔" if r.get("net_cost_manually_edited") else "",
                r.get("notes", ""),
            )
            tree.insert("", "end", iid=str(r.get("mix_number", "")),
                        values=values, tags=(tag,))

        self.summary_var.set(f"{len(rows)} فاتورة | صافي نشط: {total_net:,.2f} ﷼ | "
                             f"غير مدفوعة: {unpaid_n}")
        self.app.set_status(f"الفواتير: {len(rows)} سجل")

    # ------------------------------------------------------------ إجراءات
    def new_record(self) -> None:
        mix_ctrl = self.app.tabs.get("mix")
        if mix_ctrl is not None and hasattr(mix_ctrl, "new_record"):
            self.app.open_tab("mix")
            mix_ctrl.new_record()
        else:
            self.app.open_tab("mix")

    def edit_in_mix_tab(self) -> None:
        number = self.ui.selected_id() if self.ui else ""
        if not number:
            self.app.toast("اختر فاتورة أولاً", "warning")
            return
        if not has_permission(self.app.user, "mix.edit"):
            self.app.toast("لا تملك صلاحية التعديل", "error")
            return
        mix_ctrl = self.app.tabs.get("mix")
        if mix_ctrl is not None and hasattr(mix_ctrl, "load_invoice"):
            mix_ctrl.load_invoice(str(number))
        else:
            self.app.toast("تبويب الخلطة غير جاهز بعد", "warning")

    def show_items_popup(self) -> None:
        """نافذة منبثقة بعناصر الفاتورة المحددة عند النقر المزدوج."""
        number = self.ui.selected_id() if self.ui else ""
        if not number:
            return
        try:
            inv = invoices_repo.get_invoice(str(number)) or {}
        except Exception as exc:  # noqa: BLE001
            self.app.toast(f"فشل فتح الفاتورة: {exc}", "error")
            return
        win = tk.Toplevel(self.ui.tree.winfo_toplevel())
        win.title(f"عناصر الخلطة {number}")
        win.geometry("560x360")
        cols = ("material", "qty_kg", "unit_price", "total")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, title, w in (("material", "المادة", 160), ("qty_kg", "كغ", 100),
                              ("unit_price", "سعر الكغ", 110), ("total", "الإجمالي", 120)):
            tree.heading(col, text=title)
            tree.column(col, width=w, anchor="center")
        tree.pack(fill="both", expand=True, padx=8, pady=8)
        total = 0.0
        for it in inv.get("items", []) or []:
            tree.insert("", "end", values=(
                it.get("material_name", ""),
                fmt(it.get("qty_kg", 0.0), -1),
                fmt(it.get("unit_price", 0.0), 4),
                fmt(it.get("total_price", 0.0)),
            ))
            total += float(it.get("total_price", 0) or 0)
        ttk.Label(win, text=f"إجمالي العلف: {total:,.2f} ﷼ — الصافي: "
                            f"{float(inv.get('mixer_net_cost', 0)):,.2f} ﷼",
                  font=settings.FONT_BOLD).pack(pady=(0, 8))

    def change_status_menu(self) -> None:
        """يُستدعى من القائمة؛ يغيّر حالة دفع الفاتورة المحددة."""
        number = self.ui.selected_id() if self.ui else ""
        if not number:
            self.app.toast("اختر فاتورة", "warning")
            return
        choice = messagebox.askyesno(
            "حالة الدفع",
            f"تعليم الفاتورة {number} كـ«مدفوعة»؟\n"
            "(للتسجيل الجزئي استخدم تبويب المدفوعات)")
        if not choice:
            return
        try:
            ok = invoices_repo.set_payment_status(
                str(number), "paid",
                created_by=str(self.app.user.get("username", "")))
        except Exception as exc:  # noqa: BLE001
            self.app.toast(f"فشل تغيير الحالة: {exc}", "error")
            return
        if ok:
            self.app.toast("تم تحديث حالة الدفع ✅", "success")
            self.refresh()

    def soft_delete(self) -> None:
        number = self.ui.selected_id() if self.ui else ""
        if not number:
            self.app.toast("اختر فاتورة للحذف", "warning")
            return
        if not messagebox.askyesno(
                "حذف ناعم",
                f"نقل الفاتورة {number} إلى سلة المحذوفات؟\n"
                "يمكنك استعادتها لاحقاً."):
            return
        try:
            ok = invoices_repo.soft_delete_invoice(
                str(number), created_by=str(self.app.user.get("username", "")))
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل الحذف الناعم")
            self.app.toast(f"فشل الحذف: {exc}", "error")
            return
        if ok:
            cache.invalidate_materials()
            self.app.toast(f"🗑️ نُقلت {number} للسلة", "success")
            self.refresh()

    def restore_selected(self) -> None:
        number = self.ui.selected_id() if self.ui else ""
        if not number:
            self.app.toast("اختر فاتورة من السلة للاستعادة", "warning")
            return
        try:
            ok = invoices_repo.restore_invoice(
                str(number), created_by=str(self.app.user.get("username", "")))
        except ValueError as exc:
            self.app.toast(f"تعذّرت الاستعادة: {exc}", "error")
            return
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل الاستعادة")
            self.app.toast(f"خطأ: {exc}", "error")
            return
        if ok:
            self.app.toast(f"♻️ تمت استعادة {number}", "success")
            self.refresh()

    def permanent_delete(self) -> None:
        number = self.ui.selected_id() if self.ui else ""
        if not number:
            return
        if not messagebox.askyesno(
                "حذف نهائي ⚠️",
                f"سيُحذف السجل {number} نهائياً مع بنوده ولا يمكن التراجع.\nمتأكد؟"):
            return
        if not messagebox.askyesno("تأكيد أخير", "الحذف النهائي نهائي فعلاً. متابعة؟"):
            return
        try:
            ok = invoices_repo.delete_invoice_permanent(str(number))
        except Exception as exc:  # noqa: BLE001
            self.app.toast(f"فشل الحذف النهائي: {exc}", "error")
            return
        if ok:
            self.app.toast("تم الحذف النهائي", "success")
            self.refresh()

    def print_current(self) -> None:
        number = self.ui.selected_id() if self.ui else ""
        if not number:
            self.app.toast("اختر فاتورة للطباعة", "warning")
            return
        try:
            from reports.invoice_html import generate_invoice_html

            html = generate_invoice_html(str(number))
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل توليد الفاتورة")
            self.app.toast(f"تعذّر تجهيز الطباعة: {exc}", "error")
            return
        self.app.show_html(f"فاتورة خلطة {number}", html)

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        if self.ui is not None:
            self.ui.export("invoices")

    def focus_search(self) -> None:
        if self.ui is not None:
            self.ui.search_entry.focus_set()


def build(parent: tk.Misc, app: Any) -> InvoicesController:
    """نقطة دخول التبويب."""
    return InvoicesController(parent, app)
