"""
ui/styles.py
------------
تهيئة ثيمات ttk ووضع RTL (من اليمين لليسار) للتطبيق بالكامل.

المسؤوليات:
    1) تفعيل وضع RTL العام عبرoptiondb (يجب أن يُستدعى قبل إنشاء أي widget).
    2) بناء/تحديث ستايل ttk واحد باسم "Mixer" يغطي:
       Treeview / TNotebook / TButton / TEntry / TCombobox / TLabelframe /
       TCheckbutton / TProgressbar / Vertical.TScrollbar / Horizontal.TScrollbar.
    3) تهيئة خيارات tk.Label/tk.Frame العامة (الخط، الألوان، padx).
    4) إرجاع قائمة أنماط الأزرار الدلالية (Primary/Accent/Danger...) التي
       تستخدمها ui.widgets.make_button.

يُعاد استدعاء apply_theme() عند تبديل الوضع الليلي/النهاري من تبويب الإعدادات؛
الدالة idempotent وتعيد بناء كل الأنماط من settings.COLORS الحالية.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger

_log = get_logger("ui.styles")

STYLE_NAME: str = "Mixer"

#: أنماط الأزرار الدلالية المتاحة لـ make_button(kind=...)
BUTTON_KINDS: tuple[str, ...] = (
    "primary",
    "accent",
    "success",
    "danger",
    "warning",
    "info",
    "flat",
)

# ألوان خلفية/نص كل نوع زر (مفاتيح من settings.COLORS)
_BUTTON_COLOR_MAP: dict[str, tuple[str, str]] = {
    "primary": ("primary", "header_fg"),
    "accent": ("accent", "toast_fg"),
    "success": ("success", "header_fg"),
    "danger": ("danger", "header_fg"),
    "warning": ("warning", "toast_fg"),
    "info": ("info", "header_fg"),
    "flat": ("surface_alt", "text"),
}


def enable_rtl(root: tk.Misc) -> None:
    """
    يفعّل اتجاه RTL على مستوى التطبيق عبر optiondb.

    يجب استدعاؤها مرة واحدة مباشرة بعد إنشاء tk.Tk() وقبل أي widget،
    لأن optiondb لا يؤثر على Widgets المُنشأة سابقاً بشكل موثوق.
    """
    try:
        root.option_add("*tkDirectoryStyle", "RTL")
        # بعض أنظمة لينكس/Mac قد لا تدعم الخيار أعلاه؛ نتجاهل الخطأ بهدوء.
        _log.info("تم تفعيل وضع RTL عبر optiondb")
    except tk.TclError as exc:
        _log.warning("تعذّر تفعيل RTL: %s", exc)


def _c(key: str) -> str:
    """قراءة لون آمن من اللوحة الحالية."""
    return settings.COLORS.get(key, "#000000")


def configure_root_defaults(root: tk.Tk) -> None:
    """تهيئة الخيارات العامة لـ tk widgets والخط الافتراضي وخلفية النافذة."""
    c = settings.COLORS
    root.option_add("*Font", settings.FONT_BASE)
    for cls in (
        "Tk",
        "Label",
        "Frame",
        "Toplevel",
        "Button",
        "Entry",
        "Text",
        "Listbox",
        "Menu",
        "Message",
        "Labelframe",
        "Checkbutton",
        "Radiobutton",
    ):
        try:
            root.option_add(f"*{cls}.background", c["bg"])
        except tk.TclError:
            continue
    try:
        root.option_add("*Label.foreground", c["text"])
        root.option_add("*Text.background", c["surface"])
        root.option_add("*Text.foreground", c["text"])
        root.option_add("*Text.insertBackground", c["surface"])
        root.option_add("*Entry.background", c["surface"])
        root.option_add("*Entry.foreground", c["text"])
        root.option_add("*Entry.selectBackground", c["selection"])
        root.option_add("*Listbox.background", c["surface"])
        root.option_add("*Listbox.foreground", c["text"])
        root.option_add("*Listbox.selectBackground", c["selection"])
        root.option_add("*Listbox.selectForeground", c["text"])
        root.option_add("*Menu.background", c["surface"])
        root.option_add("*Menu.foreground", c["text"])
        root.option_add("*Menu.activeBackground", c["selection"])
        root.option_add("*TCombobox*Listbox.background", c["surface"])
        root.option_add("*TCombobox*Listbox.foreground", c["text"])
        root.option_add("*TCombobox*Listbox.selectBackground", c["selection"])
    except tk.TclError as exc:
        _log.warning("تعذّر ضبط بعض خيارات tk العامة: %s", exc)


def apply_theme(root: tk.Misc | None = None) -> ttk.Style:
    """
    يبني (أو يعيد بناء) ستايل "Mixer" من settings.COLORS الحالية.

    Args:
        root: نافذة/widget لأي غرض؛ غير مستخدمة فعلياً لكن تُقبل للاتساق.

    Returns:
        كائن ttk.Style الخاص بالتطبيق (singleton في Tkinter).
    """
    del root  # غير مستخدم - مخصص لاتساق الاستدعاء فقط
    style = ttk.Style()
    try:
        style.theme_use("clam")  # أكثر الثيمات قابلية للتخصيص عبر المنصات
    except tk.TclError:
        _log.warning("ثيم clam غير متاح - سيتم استخدام الثيم الافتراضي")

    c = settings.COLORS
    style.configure(".", font=settings.FONT_BASE, background=c["bg"],
                    foreground=c["text"], fieldbackground=c["surface"],
                    bordercolor=c["border"], lightcolor=c["bg"],
                    darkcolor=c["bg"], troughcolor=c["surface_alt"])

    # ---------- Treeview ----------
    style.configure(
        "Treeview",
        rowheight=settings.TREE_ROW_HEIGHT,
        background=c["surface"],
        fieldbackground=c["surface"],
        foreground=c["text"],
        bordercolor=c["border"],
        font=settings.FONT_BASE,
    )
    style.configure("TreeviewHeading",
                    background=c["header_bg"], foreground=c["header_fg"],
                    font=settings.FONT_BOLD, relief="flat", padding=6)
    style.map(
        "Treeview",
        background=[("selected", c["selection"])],
        foreground=[("selected", c["text"])],
    )
    style.configure("Striped.Treeview", background=c["stripe"],
                    fieldbackground=c["stripe"], foreground=c["text"])

    # ---------- Notebook ----------
    style.configure(
        "TNotebook", background=c["bg"], borderwidth=0, tabmargins=(8, 6, 8, 0)
    )
    style.configure(
        "TNotebook.Tab",
        padding=(18, 7),
        font=settings.FONT_MEDIUM,
        background=c["surface_alt"],
        foreground=c["text_muted"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", c["primary"]), ("active", c["primary_light"])],
        foreground=[("selected", c["header_fg"]), ("active", c["text"])],
        expand=[("selected", (0, 0, 0, 2))],
    )

    # ---------- Buttons ----------
    style.configure(
        "TButton",
        padding=(12, 6),
        font=settings.FONT_BASE,
        background=c["surface_alt"],
        foreground=c["text"],
        bordercolor=c["border"],
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("active", c["selection"]), ("disabled", c["bg"])],
        foreground=[("disabled", c["disabled"])],
    )
    for kind in BUTTON_KINDS:
        bg_key, fg_key = _BUTTON_COLOR_MAP[kind]
        style.configure(
            f"{kind.capitalize()}.TButton",
            background=c[bg_key],
            foreground=c[fg_key],
            font=settings.FONT_BOLD,
            padding=(14, 7),
            borderwidth=0,
        )
        style.map(
            f"{kind.capitalize()}.TButton",
            background=[("active", c["primary_dark"] if kind == "primary"
                         else c[bg_key]),
                        ("disabled", c["bg"])],
            foreground=[("disabled", c["disabled"])],
        )

    # ---------- Entries / Combobox ----------
    style.configure(
        "TEntry",
        fieldbackground=c["surface"],
        foreground=c["text"],
        insertcolor=c["text"],
        bordercolor=c["border"],
        lightcolor=c["border"],
        darkcolor=c["border"],
        padding=5,
    )
    style.configure(
        "TCombobox",
        fieldbackground=c["surface"],
        background=c["surface_alt"],
        foreground=c["text"],
        arrowcolor=c["text"],
        bordercolor=c["border"],
        padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", c["surface"])],
        selectbackground=[("readonly", c["selection"])],
        selectforeground=[("readonly", c["text"])],
    )
    # قائمة إسقاط الـ Combobox (ألوان Tk وليست ttk) — تُضبط في configure_root_defaults

    # ---------- LabelFrame ----------
    style.configure(
        "TLabelframe",
        background=c["bg"],
        bordercolor=c["border"],
        relief="groove",
    )
    style.configure(
        "TLabelframe.Label",
        background=c["bg"],
        foreground=c["primary"],
        font=settings.FONT_BOLD,
    )

    # ---------- Check / Radio ----------
    style.configure("TCheckbutton", background=c["bg"], foreground=c["text"],
                    font=settings.FONT_BASE)
    style.configure("TRadiobutton", background=c["bg"], foreground=c["text"],
                    font=settings.FONT_BASE)
    style.map("TCheckbutton", background=[("active", c["bg"])])

    # ---------- Scrollbars ----------
    for sb in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(sb, background=c["surface_alt"], troughcolor=c["bg"],
                        bordercolor=c["border"], arrowcolor=c["text_muted"])
        style.map(sb, background=[("active", c["selection"])])

    # ---------- Progressbar ----------
    style.configure("Green.Horizontal.TProgressbar", troughcolor=c["surface_alt"],
                    background=c["success"], bordercolor=c["border"], lightcolor=c["success"])

    # ---------- PanedWindow / Separator ----------
    style.configure("TPanedwindow", background=c["bg"])
    style.configure("TSeparator", background=c["border"])

    _log.info("تم تطبيق ستايل %s (%s)", STYLE_NAME,
              "ليلي" if settings.is_dark_mode() else "نهاري")
    return style


def setup_styles(root: tk.Tk) -> ttk.Style:
    """
    نقطة الدخول الرئيسية: تفعّل RTL + خيارات tk + ستايل ttk.

    تُستدعى مرة واحدة من FeedMixerERP.__init__ وبعد كل تبديل وضع لوني.
    """
    enable_rtl(root)
    configure_root_defaults(root)
    return apply_theme(root)


def styled_tree_tags(tree: ttk.Treeview) -> dict[str, Any]:
    """
    يطبّق وسوم الألوان القياسية على Treeview ويعيدها للاستخدام في التبويبات:
        even/odd (تظليل صفوف)، danger/warning/success/muted (نص ملوّن).
    """
    c = settings.COLORS
    tags = {
        "even": {"background": c["surface"]},
        "odd": {"background": c["stripe"]},
        "danger": {"foreground": c["danger"]},
        "warning": {"foreground": c["warning"]},
        "success": {"foreground": c["success"]},
        "muted": {"foreground": c["text_muted"]},
        "bold": {"font": settings.FONT_BOLD},
    }
    for name, opts in tags.items():
        tree.tag_configure(name, **opts)
    return tags
