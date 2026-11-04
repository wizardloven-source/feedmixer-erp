"""
ui/widgets.py
-------------
أدوات واجهة قابلة لإعادة الاستخدام تُبنى فوق ttk القياسي.

المحتوى:
    make_button        : زرttk بنمط دلالي (primary/accent/danger...) + اختصار لوحة.
    make_toolbar       : شريط أزرار أفقي موحد المسافات.
    attach_tree_search : بحث فوري أعلى أي Treeview (Ctrl+F) مع تظليل التطابق.
    make_date_entry    : حقل تاريخ — tkcalendar.DateEntry إن توفّر، وإلا Entry
                         مع قناع YYYY-MM-DD وتحقق تلقائي عند فقدان التركيز.
    make_labeled_entry : Entry + Label فوقه في إطار واحد (نماذج الحوارات).
    make_card          : بطاقة إحصائية (عنوان + قيمة كبيرة) للوحة الرئيسية.
    add_status_bar     : شريط حالة سفلي (رسالة + مستخدم + ساعة) لأي نافذة.
    export_tree_csv    : تصدير محتوى Treeview إلى CSV/Excel عبر reports.exporter.

كل الدوال آمنة: تفشل بصمت مسجّلاً أو تعيد None عند غياب Tk في البيئة.
"""

from __future__ import annotations

import datetime as _dt
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Iterable, Sequence

from config import settings
from core import utils
from core.logger import get_logger
from ui.styles import BUTTON_KINDS

_log = get_logger("ui.widgets")


# ============================================================
# 1) الأزرار وأشرطة الأدوات
# ============================================================

def make_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], Any] | None = None,
    kind: str = "flat",
    shortcut: str | None = None,
    tooltip: str | None = None,
    state: str = "normal",
    sticky: str = "nesw",
) -> ttk.Button:
    """
    ينشئ ttk.Button بالنمط الدلالي المطلوب.

    Args:
        parent  : الأب (Frame/Toolbar...).
        text    : النص العربي للزر.
        command : دالة الاستدعاء (تُلف لمنع سقوط التطبيق عند الخطأ).
        kind    : أحد ui.styles.BUTTON_KINDS؛ غير المعروف يسقط لـ flat.
        shortcut: اختصار لوحة مفاتيح يُربط على مستوى parent ("<Control-s>").
        tooltip : نص يظهر كـ status في شريط الحالة عند التحويم (بسيط).
        state   : normal / disabled.
        sticky  : موضع grid داخل الأب.

    Returns:
        الزر المُنشأ (يمكن إعاقة/تفعيل اللاحق عبر button.configure(state=...)).
    """
    style_kind = kind if kind in BUTTON_KINDS else "flat"

    def _safe_command() -> None:
        if command is None:
            return
        try:
            command()
        except Exception as exc:  # noqa: BLE001 - لا نسقط الواجهة أبداً
            _log.exception("خطأ في أمر الزر %r: %s", text, exc)
            utils.show_toast(parent, f"خطأ: {exc}", kind="error")

    button = ttk.Button(parent, text=text, style=f"{style_kind.capitalize()}.TButton",
                        command=_safe_command, state=state)
    if shortcut:
        try:
            bind_target = button.winfo_toplevel()
            bind_target.bind(shortcut, lambda _e: _safe_command())
        except tk.TclError as exc:
            _log.debug("تعذّر ربط الاختصار %s: %s", shortcut, exc)
    if tooltip:
        def _show(_e: tk.Event) -> None:
            top = button.winfo_toplevel()
            bar = getattr(top, "status_label", None)
            if isinstance(bar, tk.Label):
                bar.configure(text=tooltip)
        button.bind("<Enter>", _show, add="+")
    # لا نعبّئ الزر هنا: make_toolbar والتبويبات تقرر pack/grid بنفسها.
    return button


def make_toolbar(parent: tk.Misc, buttons: Sequence[tuple[str, str, Callable[[], Any]]]) -> ttk.Frame:
    """
    يبني شريط أدوات أفقي من قائمة (النص، النوع الدلالي، الأمر).

    مثال:
        make_toolbar(tab, [("＋ إضافة", "primary", on_add),
                           ("🖨 طباعة", "info", on_print)])
    """
    bar = ttk.Frame(parent)
    for text, kind, cmd in buttons:
        btn = make_button(bar, text, cmd, kind=kind)
        btn.pack(side="right", padx=3, pady=4)
    return bar


# ============================================================
# 2) البحث الفوري في Treeview
# ============================================================

