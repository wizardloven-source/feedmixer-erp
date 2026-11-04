"""
ui/tabs/materials_base.py
-------------------------
أساس مشترك لتبويبي «المواد/الأسعار» اللذين يعرضان نفس جدول materials
بنفس الأزرار والإجراءات، مع اختلاف العرض فقط:

    مخزون  (inventory.py): التركيز على الكميات (مورد/مستهلك/متبقٍ وتنبيهات)
    أسعار  (prices.py)   : التركيز على التسعير (سعر الطن + عتالة + هدر + سعر الكغ الفعلي)

يوفر MaterialsPanel:
    - بناء الجدول حسب headings الممررة + دالة تنسيق صفوف row_formatter.
    - أزرار الإضافة/التعديل/الحذف محكومة بالصلاحية (materials.edit/delete).
    - فتح MaterialDialog ثم refresh + refresh_all للتحديث المتقاطع.

لا تُستدعى هذه الوحدة مباشرة من main_window (ليست تبويباً بحد ذاتها).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Sequence

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data import materials_repo
from ui.tabs._common import TabUI, build_tab

_log = get_logger("ui.tabs.materials_base")

RowFormatter = Callable[[dict, Any], Sequence[Any]]


class MaterialsPanel:
    """لوحة مواد قابلة للتخصيص (يستعملها تبويبا المخزون والأسعار)."""

    def __init__(self, parent: tk.Misc, app: Any, *, title: str,
                 columns: Sequence[str], headings: Sequence[tuple[str, str, int]],
                 weights: Sequence[float], row_formatter: RowFormatter,
                 export_prefix: str, extra_buttons: Sequence[tuple[str, str, Any]] = ()) -> None:
        self.app = app
        self.row_formatter = row_formatter
        self.export_prefix = export_prefix
        self._build(parent, title, list(columns), list(headings),
                    list(weights), list(extra_buttons))
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc, title: str, columns: list[str],
               headings: list[tuple[str, str, int]], weights: list[float],
               extra_buttons: list[tuple[str, str, Any]]) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text=title, font=settings.FONT_LARGE_BOLD).pack(side="right")

        buttons: list[tuple[str, str, Any]] = list(extra_buttons)
        if has_permission(self.app.user, "materials.edit"):
            buttons = [("➕ مادة جديدة", "primary", self.new_record),
                       ("✏️ تعديل", "accent", self.edit_selected)] + buttons
        if has_permission(self.app.user, "materials.delete"):
            buttons.append(("🗑️ حذف", "danger", self.delete_selected))
        buttons.append(("🔄 تحديث", "flat", self.refresh))

        self.ui: TabUI = build_tab(parent, self.app, columns=columns,
                                   headings=headings, buttons=buttons,
                                   weights=weights)
        self.ui.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.ui.tree.bind("<Delete>", lambda _e: self.delete_selected())
        try:
            self.ui.tree.tag_configure("low", foreground="#c62828")
            self.ui.tree.tag_configure("ok", foreground=settings.COLORS["text"])
        except tk.TclError:
            pass

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        """يعيد تحميل المواد وتعبئة الصفوف عبر row_formatter."""
        try:
            materials = materials_repo.list_materials()
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحميل المواد")
            self.app.toast("فشل تحميل المواد", "error")
            return
        tree = self.ui.tree
        tree.delete(*tree.get_children())
        for m in materials:
            try:
                row, tag = self.row_formatter(m, self.app)
            except Exception:  # noqa: BLE001
                _log.exception("تنسيق صف مادة %s", m.get("name"))
                continue
            tree.insert("", "end", iid=str(m["id"]),
                        tags=(tag or "ok",), values=tuple(row))

    # ------------------------------------------------------------ إجراءات
    def _selected_id(self) -> int:
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر مادة من الجدول", "warning")
            return 0
        try:
            return int(sel[0])
        except (TypeError, ValueError):
            return 0

    def _open_dialog(self, material: dict | None) -> None:
        from ui.dialogs.material_dialog import MaterialDialog

        dlg = MaterialDialog(self.app, self.app, material=material)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()
            self.app.refresh_all()

    def new_record(self) -> None:
        if not has_permission(self.app.user, "materials.edit"):
            self.app.toast("لا تملك صلاحية إضافة المواد", "error")
            return
        self._open_dialog(None)

    def edit_selected(self) -> None:
        if not has_permission(self.app.user, "materials.edit"):
            self.app.toast("لا تملك صلاحية تعديل المواد", "error")
            return
        mid = self._selected_id()
        if not mid:
            return
        material = materials_repo.get_material(mid)
        if not material:
            self.app.toast("المادة غير موجودة", "error")
            return
        self._open_dialog(material)

    def delete_selected(self) -> None:
        """حذف مادة — يرفضها materials_repo إذا كانت مستخدمة."""
        if not has_permission(self.app.user, "materials.delete"):
            self.app.toast("الحذف مقصور على المدير", "error")
            return
        mid = self._selected_id()
        if not mid:
            return
        material = materials_repo.get_material(mid) or {}
        name = str(material.get("name", ""))
        if not messagebox_ok(self.app, "حذف مادة",
                             f"سيُحذف سجل المادة «{name}» نهائياً.\nمتأكد؟"):
            return
        try:
            ok = materials_repo.delete_material(mid)
        except Exception as exc:  # noqa: BLE001
            _log.info("رفض حذف المادة %s: %s", name, exc)
            self.app.toast(str(exc), "error")
            return
        if ok:
            self.app.toast(f"تم حذف «{name}»", "success")
            self.refresh()
            self.app.refresh_all()

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        self.ui.export(self.export_prefix)

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass


def messagebox_ok(app: Any, title: str, message: str) -> bool:
    """صندوق تأكيد آمن (لا يُسقط التطبيق عند فشل الواجهة)."""
    from tkinter import messagebox

    try:
        return bool(messagebox.askyesno(title, message, parent=app))
    except tk.TclError:
        return False


__all__ = ["MaterialsPanel", "messagebox_ok"]
