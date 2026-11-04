"""
ui/dialogs/purchase_dialog.py
-----------------------------
حوار إضافة/تعديل توريد مع الحساب التلقائي الحي:

    الإجمالي      = الكمية(طن) × سعر الطن
    رسوم         = تنزيل + عتالة + نقل + أخرى
    السعر الحقيقي = (الإجمالي + الرسوم) ÷ الكمية

يُحدّث شريط المعاينة في كل ضغطة مفتاح، ويحفظ عبر purchases_repo.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.cache import material_names
from core.logger import get_logger
from core.utils import safe_float, today_str
from data import purchases_repo
from ui.dialogs.base_form import FormDialog
from ui.widgets import make_date_entry

_log = get_logger("ui.dialogs.purchase")


class PurchaseDialog(FormDialog):
    """نموذج توريد واحد (إضافة/تعديل) مع معاينة حية للحساب."""

    def __init__(self, parent: tk.Misc, app: Any, purchase: dict | None = None) -> None:
        self.app = app
        self.purchase = dict(purchase) if purchase else None
        title = "✏️ تعديل توريد" if self.purchase else "➕ توريد جديد"
        super().__init__(parent, title, width=520, on_save=self._save)
        self._build_fields()
        self._update_preview()

    # ------------------------------------------------------------ الحقول
    def _build_fields(self) -> None:
        p = self.purchase or {}
        self.add_label("بيانات التوريد", bold=True)

        row = self.next_row()
        ttk.Label(self.body, text="التاريخ:", font=settings.FONT_BASE).grid(
            row=row, column=0, sticky="e", pady=3, padx=(8, 4))
        holder = ttk.Frame(self.body)
        holder.grid(row=row, column=1, columnspan=2, sticky="w", padx=4)
        self.date_entry = make_date_entry(holder, initial=str(p.get("purchase_date") or today_str()))

        mat_var = tk.StringVar(master=self, value=str(p.get("material_name") or ""))
        names = list(material_names())
        if mat_var.get() and mat_var.get() not in names:
            names.insert(0, mat_var.get())
        combo = ttk.Combobox(self.body, textvariable=mat_var, values=names,
                             width=24, font=settings.FONT_BASE)
        self.add_field("material", combo, "المادة:")
        self.mat_var = mat_var

        supplier = ttk.Entry(self.body, width=24, font=settings.FONT_BASE)
        supplier.insert(0, str(p.get("supplier") or ""))
        self.add_field("supplier", supplier, "المورد:")

        details = ttk.Entry(self.body, width=36, font=settings.FONT_BASE)
        details.insert(0, str(p.get("details") or ""))
        self.add_field("details", details, "تفاصيل / رقم بوليص:")

        # ---------- أرقام ----------
        self.num_vars: dict[str, tk.DoubleVar] = {}
        specs = [
            ("qty_ton", "الكمية (طن)", float(safe_float(p.get("qty_ton"), 0.0))),
            ("price_per_ton", "سعر الطن ($)", float(safe_float(p.get("price_per_ton"), 0.0))),
            ("unloading_fee", "رسوم تنزيل ($)", float(safe_float(p.get("unloading_fee"), 0.0))),
            ("handling_fee", "عتالة ($)", float(safe_float(p.get("handling_fee"), 0.0))),
            ("transport_fee", "نقل ($)", float(safe_float(p.get("transport_fee"), 0.0))),
            ("other_fees", "أخرى ($)", float(safe_float(p.get("other_fees"), 0.0))),
        ]
        grid_frame = ttk.Frame(self.body)
        grid_frame.grid(row=self.next_row(), column=0, columnspan=3,
                        sticky="we", pady=4)
        for idx, (key, label, init) in enumerate(specs):
            cell = ttk.Frame(grid_frame)
            cell.grid(row=idx // 3, column=idx % 3, padx=6, pady=3, sticky="we")
            ttk.Label(cell, text=label, font=settings.FONT_SMALL).pack(anchor="e")
            var = tk.DoubleVar(master=self, value=init)
            entry = ttk.Entry(cell, textvariable=var, width=11, justify="center")
            entry.pack(anchor="e")
            var.trace_add("write", lambda *_a: self._update_preview())
            self.num_vars[key] = var
        grid_frame.columnconfigure((0, 1, 2), weight=1)

        # ---------- معاينة ----------
        self.preview_var = tk.StringVar(master=self, value="")
        prev = ttk.Label(self.body, textvariable=self.preview_var,
                         font=settings.FONT_BOLD,
                         foreground=self.app_colors["primary"], justify="right")
        prev.grid(row=self.next_row(), column=0, columnspan=3, sticky="we", pady=(10, 0))

        self.body.columnconfigure(1, weight=1)

    # ------------------------------------------------------------ المعاينة
    def _totals(self) -> dict[str, float]:
        qty = self.num_vars["qty_ton"].get()
        price = self.num_vars["price_per_ton"].get()
        fees = sum(self.num_vars[k].get() for k in
                   ("unloading_fee", "handling_fee", "transport_fee", "other_fees"))
        total_cost = max(0.0, qty) * max(0.0, price)
        real = (total_cost + fees) / qty if qty > 0 else 0.0
        return {"qty": qty, "total_cost": total_cost, "fees": fees,
                "grand": total_cost + fees, "real": real}

    def _update_preview(self) -> None:
        try:
            t = self._totals()
            self.preview_var.set(
                f"تكلفة: ${t['total_cost']:,.2f}   رسوم: ${t['fees']:,.2f}   "
                f"الإجمالي: ${t['grand']:,.2f}   "
                f"الحقيقي/طن: ${t['real']:,.2f}")
        except tk.TclError:
            pass

    # ------------------------------------------------------------ الحفظ
    def _collect(self) -> dict[str, Any]:
        material = str(self.mat_var.get()).strip()
        if not material:
            raise ValueError("اختر المادة أو اكتب اسمها")
        if self.num_vars["qty_ton"].get() <= 0:
            raise ValueError("الكمية بالطن يجب أن تكون أكبر من صفر")
        if self.num_vars["price_per_ton"].get() < 0:
            raise ValueError("سعر الطن لا يمكن أن يكون سالباً")
        for key in ("unloading_fee", "handling_fee", "transport_fee", "other_fees"):
            if self.num_vars[key].get() < 0:
                raise ValueError(f"رسوم «{key}» لا يمكن أن تكون سالبة")
        return {
            "purchase_date": self.date_entry["get"](),
            "material_name": material,
            "supplier": str(self.fields["supplier"].get()).strip(),
            "details": str(self.fields["details"].get()).strip(),
            **{k: v.get() for k, v in self.num_vars.items()},
        }

    def _save(self, data: dict[str, Any]) -> bool:
        user = str(getattr(self.app, "user", {}).get("username", "")) or None
        if self.purchase is not None:
            purchases_repo.update_purchase(
                int(self.purchase["id"]),
                purchase_date=data["purchase_date"],
                material_name=data["material_name"],
                qty_ton=data["qty_ton"],
                supplier=data["supplier"],
                details=data["details"],
                price_per_ton=data["price_per_ton"],
                unloading_fee=data["unloading_fee"],
                handling_fee=data["handling_fee"],
                transport_fee=data["transport_fee"],
                other_fees=data["other_fees"],
            )
        else:
            purchases_repo.add_purchase(
                purchase_date=data["purchase_date"],
                material_name=data["material_name"],
                qty_ton=data["qty_ton"],
                supplier=data["supplier"],
                details=data["details"],
                price_per_ton=data["price_per_ton"],
                unloading_fee=data["unloading_fee"],
                handling_fee=data["handling_fee"],
                transport_fee=data["transport_fee"],
                other_fees=data["other_fees"],
                created_by=user,
            )
        return True


__all__ = ["PurchaseDialog"]