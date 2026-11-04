"""
ui/dialogs/recipe_dialog.py
---------------------------
حوار الوصفات الجاهزة: اسم + مزرعة مقترحة + ملاحظات + جدول بنود
(مادة + كمية كغ) مع إضافة/حذف سطر ومعاينة الوزن الإجمالي.

يُستخدم للإضافة والتعديل والنسخ (نسخ = فتح بحالة إنشاء مع بيانات منسوخة).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.cache import material_names
from core.logger import get_logger
from core.utils import safe_float
from data import recipes_repo
from ui.dialogs.base_form import FormDialog

_log = get_logger("ui.dialogs.recipe")


class RecipeDialog(FormDialog):
    """نموذج وصفة كاملة مع بنودها."""

    def __init__(self, parent: tk.Misc, app: Any, recipe: dict | None = None,
                 *, copy_mode: bool = False) -> None:
        self.app = app
        self.recipe = dict(recipe) if recipe else None
        self.copy_mode = copy_mode
        if copy_mode:
            title = "📋 نسخ وصفة"
        elif self.recipe:
            title = "✏️ تعديل وصفة"
        else:
            title = "➕ وصفة جديدة"
        super().__init__(parent, title, width=560, on_save=self._save)
        self._build_fields()
        self._load_items()
        self._update_total()

    # ------------------------------------------------------------ الحقول
    def _build_fields(self) -> None:
        r = self.recipe or {}
        default_name = ""
        if self.copy_mode and r:
            default_name = f"{r.get('name', '')} - نسخة"
        self.add_label("بيانات الوصفة", bold=True)

        name = ttk.Entry(self.body, width=32, font=settings.FONT_BASE)
        name.insert(0, default_name or str(r.get("name", "")))
        self.add_field("name", name, "اسم الوصفة:")
        name.focus_set()

        from core.cache import farm_names

        farms = [""] + list(farm_names())
        farm_var = tk.StringVar(master=self, value=str(r.get("farm_name") or ""))
        combo = ttk.Combobox(self.body, textvariable=farm_var, values=farms,
                             state="readonly", width=28, font=settings.FONT_BASE)
        self.add_field("farm", combo, "المزرعة المقترحة (اختياري):")
        self.farm_var = farm_var

        notes = ttk.Entry(self.body, width=44, font=settings.FONT_BASE)
        notes.insert(0, str(r.get("notes") or ""))
        self.add_field("notes", notes, "ملاحظات:")

        # ---------- جدول البنود ----------
        self.add_label("بنود الوصفة (كمية الكيلو لكل مادة)", bold=True)
        table_wrap = ttk.Frame(self.body)
        table_wrap.grid(row=self.next_row(), column=0, columnspan=3,
                        sticky="we", pady=2)
        self.tree = ttk.Treeview(
            table_wrap, columns=("material", "qty"), show="headings", height=8)
        self.tree.heading("material", text="المادة", anchor="center")
        self.tree.heading("qty", text="الكمية (كغ)", anchor="center")
        self.tree.column("material", width=280, anchor="center")
        self.tree.column("qty", width=120, anchor="center")
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        edit_row = ttk.Frame(self.body)
        edit_row.grid(row=self.next_row(), column=0, columnspan=3,
                      sticky="we", pady=4)
        self.item_material_var = tk.StringVar(master=self)
        combo_m = ttk.Combobox(edit_row, textvariable=self.item_material_var,
                               values=list(material_names()), width=22,
                               font=settings.FONT_BASE)
        combo_m.pack(side="right", padx=4)
        self.item_qty_var = tk.StringVar(master=self)
        qty_e = ttk.Entry(edit_row, textvariable=self.item_qty_var, width=12,
                          justify="center")
        qty_e.pack(side="right", padx=4)
        ttk.Button(edit_row, text="➕ إضافة بند", command=self._add_item)\
            .pack(side="right", padx=4)
        ttk.Button(edit_row, text="➖ حذف البند المحدد", command=self._remove_item)\
            .pack(side="right", padx=4)
        qty_e.bind("<Return>", lambda _e: self._add_item())

        self.total_var = tk.StringVar(master=self, value="")
        ttk.Label(self.body, textvariable=self.total_var, font=settings.FONT_BOLD,
                  foreground=self.app_colors["primary"]).grid(
            row=self.next_row(), column=0, columnspan=3, sticky="e", pady=(6, 0))

        self.body.columnconfigure(1, weight=1)

    # ------------------------------------------------------------ البنود
    def _load_items(self) -> None:
        for item in (self.recipe or {}).get("items", []) or []:
            self.tree.insert("", "end", values=(item.get("material_name", ""),
                                                item.get("qty_kg", 0)))

    def _add_item(self) -> None:
        material = str(self.item_material_var.get()).strip()
        qty = safe_float(self.item_qty_var.get(), 0.0)
        if not material:
            self.set_message("اختر المادة أولاً")
            return
        if qty <= 0:
            self.set_message("أدخل كمية كغ أكبر من صفر")
            return
        existing = {str(self.tree.set(iid, "material")): iid
                    for iid in self.tree.get_children()}
        if material in existing:  # دمج الكميات بدل تكرار السطر
            iid = existing[material]
            old = safe_float(self.tree.set(iid, "qty"))
            self.tree.set(iid, "qty", round(old + qty, 3))
        else:
            self.tree.insert("", "end", values=(material, round(qty, 3)))
        self.item_qty_var.set("")
        self.set_message("")
        self._update_total()

    def _remove_item(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.set_message("حدد سطراً لحذفه")
            return
        self.tree.delete(*sel)
        self._update_total()

    def _collect_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for iid in self.tree.get_children():
            material = str(self.tree.set(iid, "material")).strip()
            qty = safe_float(self.tree.set(iid, "qty"))
            if material and qty > 0:
                items.append({"material_name": material, "qty_kg": qty})
        return items

    def _update_total(self) -> None:
        total = sum(item["qty_kg"] for item in self._collect_items())
        self.total_var.set(f"الإجمالي: {total:,.0f} كغ = {total / 1000:,.3f} طن")

    # ------------------------------------------------------------ الحفظ
    def _collect(self) -> dict[str, Any]:
        name = str(self.fields["name"].get()).strip()
        if len(name) < 2:
            raise ValueError("اسم الوصفة مطلوب (حرفان على الأقل)")
        items = self._collect_items()
        if not items:
            raise ValueError("أضف بنداً واحداً على الأقل للوصفة")
        return {
            "name": name,
            "farm_name": str(self.farm_var.get()).strip(),
            "notes": str(self.fields["notes"].get()).strip(),
            "items": items,
        }

    def _save(self, data: dict[str, Any]) -> bool:
        if self.recipe is not None and not self.copy_mode:
            recipes_repo.update_recipe(
                int(self.recipe["id"]),
                name=data["name"],
                farm_name=data["farm_name"],
                notes=data["notes"],
                items=data["items"],
            )
        else:
            new_id = recipes_repo.add_recipe(
                name=data["name"],
                farm_name=data["farm_name"],
                notes=data["notes"],
                items=data["items"],
            )
            self.saved_recipe_id = new_id
        return True


__all__ = ["RecipeDialog"]
