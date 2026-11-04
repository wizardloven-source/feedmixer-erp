"""
ui/tabs/purchases.py
--------------------
تبويب «التوريدات»: جدول التوريدات مع الفلاتر والرسوم، استيراد CSV،
طباعة إيصال استلام، وإضافة/تعديل عبر PurchaseDialog.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> PurchasesController
    controller.new_record()     (Ctrl+N)
    controller.refresh()        (F5)
    controller.export_current() (Ctrl+C)
    controller.focus_search()   (Ctrl+F)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from config import settings
from core import cache
from core.logger import get_logger
from core.permissions import has_permission
from data import purchases_repo
from ui.tabs._common import TabUI, build_tab, clear_tree, fmt

_log = get_logger("ui.tabs.purchases")


class PurchasesController:
    """قائمة التوريدات + إجراءات الإضافة/التعديل/الحذف/الاستيراد/الطباعة."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self._built = False
        self.ui: TabUI | None = None
        self.date_from_var = tk.StringVar(master=parent, value="")
        self.date_to_var = tk.StringVar(master=parent, value="")
        self.material_var = tk.StringVar(master=parent, value="all")
        self.summary_var = tk.StringVar(master=parent, value="")
        self._build(parent)
        self._built = True
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="🚚 التوريدات", font=settings.FONT_LARGE_BOLD).pack(side="right")
        ttk.Label(head, textvariable=self.summary_var, font=settings.FONT_BASE)\
            .pack(side="left")

        filters = ttk.Frame(parent)
        filters.pack(fill="x", pady=(0, 4))
        ttk.Label(filters, text="من:", width=4).pack(side="right")
        self.from_var = tk.StringVar(master=filters, value="")
        self.to_var = tk.StringVar(master=filters, value="")

        def _date_filter_row(var: tk.StringVar) -> ttk.Entry:
            entry = ttk.Entry(filters, textvariable=var, width=11, justify="center")
            entry.pack(side="right", padx=3)
            var.trace_add("write", lambda *_a: self._on_filter_date_change())
            return entry

        from_entry = _date_filter_row(self.from_var)
        ttk.Label(filters, text="إلى:", width=4).pack(side="right", padx=(10, 0))
        to_entry = _date_filter_row(self.to_var)
        self._filter_entries = (from_entry, to_entry)
        ttk.Label(filters, text="(YYYY-MM-DD أو اتركه فارغاً)",
                  font=settings.FONT_SMALL).pack(side="right", padx=4)
        ttk.Label(filters, text="المادة:", width=8).pack(side="right", padx=(12, 0))
        self.mat_combo = ttk.Combobox(filters, textvariable=self.material_var,
                                      width=16, state="readonly", values=["all"])
        self.mat_combo.pack(side="right", padx=3)
        self.mat_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Button(filters, text="مسح الفلاتر", command=self.clear_filters)\
            .pack(side="left", padx=6)

        can_write = has_permission(self.app.user, "purchases.create")
        buttons: list[tuple[str, str, Any]] = [
            ("🔄 تحديث", "flat", self.refresh),
            ("📤 تصدير", "flat", self.export_current),
            ("🖨️ إيصال استلام", "flat", self.print_receipt),
        ]
        if can_write:
            buttons += [
                ("➕ توريد جديد", "primary", self.new_record),
                ("✏️ تعديل", "flat", self.edit_selected),
                ("🗑️ حذف", "danger", self.delete_selected),
                ("📥 استيراد CSV", "flat", self.import_csv),
            ]
        buttons.append(("🧾 نموذج CSV", "flat", self.download_template))

        self.ui = build_tab(
            parent, self.app,
            columns=["date", "material", "qty_ton", "supplier", "price_ton",
                     "total_cost", "fees", "real_price", "details"],
            headings=[
                ("date", "التاريخ", 90),
                ("material", "المادة", 130),
                ("qty_ton", "الكمية (طن)", 90),
                ("supplier", "المورد", 120),
                ("price_ton", "سعر الطن", 90),
                ("total_cost", "الإجمالي", 100),
                ("fees", "الرسوم", 90),
                ("real_price", "حقيقي/طن", 95),
                ("details", "بيانات", 140),
            ],
            buttons=buttons,
        )
        self.ui.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.ui.tree.bind("<Control-n>", lambda _e: self.new_record())

    # ------------------------------------------------------------ فلاتر
    def _valid_date(self, text: str) -> str | None:
        """يعيد النص إذا كان تاريخاً صالحاً YYYY-MM-DD، وإلا None."""
        import datetime as dt

        text = (text or "").strip()
        if not text:
            return None
        try:
            dt.datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
        return text

    def _on_filter_date_change(self) -> None:
        """تحديث عند الكتابة في فلاتر التاريخ (debounce بسيط بـ after)."""
        if getattr(self, "_filter_job", None):
            try:
                self.ui.tree.winfo_toplevel().after_cancel(self._filter_job)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
        if self.ui is not None:
            self._filter_job = self.ui.tree.winfo_toplevel().after(
                350, self.refresh)

    def clear_filters(self) -> None:
        self.from_var.set("")
        self.to_var.set("")
        self.material_var.set("all")
        self.refresh()

    # ------------------------------------------------------------ تحديث
    def refresh(self) -> None:
        if not self._built or self.ui is None:
            return
        try:
            names = ["all"] + cache.material_names(force=True)
            self.mat_combo.configure(values=names)
            rows = purchases_repo.list_purchases(
                search=None,
                material=None if self.material_var.get() in ("", "all")
                else self.material_var.get(),
                date_from=self._valid_date(self.from_var.get()),
                date_to=self._valid_date(self.to_var.get()),
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل قراءة التوريدات")
            self.app.set_status(f"فشل قراءة التوريدات: {exc}")
            return

        table = [(
            r.get("purchase_date", ""),
            r.get("material_name", ""),
            fmt(r.get("qty_ton", 0.0)),
            r.get("supplier", ""),
            fmt(r.get("price_per_ton", 0.0)),
            fmt(r.get("total_cost", 0.0)),
            fmt(r.get("fees_total", 0.0)),
            fmt(r.get("real_price_per_ton", 0.0)),
            r.get("details", ""),
        ) for r in rows]
        # نخزّن المعرّف الحقيقي في iid الصف (يقرأه selected_id عبر العمود الخفي)
        clear_tree(self.ui.tree)
        for idx, row in enumerate(table):
            pid = rows[idx].get("id", "")
            self.ui.tree.insert("", "end", iid=str(pid), values=row)

        total_qty = sum(float(r.get("qty_ton", 0) or 0) for r in rows)
        total_cost = sum(float(r.get("total_cost", 0) or 0) for r in rows)
        self.summary_var.set(f"{len(rows)} توريد | {total_qty:,.2f} طن | "
                             f"{total_cost:,.2f} ﷼")
        self.app.set_status(f"التوريدات: {len(rows)} سجل")

    # ------------------------------------------------------------ إجراءات
    def new_record(self) -> None:
        if not has_permission(self.app.user, "purchases.create"):
            self.app.toast("لا تملك صلاحية إضافة توريد", "error")
            return
        from ui.dialogs.purchase_dialog import PurchaseDialog

        dlg = PurchaseDialog(self.ui.tree.winfo_toplevel(), self.app, purchase=None)
        self.ui.tree.winfo_toplevel().wait_window(dlg)
        if dlg.saved:
            self.app.toast("✅ تم حفظ التوريد", "success")
            self.refresh()

    def edit_selected(self) -> None:
        if not has_permission(self.app.user, "purchases.edit"):
            self.app.toast("لا تملك صلاحية تعديل التوريدات", "error")
            return
        pid = self.ui.selected_id() if self.ui else ""
        if not str(pid).isdigit():
            self.app.toast("اختر صفاً من الجدول", "warning")
            return
        purchase = purchases_repo.get_purchase(int(pid))
        if not purchase:
            self.app.toast("السجل غير موجود", "error")
            return
        from ui.dialogs.purchase_dialog import PurchaseDialog

        dlg = PurchaseDialog(self.ui.tree.winfo_toplevel(), self.app,
                             purchase=purchase)
        self.ui.tree.winfo_toplevel().wait_window(dlg)
        if dlg.saved:
            self.app.toast("✅ تم تحديث التوريد", "success")
            self.refresh()

    def delete_selected(self) -> None:
        if not has_permission(self.app.user, "purchases.delete"):
            self.app.toast("لا تملك صلاحية الحذف", "error")
            return
        pid = self.ui.selected_id() if self.ui else ""
        if not str(pid).isdigit():
            self.app.toast("اختر صفاً للحذف", "warning")
            return
        row = self.ui.selected_row()
        if not messagebox.askyesno(
                "تأكيد الحذف",
                f"حذف توريد «{row.get('material', '')}» بتاريخ {row.get('date', '')}؟\n"
                "سيؤثر ذلك على أرصدة المخزون."):
            return
        try:
            ok = purchases_repo.delete_purchase(int(pid))
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل حذف التوريد")
            self.app.toast(f"فشل الحذف: {exc}", "error")
            return
        if ok:
            cache.invalidate_materials()
            self.app.toast("🗑️ تم حذف التوريد", "success")
            self.refresh()

    def import_csv(self) -> None:
        if not has_permission(self.app.user, "purchases.import"):
            self.app.toast("لا تملك صلاحية الاستيراد", "error")
            return
        path = filedialog.askopenfilename(
            title="اختر ملف CSV",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        user = str(self.app.user.get("username", ""))
        try:
            result = purchases_repo.import_csv(path, created_by=user)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل استيراد CSV")
            self.app.toast(f"فشل الاستيراد: {exc}", "error")
            return
        msg = (f"تم الاستيراد ✅\nالناجحة: {result.get('imported', 0)}\n"
               f"المتخطاة: {result.get('skipped', 0)}")
        errors = result.get("errors") or []
        if errors:
            msg += "\n\nأخطاء:\n" + "\n".join(str(e) for e in errors[:10])
        messagebox.showinfo("استيراد CSV", msg)
        self.refresh()

    def download_template(self) -> None:
        """يحفظ ملف قالب CSV بأعمدة التوريدات الصحيحة."""
        try:
            content = purchases_repo.export_csv_template()
            path = filedialog.asksaveasfilename(
                title="حفظ قالب CSV", defaultextension=".csv",
                initialfile="purchases_template.csv",
                filetypes=[("CSV", "*.csv")])
            if not path:
                return
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(content)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل إنشاء القالب")
            self.app.toast(f"فشل إنشاء القالب: {exc}", "error")
            return
        self.app.toast(f"تم حفظ القالب: {path}", "success")

    def print_receipt(self) -> None:
        pid = self.ui.selected_id() if self.ui else ""
        if not str(pid).isdigit():
            self.app.toast("اختر توريداً للطباعة", "warning")
            return
        try:
            from reports.receipt_html import generate_receipt_html

            html = generate_receipt_html(int(pid))
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل توليد الإيصال")
            self.app.toast(f"تعذّر الطباعة: {exc}", "error")
            return
        self.app.show_html(f"إيصال استلام #{pid}", html)

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        if self.ui is not None:
            self.ui.export("purchases")

    def focus_search(self) -> None:
        if self.ui is not None:
            self.ui.search_entry.focus_set()


def build(parent: tk.Misc, app: Any) -> PurchasesController:
    """نقطة دخول التبويب."""
    return PurchasesController(parent, app)
