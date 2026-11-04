"""
ui/dialogs/material_dialog.py
-----------------------------
حوار إضافة/تعديل مادة (اسم + سعر أساسي + عتالة + هدر + نوع الوحدة).

يعرض أيضاً معاينة حية لـ «سعر الكيلو» المحسوب وفق القاعدة:
    ton   : (السعر + العتالة + الهدر) / 1000
    kg    : السعر + العتالة + الهدر
    fixed : السعر
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.utils import safe_float, format_money
from data import materials_repo
from ui.dialogs.base_form import FormDialog

_log = get_logger("ui.dialogs.material")

_UNIT_LABELS = {"ton": "طن (ton)", "kg": "كيلو (kg)", "fixed": "مقطوعية (fixed)"}


class MaterialDialog(FormDialog):
    """نموذج مادة واحدة (إضافة أو تعديل)."""

    def __init__(self, parent: tk.Misc, app: Any, material: dict | None = None) -> None:
        self.app = app
        self.material = dict(material) if material else None
        title = "✏️ تعديل مادة" if self.material else "➕ إضافة مادة"
        super().__init__(parent, title, width=460, on_save=self._save)
        self._build_fields()
        self._update_preview()

    # ------------------------------------------------------------ الحقول
    def _build_fields(self) -> None:
        m = self.material or {}
        self.add_label("بيانات المادة", bold=True)

        name = ttk.Entry(self.body, width=30, font=settings.FONT_BASE)
        name.insert(0, str(m.get("name", "")))
        self.add_field("name", name, "اسم المادة:")
        name.focus_set()

        row = self.next_row()
        ttk.Label(self.body, text="السعر الأساسي:", font=settings.FONT_BASE).grid(
            row=row, column=0, sticky="e", pady=3, padx=(8, 4))
        fees_frame = ttk.Frame(self.body)
        fees_frame.grid(row=row, column=1, columnspan=2, sticky="we", pady=3, padx=4)

        self.price_vars: dict[str, tk.DoubleVar] = {}
        for key, label in (("base_price", "أساسي"), ("handling_fee", "عتالة"),
                           ("loss_fee", "هدر")):
            ttk.Label(fees_frame, text=label, font=settings.FONT_SMALL).pack(side="right")
            var = tk.DoubleVar(master=self, value=safe_float(m.get(key), 0.0))
            entry = ttk.Entry(fees_frame, textvariable=var, width=9, justify="center")
            entry.pack(side="right", padx=3)
            var.trace_add("write", lambda *_a: self._update_preview())
            self.price_vars[key] = var

        unit_var = tk.StringVar(master=self, value=str(m.get("unit_type") or "ton"))
        combo = ttk.Combobox(self.body, textvariable=unit_var, state="readonly",
                             values=[_UNIT_LABELS[u] for u in settings.UNIT_TYPES],
                             width=22, font=settings.FONT_BASE)
        self.add_field("unit_combo", combo, "نوع الوحدة:")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())
        self.unit_var = unit_var

        self.preview_var = tk.StringVar(master=self, value="")
        prev = ttk.Label(self.body, textvariable=self.preview_var,
                         font=settings.FONT_BOLD, foreground=self.app_colors["primary"])
        prev.grid(row=self.next_row(), column=0, columnspan=3, sticky="e", pady=(8, 0))

        self.body.columnconfigure(1, weight=1)

    # ------------------------------------------------------------ أدوات
    def _unit_key(self) -> str:
        text = self.unit_var.get()
        for key, label in _UNIT_LABELS.items():
            if text == label:
                return key
        return "ton"

    def _kg_price(self) -> float:
        base = self.price_vars["base_price"].get()
        handling = self.price_vars["handling_fee"].get()
        loss = self.price_vars["loss_fee"].get()
        unit = self._unit_key()
        if unit == "ton":
            return (base + handling + loss) / settings.KG_PER_TON
        if unit == "kg":
            return base + handling + loss
        return base

    def _update_preview(self) -> None:
        try:
            kg = self._kg_price()
            self.preview_var.set(
                f"سعر الكيلو ≈ ${kg:,.4f}   |   سعر الطن المكافئ ≈ ${kg * 1000:,.2f}")
        except tk.TclError:
            pass

    # ------------------------------------------------------------ الحفظ
    def _collect(self) -> dict[str, Any]:
        name = str(self.fields["name"].get()).strip()
        if len(name) < 1:
            raise ValueError("اسم المادة مطلوب")
        data = {
            "name": name,
            "base_price": self.price_vars["base_price"].get(),
            "handling_fee": self.price_vars["handling_fee"].get(),
            "loss_fee": self.price_vars["loss_fee"].get(),
            "unit_type": self._unit_key(),
        }
        for key in ("base_price", "handling_fee", "loss_fee"):
            if data[key] < 0:
                raise ValueError(f"قيمة «{key}» لا يمكن أن تكون سالبة")
        return data

    def _save(self, data: dict[str, Any]) -> bool:
        if self.material is not None:
            materials_repo.update_material(
                int(self.material["id"]),
                name=data["name"],
                base_price=data["base_price"],
                handling_fee=data["handling_fee"],
                loss_fee=data["loss_fee"],
                unit_type=data["unit_type"],
            )
        else:
            materials_repo.add_material(
                name=data["name"],
                base_price=data["base_price"],
                handling_fee=data["handling_fee"],
                loss_fee=data["loss_fee"],
                unit_type=data["unit_type"],
            )
        return True


__all__ = ["MaterialDialog"]