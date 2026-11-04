"""
ui/tabs/_common.py
------------------
أدوات مشتركة لبناء التبويبات (نمط موحّد لكل تبويبات ui/tabs/*).

يوفر:
    TabUI      : حاوية عناصر أساسية (شريط أدوات + حقل بحث + Treeview)
    build_tab  : يبني الهيكل الأساسي لتبويب قائمة/جداول
    fmt        : تنسيق الأرقام للعرض داخل الجداول

نمط التبويب الموحّد:
    toolbar (يمين: أزرار الإجراءات | يسار: حقل البحث)
    tree    (جدول بتمرير أفقي وعمودي + صف stripes)

كل تبويب يستدعي build_tab(parent, app, buttons=[...], columns=[...])
ويحصل على TabUI جاهز، ثم يملأ self.ui.tree بالبيانات في refresh().
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any, Callable, Sequence

from config import settings
from core.logger import get_logger
from ui.widgets import attach_tree_search, export_tree_view, make_button

_log = get_logger("ui.tabs._common")


def fmt(value: Any, decimals: int = 2) -> str:
    """ينسّق رقماً/نصاً للعرض في الجدول: فواصل الآلاف وتقريب اختياري."""
    if value is None or value == "":
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals < 0:
        return f"{num:,.0f}"
    # عرض الأعداد الصحيحة بلا كسور (مثل الكميات 1500 كغ)
    if num == int(num) and abs(num) >= 1:
        return f"{num:,.0f}"
    return f"{num:,.{decimals}f}"


def _tree_columns(tree: ttk.Treeview) -> tuple[str, ...]:
    """
    يعيد أعمدة Treeview بأمان.
    ملاحظة: Treeview لا يملك خاصية `.columns` — الوصول الصحيح `tree["columns"]`.
    """
    try:
        return tuple(str(c) for c in tree["columns"])
    except tk.TclError:
        return ()


@dataclass
class TabUI:
    """حاوية العناصر القياسية لتبويب من نوع «قائمة جدولية»."""

    parent: tk.Misc
    app: Any
    toolbar: ttk.Frame = field(default=None)  # type: ignore[assignment]
    search_var: tk.StringVar = field(default=None)  # type: ignore[assignment]
    search_entry: ttk.Entry = field(default=None)  # type: ignore[assignment]
    tree: ttk.Treeview = field(default=None)  # type: ignore[assignment]
    buttons: dict[str, ttk.Button] = field(default_factory=dict)

    def set_buttons_enabled(self, enabled: bool) -> None:
        """يفعّل/يعطّل كل أزرار الشريط (مثلاً حسب الصلاحيات)."""
        state = "normal" if enabled else "disabled"
        for btn in self.buttons.values():
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass

    def export(self, prefix: str = "export") -> str | None:
        """تصدير محتوى الجدول الحالي CSV/Excel (Ctrl+C العام يستدعيها)."""
        return export_tree_view(self.tree, filename_prefix=prefix)

    def selected_id(self) -> str:
        """يعيد معرّف الصف المحدد (iid — هو رقم السجل الحقيقي في تبويباتنا)."""
        sel = self.tree.selection()
        if not sel:
            return ""
        iid = str(sel[0])
        # إن وُجد عمود #id حقيقي (قيم مملوءة) نفضّله على iid النصي
        columns = _tree_columns(self.tree)
        if "#id" in columns:
            try:
                val = str(self.tree.set(iid, "#id")).strip()
                if val.isdigit():
                    return val
            except tk.TclError:
                pass
        return iid

    def selected_row_values(self) -> list[str]:
        """يعيد قيم الصف المحدد كقائمة نصوص."""
        sel = self.tree.selection()
        if not sel:
            return []
        try:
            return [str(v) for v in self.tree.item(sel[0], "values")]
        except tk.TclError:
            return []

    def selected_row(self) -> dict[str, str]:
        """يعيد قيم الصف المحدد كقاموس أعمدة -> نصوص."""
        iid = self.tree.focus()
        if not iid:
            return {}
        columns = _tree_columns(self.tree)
        if not columns:
            return {}
        try:
            return {col: str(self.tree.set(iid, col)) for col in columns}
        except tk.TclError:
            return {}


def build_tab(
    parent: tk.Misc,
    app: Any,
    *,
    columns: Sequence[str],
    headings: Sequence[tuple[str, str, int]],
    buttons: Sequence[tuple[str, str, Callable[[], Any]]] = (),
    weights: Sequence[float] | None = None,
    per_page: int = 0,
    search_placeholder: str = "🔍 بحث...",
    show: str = "headings",
) -> TabUI:
    """
    يبني هيكل تبويب قياسي ويعيد TabUI.

    Args:
        columns : معرّفات الأعمدة (تُمرَّر لـ Treeview مباشرة).
                  تُضاف تلقائياً عمود خفي '#id' إذا لم يكن موجوداً.
        headings: [(col_id, النص العربي, العرض بالبكسل), ...]
        buttons : [(النص, kind, command), ...] توضع يمين شريط الأدوات.
        weights : معاملات تمدد للأعمدة (اختياري؛ افتراضي 1 لكل عمود).
        show    : "headings" أو "tree headings".

    ملاحظات:
        - البحث الفوري يُثبَّت تلقائياً (attach_tree_search) ويُدعى عبر Ctrl+F.
        - الـ stripes والخط والحجم من إعدادات الثيم الحالية.
    """
    cols = list(columns)
    if "#id" not in cols:
        cols.insert(0, "#id")

    ui = TabUI(parent=parent, app=app)

    # ---------- شريط الأدوات ----------
    toolbar = ttk.Frame(parent)
    toolbar.pack(fill="x", pady=(0, 4))
    ui.toolbar = toolbar

    right = ttk.Frame(toolbar)  # أزرار الإجراءات (يمين)
    right.pack(side="right")
    left = ttk.Frame(toolbar)  # البحث (يسار)
    left.pack(side="left")

    for text, kind, cmd in buttons:
        btn = make_button(right, text, cmd, kind=kind)
        btn.pack(side="right", padx=3, pady=2)
        ui.buttons[text] = btn

    var = tk.StringVar(master=parent)
    ui.search_var = var
    entry = ttk.Entry(left, textvariable=var, width=30, font=settings.FONT_BASE)
    entry.pack(side="left", padx=3, pady=2)
    ui.search_entry = entry
    ttk.Label(left, text=search_placeholder, font=settings.FONT_SMALL).pack(side="left")

    # ---------- الجدول + أشرطة التمرير ----------
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)

    tree = ttk.Treeview(frame, columns=cols, show=show, selectmode="browse")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    vsb.pack(side="right", fill="y")
    hsb.pack(side="bottom", fill="x")
    tree.pack(side="left", fill="both", expand=True)
    ui.tree = tree

    stretch_weights = list(weights) if weights else [1.0] * len(headings)
    for idx, (col, title, width) in enumerate(headings):
        stretch = idx < len(stretch_weights) and stretch_weights[idx] > 0
        tree.heading(col, text=title, anchor="center")
        anchor = "center"
        tree.column(col, width=width, minwidth=40, anchor=anchor,
                    stretch=bool(stretch))
    if "#id" in cols and "#id" not in [h[0] for h in headings]:
        tree.column("#id", width=0, minwidth=0, stretch=False)

    attach_tree_search(tree, entry=entry)

    # شريط سفلي: عدد الصفوف
    count_lbl = ttk.Label(parent, text="", font=settings.FONT_SMALL)
    count_lbl.pack(anchor="w", pady=(2, 0))
    ui.count_label = count_lbl  # type: ignore[attr-defined]

    def _update_count(*_a: Any) -> None:
        try:
            visible = len(tree.get_children())
            count_lbl.configure(text=f"عدد الصفوف الظاهرة: {visible}")
        except tk.TclError:
            pass

    tree.bind("<<TreeviewInsert>>", _update_count, add="+")
    tree.bind("<<TreeviewDeleteItem>>", _update_count, add="+")
    parent.bind("<KeyRelease>", lambda _e: parent.after(120, _update_count), add="+")
    parent.bind("<<TreeSearchFiltered>>", _update_count, add="+")
    _update_count()

    return ui


def clear_tree(tree: ttk.Treeview) -> None:
    """يحذف كل صفوف الجدول بأمان."""
    try:
        for iid in tree.get_children():
            tree.delete(iid)
    except tk.TclError as exc:
        _log.debug("clear_tree فشل: %s", exc)


def fill_rows(tree: ttk.Treeview, rows: Sequence[Sequence[Any]]) -> None:
    """يمسح الجدول ثم يضيف الصفوف (كل صف tuple بنفس ترتيب columns)."""
    clear_tree(tree)
    try:
        for row in rows:
            tree.insert("", "end", values=tuple("" if v is None else v for v in row))
    except tk.TclError:
        _log.exception("تعذّر ملء الجدول")


__all__ = ["TabUI", "build_tab", "clear_tree", "fill_rows", "fmt"]