class TreeSearch:
    """
    يربط حقل بحث فوري بـ Treeview:

    - يكتب المستخدم → تُخفى الصفوف غير المطابقة (item hide) وتظهر المطابقة.
    - Ctrl+F يركّز على حقل البحث ويحدد نصه.
    - Esc يمسح البحث ويعرض كل الصفوف.
    - يعمل مع الأعمدة كلها (بحث substring غير حساس لحالة الأحرف).
    """

    def __init__(self, tree: ttk.Treeview, entry: ttk.Entry | None = None,
                 columns: Iterable[int] | None = None) -> None:
        self.tree = tree
        self.columns = list(columns) if columns is not None else list(range(1, 99))
        self._all_children: list[str] = []
        if entry is None:
            frame = ttk.Frame(tree.master)
            entry = ttk.Entry(frame, font=settings.FONT_BASE)
            frame.pack(fill="x", side="top")
            entry.pack(side="left", fill="x", expand=True, padx=(0, 6), pady=3)
            ttk.Label(frame, text="🔍 بحث:", font=settings.FONT_BASE)\
                .pack(side="left")
        self.entry = entry
        entry.bind("<KeyRelease>", self._on_change)
        entry.bind("<Escape>", self.clear)
        try:
            tree.bind("<Control-f>", self.focus_search, add="+")
        except tk.TclError:
            pass
        # تسجيل كل الصفوف الحالية
        self.snapshot()

    # ---------- API ----------
    def snapshot(self) -> None:
        """يعيد قراءة كل الصفوف الجذرية الحالية (استدعِها بعد كل refresh)."""
        try:
            self._all_children = list(self.tree.get_children(""))
        except tk.TclError:
            self._all_children = []

    def focus_search(self, _event: tk.Event | None = None) -> str:
        """يركّز على حقل البحث ويحدد محتواه (يُربط بـ Ctrl+F)."""
        try:
            self.entry.select_range(0, "end")
            self.entry.icursor("end")
            self.entry.focus_set()
        except tk.TclError:
            pass
        return "break"

    def clear(self, _event: tk.Event | None = None) -> None:
        """يمسح النص ويعرض كل الصفوف."""
        try:
            self.entry.delete(0, "end")
        except tk.TclError:
            pass
        self._apply("")

    # ---------- internals ----------
    def _on_change(self, _event: tk.Event | None = None) -> None:
        try:
            needle = self.entry.get()
        except tk.TclError:
            needle = ""
        self._apply(needle)

    def _matches(self, item_id: str, needle_lower: str) -> bool:
        values = self.tree.item(item_id, "values")
        if not self.columns or len(self.columns) >= 90:
            check_indices = range(len(values))  # كل الأعمدة فعلياً
        else:
            check_indices = self.columns
        for col_idx in check_indices:
            if col_idx >= len(values):
                continue
            if needle_lower in utils.normalize_digits(str(values[col_idx])).lower():
                return True
        return False

    def _apply(self, needle: str) -> None:
        needle_lower = utils.normalize_digits(needle).strip().lower()
        try:
            visible_ids: list[str] = []
            for item_id in self._all_children:
                if not self.tree.exists(item_id):
                    continue
                show = (not needle_lower) or self._matches(item_id, needle_lower)
                if show:
                    visible_ids.append(item_id)
            # إخفاء الكل ثم إظهار المطابق (أبسط وأسرع من delete/re-insert)
            for item_id in self._all_children:
                if self.tree.exists(item_id):
                    self.tree.detach(item_id)
            for item_id in visible_ids:
                self.tree.reattach(item_id, "", "end")
        except tk.TclError as exc:
            _log.debug("فشل تطبيق البحث: %s", exc)


def attach_tree_search(tree: ttk.Treeview,
                       entry: ttk.Entry | None = None) -> TreeSearch:
    """اختصار لبناء TreeSearch حول Treeview (ينشئ حقل بحث فوقه إن لم يُعطَ)."""
    return TreeSearch(tree, entry=entry)


# ============================================================
# 3) حقول النماذج
# ============================================================

_DATE_FMT = "%Y-%m-%d"


def _validate_date_text(text: str) -> bool:
    try:
        _dt.datetime.strptime(utils.normalize_digits(text).strip(), _DATE_FMT)
        return True
    except (ValueError, TypeError):
        return False


