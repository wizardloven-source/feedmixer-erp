"""
ui/tabs/inventory.py
--------------------
تبويب «المخزون»: أرصدة المواد (المورد − المستهلك = المتبقي)
مع تنبيه الأصناف الأقل من 5 طن والعجز السلبي.

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

_log = get_logger("ui.tabs.inventory")

STATUS_LABELS = {
    "ok": "✅ متوفر",
    "low": "⚠️ منخفض",
    "negative": "🛑 عجز",
}


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

        self.ui = build_tab(
            parent, self.app,
            columns=["material", "unit", "in_ton", "out_ton", "remain_ton",
                     "remain_kg", "status"],
            headings=[
                ("material", "المادة", 160),
                ("unit", "الوحدة", 70),
                ("in_ton", "المورد (طن)", 100),
                ("out_ton", "المستهلك (طن)", 110),
                ("remain_ton", "المتبقي (طن)", 110),
                ("remain_kg", "المتبقي (كغ)", 110),
                ("status", "الحالة", 110),
            ],
            buttons=[
                ("🔄 تحديث", "flat", self.refresh),
                ("📤 تصدير", "flat", self.export_current),
            ],
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
            remaining = float(r.get("remaining_ton", 0.0))
            if remaining < 0:
                st = "negative"
            elif remaining < settings.LOW_STOCK_THRESHOLD_TONS:
                st = "low"
            else:
                st = "ok"
            if status != "all" and status != st:
                continue
            rows.append((
                r.get("name", ""),
                str(r.get("unit_type", "ton")),
                fmt(r.get("in_ton", 0.0)),
                fmt(r.get("out_ton", 0.0)),
                fmt(remaining),
                fmt(float(r.get("remaining_kg", 0.0)), -1),
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

        low_n = sum(1 for r in rows_all
                    if 0 <= float(r.get("remaining_ton", 0)) < settings.LOW_STOCK_THRESHOLD_TONS)
        neg_n = sum(1 for r in rows_all if float(r.get("remaining_ton", 0)) < 0)
        total_remaining = sum(float(r.get("remaining_ton", 0)) for r in rows_all)
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
        except Exception:
            bal = {}
        win = tk.Toplevel(self.ui.tree.winfo_toplevel())
        win.title(f"تفاصيل: {name}")
        win.geometry("420x300")
        txt = tk.Text(win, font=settings.FONT_BASE, wrap="word")
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        lines = [
            f"المادة: {name}",
            f"الوحدة: {bal.get('unit_type', 'ton')}",
            f"المورد: {float(bal.get('in_ton', 0)):,.2f} طن",
            f"المستهلك: {float(bal.get('out_ton', 0)):,.2f} طن",
            f"المتبقي: {float(bal.get('remaining_ton', 0)):,.2f} طن "
            f"({float(bal.get('remaining_kg', 0)):,.0f} كغ)",
        ]
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        if self.ui is not None:
            self.ui.export("inventory")

    def focus_search(self) -> None:
        if self.ui is not None:
            self.ui.search_entry.focus_set()



    def adjust_quantity(self) -> None:
        """إضافة/ تعديل كمية مادة محددة عند تسوية المخزون."""
        if self.ui is None:
            return
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("ط§ط®طھط± ظ…ط§ط¯ط© ظ…ظ† ط§ظ„ط¬ط¯ظˆظ„", "warning")
            return
        name = self.ui.selected_row().get("material", "")
        if not name:
            self.app.toast("ط§ط®طھط± ظ…ط§ط¯ط© ظ…ظ† ط§ظ„ط¬ط¯ظˆظ„", "warning")
            return
        try:
            bal = next((r for r in inventory_service.inventory_balances()
                        if str(r.get("name")) == name), {})
        except Exception:
            bal = {}
        current = float(bal.get("remaining_ton", 0.0))
        import tkinter as tk
        root = tk.Toplevel(self.ui.tree.winfo_toplevel())
        root.title(f"ط§ظ„ط·ط¨ط§ط¹ط©: {name}")
        root.geometry("360x200")
        ttk.Label(root, text="ط§ظ„طھط§ط±ظٹط® ط§ظ„ظ…ط§ط¯ط©:", font=settings.FONT_BASE).pack(anchor="w", padx=20, pady=(20, 5))
        entry = ttk.Entry(root, width=40, font=settings.FONT_BASE)
        entry.insert(0, f"{current:,.3f}")
        entry.pack(padx=20, pady=(0, 10))
        result = {"value": None}

        def ok():
            try:
                val = float(entry.get().replace(",", "").replace(" ", ""))
                if val < 0:
                    raise ValueError("كمية سالبة غير مسموحة")
                result["value"] = val
            except (ValueError, tk.TclError):
                self.app.toast("يرجى إدخال رقم صحيح للكمية", "error")
                return
            root.destroy()

        def cancel():
            root.destroy()

        btn_row = ttk.Frame(root)
        btn_row.pack(padx=20, pady=(0, 20), fill="x")
        ttk.Button(btn_row, text="ط§ط®طھط±", command=ok).pack(side="right", padx=(10, 0))
        ttk.Button(btn_row, text="ط¥ظ„ط؛ط§ط¤", command=cancel).pack(side="right", padx=(0, 10))
        root.wait_window(root)
        root.destroy()

        if result["value"] is None:
            return
        try:
            ok = inventory_service.set_manual_remaining(name, result["value"])
            if ok:
                self.app.toast(f"طھظ… ط§ظ „ط·ط¨ط§ط¹ط© آ«{name}آ» ط¨ظ†ط¬ط§ط­ ًں”‘", "success")
                self.refresh()
            else:
                self.app.toast("ط§ظ„ظ…ط§ط¯ط© ط؛ظٹط± ظ…ظˆط¬ظˆط¯ط©", "error")
        except Exception as exc:
            self.app.toast(f"ط®ط·ط£: {exc}", "error")

def build(parent: tk.Misc, app: Any) -> InventoryController:
    """نقطة الدخول التي تستدعيها النافذة الرئيسية."""
    return InventoryController(parent, app)
