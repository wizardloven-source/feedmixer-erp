"""
ui/tabs/inventory.py
--------------------
تبويب «المخزون»: أرصدة المواد (المورد − المستهلك = المتبقي)
مع تنبيه الأصناف الأقل من 5 طن والعجز السلبي.

إصلاحات المرحلة 3:
    * حذف دالة adjust_quantity المعطوبة نهائياً — كانت تحتوي نصاً عربياً
      مشوّه الترميز (mojibake)، ولا يوجد زر يستدعيها، وتستدعي
      inventory_service.set_manual_remaining() الوهمية التي ترجع False دائماً.
    * تصحيح مفاتيح القراءة من inventory_service._load_balances():
        supplied_ton / consumed_ton / remaining_ton
      بدلاً من المفاتيح غير الموجودة in_ton / out_ton / remaining_kg
      (كانت أعمدة «المورد» و«المستهلك» و«المتبقي كغ» تظهر صفراً دائماً).
    * عمود «المتبقي (كغ)» يُحسب محلياً للعرض فقط: remaining_ton × KG_PER_TON.
    * بعد كل إعادة بناء للجدول يُطلق حدث <<TreeRefreshed>> ليحدّث
      TreeSearch snapshot — فيستمر البحث الفوري بعد F5 (راجع ui/widgets.py).

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> InventoryController
    controller.refresh()        (F5 / عند فتح التبويب)
    controller.export_current() (Ctrl+C)
    controller.focus_search()   (Ctrl+F)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from services import inventory_service
from ui.tabs._common import TabUI, build_tab, clear_tree, fmt
from ui.widgets import TreeSearch

_log = get_logger("ui.tabs.inventory")

STATUS_LABELS = {
    "ok": "✅ متوفر",
    "low": "⚠️ منخفض",
    "negative": "🛑 عجز",
}


def _find_search(tree: ttk.Treeview) -> TreeSearch | None:
    """يعيد كائن البحث المرتبط بالجدول إن وُجد (للتحديث الموثوق بعد refresh)."""
    return getattr(tree, "_feedmixer_search", None)


def notify_refresh(tree: ttk.Treeview) -> None:
    """يخبر TreeSearch أن الجدول أُعيد بناؤه فيحدّث snapshot.

    إصلاح حرج: بدون هذا التحديث تبقى _all_children تحمل iids قديمة بعد
    أي refresh/F5 فلا يجد البحث الصفوف الجديدة. نستخدم النداء المباشر
    لأن event_generate لا يعمل داخل معالجات الأحداث (سلوك Tk المعروف)،
    ونطلق الحدث أيضاً لتبقياته المتوافقة مع الأربطة الأخرى.
    """
    ts = _find_search(tree)
    if ts is not None:
        try:
            ts.refresh_snapshot()
        except tk.TclError:
            pass
    try:
        tree.event_generate("<<TreeRefreshed>>")
    except tk.TclError:
        pass


class InventoryController:
    """جدول المخزون مع فلترة الحالة وملخص علوي."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self._built = False
        self.ui: TabUI | None = None
        self.status_var = tk.StringVar(master=parent, value="all")
        self.summary_var = tk.StringVar(master=parent, value="")
        self._build(parent)
        self._built = True
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="📦 المخزون", font=settings.FONT_LARGE_BOLD).pack(side="right")
        ttk.Label(head, textvariable=self.summary_var,
                  font=settings.FONT_BASE).pack(side="left")

        filter_row = ttk.Frame(parent)
        filter_row.pack(fill="x", pady=(0, 4))
        ttk.Label(filter_row, text="تصفية:", font=settings.FONT_BASE).pack(side="right")
        combo = ttk.Combobox(
            filter_row, textvariable=self.status_var, width=12, state="readonly",
            values=["all", "low", "negative", "ok"],
        )
        combo.pack(side="right", padx=4)
        combo.set("all")
        combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        labels = {"all": "الكل", "low": "منخفض (< 5 طن)",
                  "negative": "عجز (سالب)", "ok": "متوفر"}
        hint = ttk.Label(filter_row, text="الحالة: الكل", font=settings.FONT_SMALL)
        hint.pack(side="right", padx=6)

        def _sync_hint(*_a: Any) -> None:
            hint.configure(text=f"الحالة: {labels.get(self.status_var.get(), 'الكل')}")

        self.status_var.trace_add("write", _sync_hint)

        # إصلاح: أسماء الأعمدة صارت مطابقة لمفاتيح الخدمة
        # (supplied_ton/consumed_ton/remaining_ton) بدل in_ton/out_ton الخاطئة
        self.ui = build_tab(
            parent, self.app,
            columns=["material", "unit", "supplied_ton", "consumed_ton",
                     "remain_ton", "remain_kg", "status"],
            headings=[
                ("material", "المادة", 160),
                ("unit", "الوحدة", 70),
                ("supplied_ton", "المورد (طن)", 100),
                ("consumed_ton", "المستهلك (طن)", 110),
                ("remain_ton", "المتبقي (طن)", 110),
                ("remain_kg", "المتبقي (كغ)", 110),
                ("status", "الحالة", 110),
            ],
            buttons=[
                ("🔄 تحديث", "flat", self.refresh),
                ("📤 تصدير", "flat", self.export_current),
            ],
            # ملاحظة: لا يوجد زر «تسوية/تعديل كمية» — الدالة حُذفت (كود ميت)
        )
        tree = self.ui.tree
        try:
            tree.tag_configure("low", foreground=settings.COLORS.get("warning", "#b8860b"))
            tree.tag_configure("negative", foreground=settings.COLORS.get("danger", "#b00020"))
            tree.tag_configure("ok", foreground=settings.COLORS.get("success", "#1a7f37"))
        except tk.TclError:
            pass
        tree.bind("<Double-1>", lambda _e: self.show_detail())

    # ------------------------------------------------------------ تحديث
    @staticmethod
    def _row_status(row: dict[str, Any]) -> str:
        """يحدد حالة الصف من حقول الخدمة نفسها (low/negative) بسلّم موثوق."""
        remaining = float(row.get("remaining_ton", 0.0) or 0.0)
        if row.get("negative") or remaining < 0:
            return "negative"
        if row.get("low") or remaining < settings.LOW_STOCK_THRESHOLD_TONS:
            return "low"
        return "ok"

    def refresh(self) -> None:
        if not self._built or self.ui is None:
            return
        try:
            rows_all = inventory_service.inventory_balances(force_refresh=True)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل قراءة المخزون")
            self.app.set_status(f"فشل قراءة المخزون: {exc}")
            return

        status = self.status_var.get()
        rows = []
        for r in rows_all:
            st = self._row_status(r)
            if status != "all" and status != st:
                continue
            remaining = float(r.get("remaining_ton", 0.0) or 0.0)
            # إصلاح: المفاتيح الصحيحة من inventory_service._load_balances؛
            # remaining_kg غير موجود في الخدمة فيُحسب محلياً للعرض فقط
            remaining_kg = remaining * settings.KG_PER_TON
            rows.append((
                r.get("name", ""),
                str(r.get("unit_type", "ton")),
                fmt(r.get("supplied_ton", 0.0)),
                fmt(r.get("consumed_ton", 0.0)),
                fmt(remaining),
                fmt(remaining_kg, -1),
                STATUS_LABELS[st],
            ))
        # الإدراج اليدوي هنا (بدل fill_rows) لدعم وسوم الألوان حسب الحالة
        clear_tree(self.ui.tree)
        for idx, row in enumerate(rows):
            label = str(row[6])
            tag_key = ("negative" if "🛑" in label
                       else "low" if "⚠️" in label else "ok")
            self.ui.tree.insert("", "end", values=row[:7], tags=(tag_key,),
                                iid=f"I{idx}")
        # إصلاح: إخطار TreeSearch بإعادة بناء الجدول حتى لا يفقد البحث
        # نتائجه بعد F5 (snapshot كان يحمل iids قديمة محذوفة)
        notify_refresh(self.ui.tree)

        low_n = sum(1 for r in rows_all if self._row_status(r) == "low")
        neg_n = sum(1 for r in rows_all if self._row_status(r) == "negative")
        total_remaining = sum(float(r.get("remaining_ton", 0) or 0.0) for r in rows_all)
        self.summary_var.set(
            f"إجمالي المتبقي: {total_remaining:,.1f} طن | "
            f"منخفض: {low_n} | عجز: {neg_n}"
        )
        self.app.set_status(f"المخزون: {len(rows_all)} مادة — {low_n} صنف تحت "
                            f"{settings.LOW_STOCK_THRESHOLD_TONS:g} طن")

    # ------------------------------------------------------------ إجراءات
    def show_detail(self) -> None:
        """نافذة تفصيلية لمادة محددة: مصدر/مستهلك شهرياً."""
        if self.ui is None:
            return
        name = self.ui.selected_row().get("material", "")
        if not name:
            self.app.toast("اختر مادة أولاً", "warning")
            return
        try:
            bal = next((r for r in inventory_service.inventory_balances()
                        if str(r.get("name")) == name), {})
        except Exception:  # noqa: BLE001
            bal = {}
        win = tk.Toplevel(self.ui.tree.winfo_toplevel())
        win.title(f"تفاصيل: {name}")
        win.geometry("420x300")
        txt = tk.Text(win, font=settings.FONT_BASE, wrap="word")
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        # إصلاح: المفاتيح الصحيحة (supplied_ton/consumed_ton) وحساب الكغ
        # محلياً من remaining_ton × KG_PER_TON — كان يقرأ مفاتيح غير موجودة
        supplied = float(bal.get("supplied_ton", 0) or 0.0)
        consumed = float(bal.get("consumed_ton", 0) or 0.0)
        remaining = float(bal.get("remaining_ton", 0) or 0.0)
        lines = [
            f"المادة: {name}",
            f"الوحدة: {bal.get('unit_type', 'ton')}",
            f"المورد: {supplied:,.2f} طن",
            f"المستهلك: {consumed:,.2f} طن",
            f"المتبقي: {remaining:,.2f} طن "
            f"({remaining * settings.KG_PER_TON:,.0f} كغ)",
        ]
        if bal.get("missing"):
            lines.append("⚠️ مادة غير مسجَّلة في جدول المواد (حركة يتيماء)")
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        if self.ui is not None:
            self.ui.export("inventory")

    def focus_search(self) -> None:
        if self.ui is not None:
            self.ui.search_entry.focus_set()


# ملاحظة: دالة adjust_quantity حُذفت نهائياً (كود ميت: لا زر يستدعيها،
# ترميز عربي مشوّه mojibake، وتعتمد على set_manual_remaining الوهمية).


def build(parent: tk.Misc, app: Any) -> InventoryController:
    """نقطة الدخول التي تستدعيها النافذة الرئيسية."""
    return InventoryController(parent, app)
