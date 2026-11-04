"""
ui/tabs/prices.py
-----------------
تبويب «الأسعار»: جدول مواد التسعير (نفس جدول materials) مع التركيز على
السعر: سعر الطن الأساسي + عتالة + هدر + سعر الكيلوغرام الفعلي المحسوب
حسب نوع الوحدة (ton/kg/fixed).

ملاحظة مهمة:
    تعديل الأسعار هنا يؤثر على الخلطات الجديدة فقط.
    الفواتير المحفوظة تحتفظ بسعرها المجمّد وقت الإنشاء.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any
from tkinter import ttk

from config import settings
from core.utils import material_kg_price, safe_float
from data import purchases_repo
from ui.tabs._common import fmt
from ui.tabs.materials_base import MaterialsPanel

UNIT_LABELS = {"ton": "طن", "kg": "كغ", "fixed": "مقطوعية"}


def _latest_real_price(material_name: str) -> float | None:
    """آخر سعر حقيقي/طن مسجل في التوريدات لهذه المادة (أو None)."""
    try:
        rows = purchases_repo.get_purchases_by_material(material_name)
    except Exception:  # noqa: BLE001
        return None
    for row in reversed(rows):
        price = safe_float(row.get("real_price_per_ton"), 0.0)
        if price > 0:
            return price
    return None


class PricesController:
    """كنترولر تبويب الأسعار — يغلّف MaterialsPanel بصف تسعيري."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.panel = MaterialsPanel(
            parent,
            app,
            title="🏷️ أسعار المواد",
            columns=["id", "name", "unit", "base", "handling", "loss", "kg_price", "last_real"],
            headings=[
                ("id", "#", 45), ("name", "المادة", 170), ("unit", "الوحدة", 80),
                ("base", "سعر الطن", 110), ("handling", "عتالة", 90),
                ("loss", "هدر", 90), ("kg_price", "سعر الكغ الفعلي", 130),
                ("last_real", "آخر توريد حقيقي/طن", 150),
            ],
            weights=[0, 2, 0.7, 1, 0.8, 0.8, 1.2, 1.3],
            row_formatter=self._format_row,
            export_prefix="prices",
        )
        # تنبيه المستخدم بأن التعديل مستقبلي فقط
        try:
            ttk.Label(
                parent,
                text="ℹ️ تعديل الأسعار يؤثر على الخلطات الجديدة فقط — الفواتير المحفوظة تحتفظ بسعرها.",
                font=settings.FONT_SMALL,
                foreground="#888888",
            ).pack(fill="x", pady=(2, 0))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ صفوف
    @staticmethod
    def _format_row(material: dict, _app: Any) -> tuple[list[Any], str]:
        name = str(material.get("name", ""))
        unit = str(material.get("unit_type") or "ton")
        kg_price = material_kg_price(material)
        last_real = _latest_real_price(name)
        row = [
            material.get("id", ""),
            name,
            UNIT_LABELS.get(unit, unit),
            fmt(material.get("base_price")),
            fmt(material.get("handling_fee")),
            fmt(material.get("loss_fee")),
            f"{kg_price:,.4f}" if kg_price else "-",
            fmt(last_real) if last_real is not None else "-",
        ]
        tag = "ok" if kg_price > 0 else "low"
        return row, tag

    # ------------------------------------------------------------ واجهة عامة
    def refresh(self) -> None:
        self.panel.refresh()

    def new_record(self) -> None:
        self.panel.new_record()

    def edit_selected(self) -> None:
        self.panel.edit_selected()

    def delete_selected(self) -> None:
        self.panel.delete_selected()

    def export_current(self) -> None:
        self.panel.export_current()

    def focus_search(self) -> None:
        self.panel.focus_search()


def build(parent: tk.Misc, app: Any) -> PricesController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return PricesController(parent, app)