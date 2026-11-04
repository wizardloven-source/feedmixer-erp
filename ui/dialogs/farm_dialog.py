"""
ui/dialogs/farm_dialog.py
-------------------------
حوار إضافة/تعديل مزرعة (اسم + أجرة نقل + هاتف + ملاحظات).

الاستخدام:
    dlg = FarmDialog(parent, app, farm=None)          # إضافة
    dlg = FarmDialog(parent, app, farm=farm_dict)     # تعديل
    parent.wait_window(dlg)
    if dlg.saved: ...
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.utils import safe_float, format_money
from data import farms_repo
from ui.dialogs.base_form import FormDialog

_log = get_logger("ui.dialogs.farm")


class FarmDialog(FormDialog):
    """نموذج مزرعة واحدة (إضافة أو تعديل)."""

    def __init__(self, parent: tk.Misc, app: Any, farm: dict | None = None) -> None:
        self.app = app
        self.farm = dict(farm) if farm else None
        title = "✏️ تعديل مزرعة" if self.farm else "➕ إضافة مزرعة"
        super().__init__(parent, title, width=430, on_save=self._save)
        self._build_fields()

    # ------------------------------------------------------------ الحقول
    def _build_fields(self) -> None:
        f = self.farm or {}
        self.add_label("بيانات المزرعة", bold=True)

        name = ttk.Entry(self.body, width=32, font=settings.FONT_BASE)
        name.insert(0, str(f.get("name", "")))
        self.add_field("name", name, "اسم المزرعة:")
        name.focus_set()

        fee = ttk.Entry(self.body, width=16, font=settings.FONT_BASE)
        fee.insert(0, "" if not f else format_money(safe_float(f.get("transport_fee"))))
        self.add_field("transport_fee", fee, "أجرة النقل الافتراضية:")
        ttk.Label(self.body, text="$ / طن", font=settings.FONT_SMALL).grid(
            row=self._row - 1, column=2, sticky="w", padx=4)

        phone = ttk.Entry(self.body, width=20, font=settings.FONT_BASE)
        phone.insert(0, str(f.get("phone") or ""))
        self.add_field("phone", phone, "الهاتف:")

        notes = ttk.Entry(self.body, width=40, font=settings.FONT_BASE)
        notes.insert(0, str(f.get("notes") or ""))
        self.add_field("notes", notes, "ملاحظات:")

        archived = f.get("is_archived") if f else 0
        if self.farm is not None:
            self.arch_var = tk.BooleanVar(master=self, value=bool(archived))
            chk = ttk.Checkbutton(self.body, text="مؤرشفة (غير نشطة)",
                                  variable=self.arch_var)
            self.add_field("is_archived", chk, "")
        else:
            self.arch_var = None

        self.body.columnconfigure(1, weight=1)

    # ------------------------------------------------------------ الحفظ
    def _collect(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": str(self.fields["name"].get()).strip(),
            "transport_fee": safe_float(self.fields["transport_fee"].get(), 0.0),
            "phone": str(self.fields["phone"].get()).strip(),
            "notes": str(self.fields["notes"].get()).strip(),
        }
        if len(data["name"]) < 2:
            raise ValueError("اسم المزرعة مطلوب (حرفان على الأقل)")
        if data["transport_fee"] < 0:
            raise ValueError("أجرة النقل لا يمكن أن تكون سالبة")
        return data

    def _save(self, data: dict[str, Any]) -> bool:
        try:
            if self.farm is not None:
                farms_repo.update_farm(
                    int(self.farm["id"]),
                    name=data["name"],
                    transport_fee=data["transport_fee"],
                    phone=data["phone"],
                    notes=data["notes"],
                )
                if self.arch_var is not None:
                    farms_repo.archive_farm(int(self.farm["id"]),
                                            archived=bool(self.arch_var.get()))
            else:
                farms_repo.add_farm(
                    name=data["name"],
                    transport_fee=data["transport_fee"],
                    phone=data["phone"],
                    notes=data["notes"],
                )
        except ValueError as exc:
            _log.info("فشل حفظ المزرعة: %s", exc)
            raise
        return True


__all__ = ["FarmDialog"]