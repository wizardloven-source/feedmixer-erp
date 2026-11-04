"""
ui/tabs/recipes.py
------------------
تبويب «الوصفات الجاهزة»: إدارة recipes + recipe_items.

الأعمدة: # | الاسم | المزرعة | عدد البنود | إجمالي الكغ | تاريخ الإنشاء | ملاحظات
الوظائف:
    - ➕ وصفة جديدة / ✏️ تعديل / 📋 نسخ (copy_recipe) / 🗑️ حذف (recipes.edit/delete).
    - 🧪 تطبيق على شاشة الخلطة: ينقل mix tab ويفرج الوصفة (mix.apply_recipe).
    - 👁️ عرض بنود الوصفة في نافذة منبثقة.
    - بحث فوري + تصدير CSV/Excel.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> RecipesController
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data import recipes_repo
from ui.tabs._common import TabUI, build_tab, fmt

_log = get_logger("ui.tabs.recipes")


class RecipesController:
    """كنترولر تبويب الوصفات."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self._build(parent)
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="📝 الوصفات الجاهزة", font=settings.FONT_LARGE_BOLD)\
            .pack(side="right")

        can_edit = has_permission(self.app.user, "recipes.edit")
        buttons: list[tuple[str, str, Any]] = [("👁️ البنود", "flat", self.show_items)]
        if can_edit:
            buttons = [
                ("➕ وصفة جديدة", "primary", self.new_record),
                ("✏️ تعديل", "accent", self.edit_selected),
                ("📋 نسخ", "flat", self.copy_selected),
                ("🧪 تطبيق على خلطة", "success", self.apply_to_mix),
            ] + buttons
        if has_permission(self.app.user, "recipes.delete"):
            buttons.append(("🗑️ حذف", "danger", self.delete_selected))
        buttons.append(("🔄 تحديث", "flat", self.refresh))

        columns = ["id", "name", "farm", "items_count", "total_kg", "created_at", "notes"]
        headings = [
            ("id", "#", 45), ("name", "اسم الوصفة", 190), ("farm", "المزرعة", 140),
            ("items_count", "البنود", 60), ("total_kg", "إجمالي كغ", 110),
            ("created_at", "التاريخ", 110), ("notes", "ملاحظات", 220),
        ]
        self.ui: TabUI = build_tab(parent, self.app, columns=columns, headings=headings,
                                   buttons=buttons, weights=[0, 2, 1.4, 0.5, 1, 1, 2])
        self.ui.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        self.ui.tree.bind("<Delete>", lambda _e: self.delete_selected())

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        """يعيد تحميل الوصفات مع ملخص البنود لكل وصفة."""
        try:
            recipes = recipes_repo.list_recipes()
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحميل الوصفات")
            self.app.toast("فشل تحميل الوصفات", "error")
            return
        tree = self.ui.tree
        tree.delete(*tree.get_children())
        for r in recipes:
            rid = int(r["id"])
            items: list[dict] = []
            try:
                full = recipes_repo.get_recipe(rid) or {}
                items = list(full.get("items") or [])
            except Exception:  # noqa: BLE001
                _log.debug("فشل تحميل بنود الوصفة %s", rid)
            total_kg = sum(float(i.get("qty_kg") or 0) for i in items)
            created = str(r.get("created_at") or "")[:10]
            tree.insert("", "end", iid=str(rid), values=(
                rid, r.get("name", ""), r.get("farm_name", "") or "-",
                len(items), fmt(total_kg, decimals=0), created, r.get("notes", "") or "",
            ))

    # ------------------------------------------------------------ إجراءات
    def _selected_id(self) -> int:
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر وصفة من الجدول", "warning")
            return 0
        try:
            return int(sel[0])
        except (TypeError, ValueError):
            return 0

    def _recipe_or_none(self, rid: int) -> dict | None:
        try:
            return recipes_repo.get_recipe(rid)
        except Exception:  # noqa: BLE001
            _log.exception("فشل قراءة الوصفة %s", rid)
            return None

    def new_record(self) -> None:
        if not has_permission(self.app.user, "recipes.edit"):
            self.app.toast("لا تملك صلاحية تعديل الوصفات", "error")
            return
        from ui.dialogs.recipe_dialog import RecipeDialog

        dlg = RecipeDialog(self.app, self.app)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()

    def edit_selected(self) -> None:
        if not has_permission(self.app.user, "recipes.edit"):
            self.app.toast("لا تملك صلاحية تعديل الوصفات", "error")
            return
        rid = self._selected_id()
        recipe = self._recipe_or_none(rid) if rid else None
        if not recipe:
            return
        from ui.dialogs.recipe_dialog import RecipeDialog

        dlg = RecipeDialog(self.app, self.app, recipe=recipe)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()

    def copy_selected(self) -> None:
        """يفتح الحوار في وضع النسخ (اسم جديد + نفس البنود)."""
        if not has_permission(self.app.user, "recipes.edit"):
            self.app.toast("لا تملك صلاحية تعديل الوصفات", "error")
            return
        rid = self._selected_id()
        recipe = self._recipe_or_none(rid) if rid else None
        if not recipe:
            return
        from ui.dialogs.recipe_dialog import RecipeDialog

        dlg = RecipeDialog(self.app, self.app, recipe=recipe, copy_mode=True)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()

    def delete_selected(self) -> None:
        if not has_permission(self.app.user, "recipes.delete"):
            self.app.toast("لا تملك صلاحية حذف الوصفات", "error")
            return
        rid = self._selected_id()
        recipe = self._recipe_or_none(rid) if rid else None
        if not recipe:
            return
        name = str(recipe.get("name", ""))
        if not messagebox.askyesno("حذف وصفة",
                                  f"سيُحذف سجل الوصفة «{name}» مع بنودها.\nمتأكد؟",
                                  parent=self.app):
            return
        try:
            ok = recipes_repo.delete_recipe(rid)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل حذف الوصفة %s", rid)
            self.app.toast(str(exc), "error")
            return
        if ok:
            self.app.toast(f"تم حذف الوصفة «{name}»", "success")
            self.refresh()

    def show_items(self) -> None:
        """نافذة منبثقة تعرض بنود الوصفة المحددة (للقراءة فقط)."""
        rid = self._selected_id()
        recipe = self._recipe_or_none(rid) if rid else None
        if not recipe:
            return
        win = tk.Toplevel(self.app)
        win.title(f"بنود الوصفة: {recipe.get('name', '')}")
        win.geometry("480x320")
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("m", "q"), show="headings")
        tree.heading("m", text="المادة")
        tree.heading("q", text="الكمية (كغ)")
        tree.column("m", width=260)
        tree.column("q", width=140, anchor="center")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        total = 0.0
        for item in recipe.get("items") or []:
            qty = float(item.get("qty_kg") or 0)
            total += qty
            tree.insert("", "end", values=(item.get("material_name", ""), fmt(qty, decimals=0)))
        ttk.Label(win, text=f"الإجمالي: {fmt(total, decimals=0)} كغ",
                  font=settings.FONT_BOLD).pack(anchor="e", padx=10, pady=6)
        ttk.Button(win, text="إغلاق", command=win.destroy).pack(pady=(0, 8))

    def apply_to_mix(self) -> None:
        """ينقل المستخدم لتبويب الخلطة ويفرج بنود الوصفة المحددة."""
        if not has_permission(self.app.user, "mix.create"):
            self.app.toast("لا تملك صلاحية إنشاء الخلطات", "error")
            return
        rid = self._selected_id()
        recipe = self._recipe_or_none(rid) if rid else None
        if not recipe:
            return
        self.app.open_tab("mix")
        ctrl = self.app.tabs.get("mix")
        fn = getattr(ctrl, "apply_recipe", None)
        if callable(fn):
            try:
                fn(int(rid))
                self.app.toast(f"تم تطبيق الوصفة «{recipe.get('name', '')}» على شاشة الخلطة",
                               "success")
                return
            except Exception:  # noqa: BLE001
                _log.exception("فشل تطبيق الوصفة %s على الخلطة", rid)
        self.app.toast("تعذّر التطبيق التلقائي — افتح الخلطة واختر الوصفة يدوياً", "warning")

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        self.ui.export("recipes")

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass


def build(parent: tk.Misc, app: Any) -> RecipesController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return RecipesController(parent, app)
