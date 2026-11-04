"""
ui/tabs/farms.py
----------------
تبويب «المزارع»: قائمة المزارع + إضافة/تعديل/أرشفة/استعادة/حذف.

الأعمدة: # | الاسم | أجرة النقل/طن | هاتف | الحالة | ملاحظات
الوظائف:
    - ➕ إضافة / ✏️ تعديل عبر FarmDialog (farms.edit).
    - 📦 أرشفة / ♻️ إلغاء الأرشفة (الحقول المحفوظة في farms_repo.archive_farm).
    - 🗑️ حذف نهائي للمزارع المؤرشفة فقط التي بلا حركات (farms.delete).
    - بحث فوري + تصدير CSV/Excel + اختصارات عامة (Ctrl+N/Delete/F5).

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> FarmsController
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data import farms_repo
from ui.tabs._common import TabUI, build_tab, fmt

_log = get_logger("ui.tabs.farms")


class FarmsController:
    """كنترولر تبويب المزارع."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.show_archived_var = tk.BooleanVar(master=parent, value=True)
        self._build(parent)
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="🚜 إدارة المزارع", font=settings.FONT_LARGE_BOLD)\
            .pack(side="right")

        can_edit = has_permission(self.app.user, "farms.edit")
        buttons: list[tuple[str, str, Any]] = []
        if can_edit:
            buttons += [
                ("➕ إضافة", "primary", self.new_record),
                ("✏️ تعديل", "accent", self.edit_selected),
                ("📦 أرشفة", "flat", self.archive_selected),
                ("♻️ استعادة", "success", self.unarchive_selected),
            ]
        if has_permission(self.app.user, "farms.delete"):
            buttons += [("🗑️ حذف نهائي", "danger", self.delete_selected)]
        buttons += [("🔄 تحديث", "flat", self.refresh)]

        columns = ["id", "name", "transport_fee", "phone", "status", "notes"]
        headings = [
            ("id", "#", 45), ("name", "الاسم", 200),
            ("transport_fee", "أجرة النقل/طن", 110), ("phone", "الهاتف", 130),
            ("status", "الحالة", 90), ("notes", "ملاحظات", 260),
        ]
        self.ui: TabUI = build_tab(
            parent, self.app, columns=columns, headings=headings,
            buttons=buttons, weights=[0, 2, 1, 1.2, 0.7, 2.5],
        )
        self.ui.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.ui.tree.bind("<Delete>", lambda _e: self.delete_selected())
        try:
            self.ui.tree.tag_configure("archived", foreground="#9e9e9e")
            self.ui.tree.tag_configure("active", foreground=settings.COLORS["text"])
        except tk.TclError:
            pass

        opts = ttk.Frame(parent)
        opts.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(opts, text="إظهار المؤرشفة",
                        variable=self.show_archived_var,
                        command=self.refresh).pack(side="right")

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        """يعيد قراءة المزارع ويعبّئ الجدول."""
        try:
            rows = farms_repo.list_farms(
                include_archived=bool(self.show_archived_var.get()))
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحميل المزارع")
            self.app.toast("فشل تحميل المزارع", "error")
            return
        tree = self.ui.tree
        tree.delete(*tree.get_children())
        for r in rows:
            archived = bool(r.get("is_archived"))
            tree.insert("", "end", iid=str(r["id"]), tags=("archived" if archived else "active",),
                        values=(r["id"], r.get("name", ""), fmt(r.get("transport_fee")),
                                r.get("phone", ""), "📦 مؤرشفة" if archived else "✅ نشطة",
                                r.get("notes", "")))

    # ------------------------------------------------------------ إجراءات
    def _selected_farm_id(self) -> int:
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر مزرعة من الجدول", "warning")
            return 0
        try:
            return int(sel[0])
        except (TypeError, ValueError):
            return 0

    def _open_dialog(self, farm: dict | None) -> None:
        from ui.dialogs.farm_dialog import FarmDialog

        dlg = FarmDialog(self.app, self.app, farm=farm)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()
            self.app.refresh_all()

    def new_record(self) -> None:
        if not has_permission(self.app.user, "farms.edit"):
            self.app.toast("لا تملك صلاحية تعديل المزارع", "error")
            return
        self._open_dialog(None)

    def edit_selected(self) -> None:
        if not has_permission(self.app.user, "farms.edit"):
            self.app.toast("لا تملك صلاحية تعديل المزارع", "error")
            return
        farm_id = self._selected_farm_id()
        if not farm_id:
            return
        farm = farms_repo.get_farm(farm_id)
        if not farm:
            self.app.toast("المزرعة غير موجودة", "error")
            return
        self._open_dialog(farm)

    def _set_archive(self, archived: bool) -> None:
        if not has_permission(self.app.user, "farms.edit"):
            self.app.toast("لا تملك صلاحية تعديل المزارع", "error")
            return
        farm_id = self._selected_farm_id()
        if not farm_id:
            return
        try:
            ok = farms_repo.archive_farm(farm_id, archived)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل تغيير حالة الأرشفة")
            self.app.toast(f"خطأ: {exc}", "error")
            return
        if ok:
            self.app.toast("تم الأرشفة ✅" if archived else "تمت الاستعادة ♻️", "success")
            self.refresh()
            self.app.refresh_all()

    def archive_selected(self) -> None:
        self._set_archive(True)

    def unarchive_selected(self) -> None:
        self._set_archive(False)

    def delete_selected(self) -> None:
        """حذف نهائي — متاح للمؤرشفة بلا حركات فقط (يفحصه farms_repo)."""
        if not has_permission(self.app.user, "farms.delete"):
            self.app.toast("الحذف مقصور على المدير", "error")
            return
        farm_id = self._selected_farm_id()
        if not farm_id:
            return
        farm = farms_repo.get_farm(farm_id) or {}
        name = str(farm.get("name", ""))
        if not farm.get("is_archived"):
            self.app.toast("لا يمكن الحذف قبل الأرشفة أولاً 📦", "warning")
            return
        if not messagebox.askyesno("حذف مزرعة",
                                   f"سيُحذف سجل «{name}» نهائياً.\nهل أنت متأكد؟",
                                   parent=self.app):
            return
        try:
            ok = farms_repo.delete_farm(farm_id)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل حذف المزرعة")
            self.app.toast(str(exc), "error")
            return
        if ok:
            self.app.toast(f"تم حذف «{name}»", "success")
            self.refresh()
            self.app.refresh_all()

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        self.ui.export("farms")

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass


def build(parent: tk.Misc, app: Any) -> FarmsController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return FarmsController(parent, app)
