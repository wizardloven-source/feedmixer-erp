"""
ui/tabs/audit.py
----------------
تبويب «سجل التدقيق»: عرض جدول audit_log مع فلاتر وتفاصيل القيم القديمة/الجديدة.

الأعمدة: # | العملية | الجدول | المعرف | التاريخ | المستخدم | ملخص التغيير
الفلاتر: نص حر + جدول (combobox من الجداول المعروفة). الزر 👁️ التفاصيل يعرض
old_value/new_value بصيغة JSON مقروءة في نافذة منبثقة. العرض للقراءة فقط —
الصلاحية audit.view (admin افتراضياً).

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> AuditController
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data.connection import query_all
from ui.tabs._common import TabUI, build_tab

_log = get_logger("ui.tabs.audit")

AUDIT_TABLES = ("users", "farms", "materials", "purchases", "mix_invoices",
                "mix_items", "payments", "recipes", "settings")


def _summarize(new_value: Any, old_value: Any) -> str:
    """سطر ملخص قصير للتغيير للعرض في الجدول."""
    def keys_of(raw: Any) -> dict:
        if not raw:
            return {}
        try:
            data = json.loads(str(raw))
        except Exception:  # noqa: BLE001 - قد تكون قيمة نصية غير JSON
            return {"value": str(raw)[:80]}
        return data if isinstance(data, dict) else {"value": data}

    new_d, old_d = keys_of(new_value), keys_of(old_value)
    if not old_d and new_d:
        return f"إضافة: {', '.join(list(new_d)[:4])}"
    if new_d and not old_d:
        return "حذف السجل"
    changed = [k for k in new_d if str(new_d[k]) != str(old_d.get(k))]
    if changed:
        return "تغيير: " + ", ".join(changed[:5])
    return "-"


class AuditController:
    """كنترولر تبويب سجل التدقيق (قراءة فقط)."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.limit_var = tk.StringVar(master=parent, value="200")
        self.table_var = tk.StringVar(master=parent, value="")
        self._build(parent)
        if has_permission(self.app.user, "audit.view"):
            self.refresh()
        else:
            self.ui.tree.insert("", "end",
                                values=("", "⛔ لا تملك صلاحية عرض السجل", "", "", "", "", ""))

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="🔍 سجل التدقيق", font=settings.FONT_LARGE_BOLD)\
            .pack(side="right")

        buttons = [("👁️ التفاصيل", "flat", self.show_details),
                   ("🔄 تحديث", "flat", self.refresh)]

        columns = ["id", "action", "table", "record", "ts", "user", "summary"]
        headings = [
            ("id", "#", 60), ("action", "العملية", 90), ("table", "الجدول", 120),
            ("record", "المعرف", 70), ("ts", "التاريخ", 140),
            ("user", "المستخدم", 100), ("summary", "ملخص التغيير", 300),
        ]
        self.ui: TabUI = build_tab(parent, self.app, columns=columns, headings=headings,
                                   buttons=buttons, weights=[0, 0.7, 0.9, 0.5, 1.1, 0.8, 2.5])
        self.ui.tree.bind("<Double-1>", lambda _e: self.show_details())
        try:
            self.ui.tree.tag_configure("INSERT", foreground="#2e7d32")
            self.ui.tree.tag_configure("UPDATE", foreground="#1565c0")
            self.ui.tree.tag_configure("DELETE", foreground="#c62828")
        except tk.TclError:
            pass

        filters = ttk.Frame(parent)
        filters.pack(fill="x", pady=(4, 0))
        ttk.Label(filters, text="الجدول:", font=settings.FONT_BASE).pack(side="right")
        combo = ttk.Combobox(filters, textvariable=self.table_var, width=14,
                             state="readonly", font=settings.FONT_BASE,
                             values=["", *AUDIT_TABLES])
        combo.pack(side="right", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Label(filters, text="عدد الصفوف:", font=settings.FONT_BASE).pack(side="right")
        limit_combo = ttk.Combobox(filters, textvariable=self.limit_var, width=7,
                                   state="readonly", font=settings.FONT_BASE,
                                   values=["100", "200", "500", "1000"])
        limit_combo.pack(side="right", padx=4)
        limit_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        """يقرأ آخر N سطراً من audit_log مع فلتر الجدول اختياري."""
        if not has_permission(self.app.user, "audit.view"):
            return
        try:
            limit = int(str(self.limit_var.get()))
        except ValueError:
            limit = 200
        table = str(self.table_var.get()).strip()
        sql = ("SELECT id, action, table_name, record_id, old_value, new_value, "
               "timestamp, user FROM audit_log")
        params: list[Any] = []
        if table:
            sql += " WHERE table_name = ?"
            params.append(table)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(10, min(limit, 5000)))
        try:
            rows = query_all(sql, tuple(params))
        except Exception:  # noqa: BLE001
            _log.exception("فشل قراءة سجل التدقيق")
            self.app.toast("فشل قراءة السجل", "error")
            return
        tree = self.ui.tree
        tree.delete(*tree.get_children())
        for r in rows:
            action = str(r.get("action", ""))
            tree.insert("", "end", iid=str(r["id"]), tags=(action,), values=(
                r["id"], action, r.get("table_name", ""), r.get("record_id", ""),
                r.get("timestamp", ""), r.get("user", ""),
                _summarize(r.get("new_value"), r.get("old_value")),
            ))
        # نخزّن آخر صفوف للعرض التفصيلي الفوري
        self._rows_by_id = {str(r["id"]): r for r in rows}

    # ------------------------------------------------------------ تفاصيل
    def show_details(self) -> None:
        """نافذة تعرض old_value / new_value بصيغة JSON منسّقة."""
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر سطراً من السجل", "warning")
            return
        row = getattr(self, "_rows_by_id", {}).get(str(sel[0]))
        if row is None:
            try:
                from data.connection import query_one

                row = query_one("SELECT * FROM audit_log WHERE id = ?", (int(sel[0]),))
            except Exception:  # noqa: BLE001
                row = None
        if not row:
            return

        def pretty(raw: Any) -> str:
            if raw in (None, ""):
                return "(فارغ)"
            try:
                return json.dumps(json.loads(str(raw)), ensure_ascii=False, indent=2)
            except Exception:  # noqa: BLE001
                return str(raw)

        win = tk.Toplevel(self.app)
        win.title(f"تفاصيل السجل #{row.get('id')}")
        win.geometry("560x480")
        try:
            from ui import styles

            styles.apply_theme(win)
        except Exception:  # noqa: BLE001
            pass
        info = ttk.LabelFrame(win, text="المعلومات العامة", padding=8)
        info.pack(fill="x", padx=8, pady=6)
        ttk.Label(info, text=f"العملية: {row.get('action', '')}   |   "
                             f"الجدول: {row.get('table_name', '')}   |   "
                             f"المعرف: {row.get('record_id', '')}").pack(anchor="e")
        ttk.Label(info, text=f"التاريخ: {row.get('timestamp', '')}   |   "
                             f"المستخدم: {row.get('user', '')}").pack(anchor="e")

        for label, key in (("القيم القديمة (old_value)", "old_value"),
                           ("القيم الجديدة (new_value)", "new_value")):
            frame = ttk.LabelFrame(win, text=label, padding=6)
            frame.pack(fill="both", expand=True, padx=8, pady=4)
            txt = tk.Text(frame, height=8, wrap="word", font=settings.FONT_SMALL,
                          bg="#ffffff", fg="#111111")
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", pretty(row.get(key)))
            txt.configure(state="disabled")

        ttk.Button(win, text="إغلاق", command=win.destroy).pack(pady=6)

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        if not has_permission(self.app.user, "audit.view"):
            self.app.toast("لا تملك صلاحية التصدير من السجل", "error")
            return
        self.ui.export("audit_log")

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass


def build(parent: tk.Misc, app: Any) -> AuditController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return AuditController(parent, app)