def make_date_entry(
    parent: tk.Misc,
    initial: str | None = None,
    width: int = 12,
    on_change: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """
    حقل تاريخ موحّد:

    - إذا توفّر tkcalendar → DateEntry (انتقاء تقويمي + كتابة يدوية).
    - وإلا → ttk.Entry بقناع YYYY-MM-DD، مع تصحيح تلقائي لتاريخ اليوم
      عند فقدان التركيز إذا كان النص غير صالح.

    يعيد قاموساً: {"get": Callable[()->str], "set": Callable[(str)->None],
                   "widget": tk.Widget}
    """
    value = utils.today_str() if initial is None else str(initial)

    if settings.HAS_TKCALENDAR:  # pragma: no cover - يعتمد على البيئة
        try:
            date_widget = settings.tkcalendar.DateEntry(
                parent, textvariable=None, width=width, date_format=_DATE_FMT,
                daypattern="{{dd}}", monthpattern="{{mm}}", yearpattern="{{yyyy}}",
            )
            try:
                parsed = _dt.datetime.strptime(value, _DATE_FMT)
                date_widget.set_value(parsed.date())
            except (ValueError, TypeError):
                pass

            def _get_cal() -> str:
                try:
                    return date_widget.get_date().strftime(_DATE_FMT)
                except Exception:  # noqa: BLE001
                    return utils.today_str()

            def _set_cal(txt: str) -> None:
                try:
                    date_widget.set_value(
                        _dt.datetime.strptime(txt, _DATE_FMT).date())
                except Exception as exc:  # noqa: BLE001
                    _log.debug("DateEntry.set failed: %s", exc)

            if on_change is not None:
                date_widget.bind("<<DateEntrySelected>>",
                                 lambda _e: on_change(_get_cal()))
            date_widget.pack(side="left", padx=3, pady=2)
            return {"get": _get_cal, "set": _set_cal, "widget": date_widget}
        except Exception as exc:  # noqa: BLE001 - سقوط آمن للـ Entry العادي
            _log.info("تعذّر إنشاء DateEntry (%s) - استخدام Entry نصي", exc)

    var = tk.StringVar(master=parent, value=value)
    entry = ttk.Entry(parent, textvariable=var, width=width, justify="center")

    def _get() -> str:
        txt = var.get().strip()
        return txt if _validate_date_text(txt) else utils.today_str()

    def _set(txt: str) -> None:
        var.set(str(txt))

    def _on_focus_out(_e: tk.Event) -> None:
        if not _validate_date_text(var.get()):
            var.set(value if _validate_date_text(value) else utils.today_str())

    entry.bind("<FocusOut>", _on_focus_out)
    if on_change is not None:
        var.trace_add("write", lambda *_a: on_change(_get()))
    entry.pack(side="left", padx=3, pady=2)
    return {"get": _get, "set": _set, "widget": entry}


def make_labeled_entry(
    parent: tk.Misc,
    label: str,
    initial: str = "",
    width: int = 24,
    show: str | None = None,
    readonly: bool = False,
) -> dict[str, Any]:
    """
    سطر نموذج: Label + Entry داخل Frame. يعيد:
        {"frame","label","entry","get"()->str,"set"(str)->None}
    """
    frame = ttk.Frame(parent)
    lbl = ttk.Label(frame, text=label, font=settings.FONT_BASE, width=16, anchor="e")
    var = tk.StringVar(master=parent, value=str(initial))
    entry = ttk.Entry(frame, textvariable=var, width=width, show=show or "")
    if readonly:
        entry.configure(state="readonly")
    lbl.pack(side="right", padx=(6, 2))
    entry.pack(side="right", padx=2)
    frame.pack(fill="x", pady=2)
    return {
        "frame": frame,
        "label": lbl,
        "entry": entry,
        "get": lambda: var.get().strip(),
        "set": lambda txt: var.set(str(txt)),
    }


def make_labeled_combo(
    parent: tk.Misc,
    label: str,
    values: Sequence[str],
    initial: str = "",
    width: int = 22,
    readonly: bool = True,
) -> dict[str, Any]:
    """سطر نموذج: Label + Combobox (readonly افتراضياً)."""
    frame = ttk.Frame(parent)
    lbl = ttk.Label(frame, text=label, font=settings.FONT_BASE, width=16, anchor="e")
    combo = ttk.Combobox(frame, values=list(values), width=width,
                         state="readonly" if readonly else "normal",
                         font=settings.FONT_BASE)
    combo.set(initial or (values[0] if values else ""))
    lbl.pack(side="right", padx=(6, 2))
    combo.pack(side="right", padx=2)
    frame.pack(fill="x", pady=2)
    return {
        "frame": frame,
        "label": lbl,
        "combo": combo,
        "get": lambda: combo.get().strip(),
        "set": lambda txt: combo.set(str(txt)),
    }


# ============================================================
# 4) بطاقات لوحة القيادة وشريط الحالة
# ============================================================

def make_card(parent: tk.Misc, title: str, value: str = "-",
              color_key: str = "primary", width: int = 15) -> dict[str, Any]:
    """
    بطاقة إحصائية للوحة الرئيسية: عنوان صغير + قيمة كبيرة ملوّنة.
    يعيد {"frame", "title", "value", "set_value"(str)}
    """
    c = settings.COLORS
    card = tk.Frame(parent, bg=c["surface"], highlightbackground=c["border"],
                    highlightthickness=1)
    inner_top = tk.Frame(card, bg=c[color_key])
    inner_top.pack(fill="x")
    tk.Frame(inner_top, bg=c[color_key], height=4).pack()
    lbl_title = tk.Label(card, text=title, bg=c["surface"], fg=c["text_muted"],
                         font=settings.FONT_BASE)
    lbl_title.pack(pady=(8, 0))
    lbl_value = tk.Label(card, text=value, bg=c["surface"], fg=c[color_key],
                         font=settings.FONT_TITLE_BOLD)
    lbl_value.pack(pady=(2, 10))
    card.pack_propagate(False)
    card.configure(width=width * 7, height=86)
    return {
        "frame": card,
        "title": lbl_title,
        "value": lbl_value,
        "set_value": lambda txt: lbl_value.configure(text=str(txt)),
    }


def add_status_bar(root: tk.Tk, username: str = "", role_label: str = "") -> tk.Label:
    """
    يضيف شريط حالة سفلياً للنافذة ويربط السمة `root.status_label` عليه،
    مع تحديث الساعة كل دقيقة. يعيد الـ Label الرئيسي (الرسالة).
    """
    c = settings.COLORS
    bar = tk.Frame(root, bg=c["header_bg"], height=26)
    bar.pack(side="bottom", fill="x")
    bar.pack_propagate(False)

    msg = tk.Label(bar, text="جاهز", bg=c["header_bg"], fg=c["header_fg"],
                   font=settings.FONT_SMALL, anchor="e")
    msg.pack(side="right", padx=8)
    user_lbl = tk.Label(bar, text=f"👤 {username} ({role_label})" if username else "",
                        bg=c["header_bg"], fg=c["header_fg"],
                        font=settings.FONT_SMALL, anchor="e")
    user_lbl.pack(side="left", padx=8)
    clock = tk.Label(bar, text="", bg=c["header_bg"], fg=c["header_fg"],
                     font=settings.FONT_SMALL)
    clock.pack(side="left", padx=8)

    root.status_label = msg  # type: ignore[attr-defined]

    def _tick() -> None:
        try:
            clock.configure(text=_dt.datetime.now().strftime("%H:%M"))
            root.after(30_000, _tick)
        except tk.TclError:
            pass

    _tick()
    return msg


def set_status(root: tk.Tk, message: str) -> None:
    """يحدّث نص شريط الحالة إن كان موجوداً (آمن عند غيابه)."""
    label = getattr(root, "status_label", None)
    if isinstance(label, tk.Label):
        try:
            label.configure(text=message)
        except tk.TclError:
            pass


# ============================================================
# 5) تصدير محتوى جدول
# ============================================================

def tree_rows(tree: ttk.Treeview) -> tuple[list[str], list[list[str]]]:
    """
    يقرأ رؤوس الأعمدة وصفوف Treeview المرئية كـ (headers, rows).
    يستخدمه تبويبات كثيرة للتصدير CSV/Excel.
    """
    headers: list[str] = []
    for col in tree["columns"]:
        heading = tree.heading(col, "text") or col
        headers.append(str(heading))
    rows: list[list[str]] = []
    for item_id in tree.get_children(""):
        rows.append([str(v) for v in tree.item(item_id, "values")])
    return headers, rows


def export_tree_view(tree: ttk.Treeview, filename_prefix: str = "export") -> str | None:
    """
    يصدّر صفوف Treeview المرئية إلى CSV (أو Excel إن توفر openpyxl)،
    ويفتح الملف بعد التصدير. يعيد المسار أو None عند الفشل.
    """
    from reports.exporter import export_table  # استيراد متأخر لدورة الاستيراد

    headers, rows = tree_rows(tree)
    if not rows:
        utils.show_toast(tree, "لا توجد بيانات للتصدير", kind="warning")
        return None
    use_excel = settings.HAS_OPENPYXL
    try:
        path = export_table(headers, rows,
                            filename_prefix=filename_prefix,
                            as_excel=use_excel)
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل تصدير الجدول: %s", exc)
        utils.show_toast(tree, f"فشل التصدير: {exc}", kind="error")
        return None
    utils.open_with_default_app(path)
    utils.show_toast(tree, f"تم التصدير: {path}", kind="success")
    return path
