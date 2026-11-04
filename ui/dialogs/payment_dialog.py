"""
ui/dialogs/payment_dialog.py
----------------------------
حوار إضافة/تعديل دفعة (مزرعة + تاريخ + مبلغ + طريقة + مرجع + ملاحظات).

الطرق المعروضة بالعربية وتُخزَّن بالمفاتيح الإنجليزية:
    نقدي=cash | تحويل=transfer | شيك=cheque
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.utils import safe_float, today_str
from data import payments_repo
from ui.dialogs.base_form import FormDialog
from ui.widgets import make_date_entry

_log = get_logger("ui.dialogs.payment")

_METHOD_LABELS = {"cash": "💵 نقدي", "transfer": "🏦 تحويل", "cheque": "📄 شيك"}
_LABEL_TO_KEY = {v: k for k, v in _METHOD_LABELS.items()}


class PaymentDialog(FormDialog):
    """نموذج دفعة واحدة (إضافة أو تعديل)."""

    def __init__(self, parent: tk.Misc, app: Any, payment: dict | None = None,
                 farm_name: str = "") -> None:
        self.app = app
        self.payment = dict(payment) if payment else None
        title = "✏️ تعديل دفعة" if self.payment else "➕ تسجيل دفعة"
        super().__init__(parent, title, width=470, on_save=self._save)
        self._build_fields(farm_name)

    # ------------------------------------------------------------ الحقول
    def _build_fields(self, default_farm: str) -> None:
        p = self.payment or {}
        self.add_label("بيانات الدفعة", bold=True)

        from core.cache import farm_names

        farms = farm_names()
        current = str(p.get("farm_name") or default_farm or "")
        if current and current not in farms:
            farms = [current] + list(farms)
        farm_var = tk.StringVar(master=self, value=current)
        combo = ttk.Combobox(self.body, textvariable=farm_var, values=farms,
                             state="readonly", width=26, font=settings.FONT_BASE)
        self.add_field("farm", combo, "المزرعة:")
        self.farm_var = farm_var

        date_row = self.next_row()
        ttk.Label(self.body, text="التاريخ:", font=settings.FONT_BASE).grid(
            row=date_row, column=0, sticky="e", pady=3, padx=(8, 4))
        holder = ttk.Frame(self.body)
        holder.grid(row=date_row, column=1, columnspan=2, sticky="w", padx=4)
        self.date_entry = make_date_entry(holder, initial=str(p.get("payment_date") or today_str()))

        amount = ttk.Entry(self.body, width=16, font=settings.FONT_BASE)
        amount.insert(0, "" if not p else f"{safe_float(p.get('amount')):.2f}")
        self.add_field("amount", amount, "المبلغ:")
        ttk.Label(self.body, text="$", font=settings.FONT_SMALL).grid(
            row=self._row - 1, column=2, sticky="w", padx=4)
        amount.focus_set()

        method_key = str(p.get("method") or "cash")
        self.method_var = tk.StringVar(
            master=self, value=_METHOD_LABELS.get(method_key, "💵 نقدي"))
        m_combo = ttk.Combobox(self.body, textvariable=self.method_var,
                               values=list(_METHOD_LABELS.values()),
                               state="readonly", width=16, font=settings.FONT_BASE)
        self.add_field("method", m_combo, "طريقة الدفع:")

        ref = ttk.Entry(self.body, width=24, font=settings.FONT_BASE)
        ref.insert(0, str(p.get("reference") or ""))
        self.add_field("reference", ref, "المرجع (رقم إيصال/ cheque):")

        notes = ttk.Entry(self.body, width=36, font=settings.FONT_BASE)
        notes.insert(0, str(p.get("notes") or ""))
        self.add_field("notes", notes, "ملاحظات:")

        self.body.columnconfigure(1, weight=1)

    # ------------------------------------------------------------ الحفظ
    def _collect(self) -> dict[str, Any]:
        farm = str(self.farm_var.get()).strip()
        if not farm:
            raise ValueError("اختر المزرعة")
        try:
            amount = float(str(self.fields["amount"].get()).replace(",", "").strip())
        except ValueError:
            raise ValueError("أدخل مبلغاً رقمياً صحيحاً") from None
        if amount <= 0:
            raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
        return {
            "farm_name": farm,
            "payment_date": self.date_entry["get"](),
            "amount": amount,
            "method": _LABEL_TO_KEY.get(self.method_var.get(), "cash"),
            "reference": str(self.fields["reference"].get()).strip(),
            "notes": str(self.fields["notes"].get()).strip(),
        }

    def _save(self, data: dict[str, Any]) -> bool:
        user = str(getattr(self.app, "user", {}).get("username", "")) or None
        if self.payment is not None:
            payments_repo.update_payment(
                int(self.payment["id"]),
                farm_name=data["farm_name"],
                payment_date=data["payment_date"],
                amount=data["amount"],
                method=data["method"],
                reference=data["reference"],
                notes=data["notes"],
            )
        else:
            payments_repo.add_payment(
                farm_name=data["farm_name"],
                payment_date=data["payment_date"],
                amount=data["amount"],
                method=data["method"],
                reference=data["reference"],
                notes=data["notes"],
                created_by=user,
            )
        return True


__all__ = ["PaymentDialog"]