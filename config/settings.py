"""
config/settings.py
------------------
الإعدادات المركزية لـ FeedMixer ERP v3.0.

يحتوي هذا الملف على:
- مسارات المشروع (قاعدة البيانات، السجلات، التصدير، النسخ الاحتياطي).
- ثوابت التطبيق (الأدوار، حالات الدفع، وحدات القياس، الحدود).
- لوحات الألوان للوضعين النهاري والليلي + دالة التبديل.
- إعدادات الخطوط العربية.
- البيانات الافتراضية (مزارع / مواد / إعدادات).
- اكتشاف المكتبات الاختيارية: tkcalendar / matplotlib / openpyxl.

هذه الطبقة لا تستورد أي شيء من بقية المشروع (ورقة مستقلة)،
لذلك يمكن استيرادها من أي مكان دون مخاطر استيراد دوري.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

# ============================================================
# 1) هوية التطبيق
# ============================================================

APP_NAME: Final[str] = "FeedMixer ERP"
APP_VERSION: Final[str] = "3.0.0"
APP_TITLE: Final[str] = f"{APP_NAME} v{APP_VERSION}"
APP_VENDOR: Final[str] = "FeedMixer"

# ============================================================
# 2) المسارات
# ============================================================

BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent
STORAGE_DIR: Final[Path] = BASE_DIR / "storage"
LOG_DIR: Final[Path] = BASE_DIR / "logs"
EXPORT_DIR: Final[Path] = BASE_DIR / "exports"
PRINT_DIR: Final[Path] = BASE_DIR / "prints"
BACKUP_DIR: Final[Path] = STORAGE_DIR / "backups"

DB_PATH: Final[Path] = Path(
    os.environ.get("FEEDMIXER_DB", str(STORAGE_DIR / "feedmixer.db"))
)
LOG_FILE: Final[Path] = LOG_DIR / "app.log"
UI_STATE_FILE: Final[Path] = STORAGE_DIR / "ui_state.json"


def ensure_directories() -> None:
    """ينشئ كل المجلدات التي يحتاجها التطبيق عند التشغيل."""
    for folder in (STORAGE_DIR, LOG_DIR, EXPORT_DIR, PRINT_DIR, BACKUP_DIR):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            # لا نُسقط التطبيق بسبب صلاحيات مجلد فرعي
            continue


# ============================================================
# 3) النافذة الرئيسية
# ============================================================

DEFAULT_WINDOW_GEOMETRY: Final[str] = "1280x780"
DEFAULT_WINDOW_STATE: Final[str] = "zoomed"
MIN_WINDOW_WIDTH: Final[int] = 1100
MIN_WINDOW_HEIGHT: Final[int] = 660

# ============================================================
# 4) الخطوط
# ============================================================

FONT_FAMILY: Final[str] = "Segoe UI"
FONT_FAMILY_MONO: Final[str] = "Consolas"

FONT_SIZE_SMALL: Final[int] = 9
FONT_SIZE_NORMAL: Final[int] = 10
FONT_SIZE_MEDIUM: Final[int] = 11
FONT_SIZE_LARGE: Final[int] = 14
FONT_SIZE_TITLE: Final[int] = 18

FONT_BASE: Final[tuple[str, int]] = (FONT_FAMILY, FONT_SIZE_NORMAL)
FONT_SMALL: Final[tuple[str, int]] = (FONT_FAMILY, FONT_SIZE_SMALL)
FONT_MEDIUM: Final[tuple[str, int]] = (FONT_FAMILY, FONT_SIZE_MEDIUM)
FONT_LARGE_BOLD: Final[tuple[str, int, str]] = (FONT_FAMILY, FONT_SIZE_LARGE, "bold")
FONT_TITLE_BOLD: Final[tuple[str, int, str]] = (FONT_FAMILY, FONT_SIZE_TITLE, "bold")
FONT_BOLD: Final[tuple[str, int, str]] = (FONT_FAMILY, FONT_SIZE_NORMAL, "bold")

TREE_ROW_HEIGHT: Final[int] = 26

# ============================================================
# 5) الألوان (نهاري / ليلي)
# ============================================================

LIGHT_COLORS: Final[dict[str, str]] = {
    "bg": "#f4f6f9",
    "surface": "#ffffff",
    "surface_alt": "#eef2f7",
    "border": "#d7dee8",
    "text": "#1f2937",
    "text_muted": "#6b7280",
    "primary": "#1f6f4a",
    "primary_dark": "#17553a",
    "primary_light": "#e6f4ec",
    "accent": "#c98a16",
    "success": "#2e9e5b",
    "warning": "#d98324",
    "danger": "#c0392b",
    "info": "#2f6f9f",
    "header_bg": "#1f6f4a",
    "header_fg": "#ffffff",
    "selection": "#d7ead9",
    "stripe": "#f8fafc",
    "disabled": "#9aa5b1",
    "toast_bg": "#1f2937",
    "toast_fg": "#ffffff",
    "chart_grid": "#d7dee8",
}

DARK_COLORS: Final[dict[str, str]] = {
    "bg": "#111827",
    "surface": "#1b2433",
    "surface_alt": "#232f42",
    "border": "#334155",
    "text": "#e5e7eb",
    "text_muted": "#9ca3af",
    "primary": "#2e9e5b",
    "primary_dark": "#247a46",
    "primary_light": "#1f3a2b",
    "accent": "#e0a52e",
    "success": "#34d399",
    "warning": "#fbbf24",
    "danger": "#f87171",
    "info": "#60a5fa",
    "header_bg": "#16202e",
    "header_fg": "#e5e7eb",
    "selection": "#274536",
    "stripe": "#1f2a3a",
    "disabled": "#64748b",
    "toast_bg": "#e5e7eb",
    "toast_fg": "#111827",
    "chart_grid": "#334155",
}

# القاموس العام الذي تقرأ منه الواجهة (يُحدّث في مكانه عند تغيير الوضع)
COLORS: dict[str, str] = dict(LIGHT_COLORS)
_dark_mode: bool = False


def get_colors(dark: bool | None = None) -> dict[str, str]:
    """يعيد لوحة الألوان المطلوبة دون تغيير الوضع الحالي."""
    if dark is None:
        dark = _dark_mode
    return dict(DARK_COLORS if dark else LIGHT_COLORS)


def set_theme(dark: bool) -> None:
    """
    يبدّل الوضع اللوني العام ويُحدّث COLORS في مكانه،
    حتى تلتقط التبويبات المفتوحة القيم الجديدة عند إعادة الرسم.
    """
    global _dark_mode
    _dark_mode = bool(dark)
    COLORS.clear()
    COLORS.update(DARK_COLORS if _dark_mode else LIGHT_COLORS)


def is_dark_mode() -> bool:
    """هل الوضع الحالي ليلي؟"""
    return _dark_mode


# ============================================================
# 6) الأدوار والصلاحيات
# ============================================================

ROLE_ADMIN: Final[str] = "admin"
ROLE_OPERATOR: Final[str] = "operator"
ROLE_VIEWER: Final[str] = "viewer"

ROLES: Final[tuple[str, ...]] = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)
ROLE_LABELS: Final[dict[str, str]] = {
    ROLE_ADMIN: "مدير النظام",
    ROLE_OPERATOR: "مشغّل",
    ROLE_VIEWER: "مشاهد",
}

# ============================================================
# 7) وحدات المواد وحالات الدفع
# ============================================================

UNIT_TYPES: Final[tuple[str, ...]] = ("ton", "kg", "fixed")
UNIT_LABELS: Final[dict[str, str]] = {
    "ton": "طن",
    "kg": "كغ",
    "fixed": "سعر ثابت",
}

PAYMENT_STATUSES: Final[tuple[str, ...]] = ("unpaid", "partial", "paid")
PAYMENT_STATUS_LABELS: Final[dict[str, str]] = {
    "unpaid": "غير مدفوع",
    "partial": "مدفوع جزئياً",
    "paid": "مدفوع",
}

PAYMENT_METHODS: Final[tuple[str, ...]] = ("cash", "transfer", "cheque")
PAYMENT_METHOD_LABELS: Final[dict[str, str]] = {
    "cash": "نقدي",
    "transfer": "تحويل بنكي",
    "cheque": "شيك",
}

# ============================================================
# 8) ثوابت محاسبية ومخزنية
# ============================================================

KG_PER_TON: Final[int] = 1000
BILLABLE_TON_STEP_KG: Final[int] = 500
LOW_STOCK_THRESHOLD_TONS: Final[float] = 5.0
DEFAULT_TRANSPORT_FEE: Final[float] = 0.0
ROUND_MONEY: Final[int] = 2
ROUND_QTY: Final[int] = 3

# ============================================================
# 9) قيم الإعدادات الافتراضية
# ============================================================

DEFAULT_SETTINGS: Final[dict[str, tuple[float, str]]] = {
    "electricity_fee": (1.5, "أجرة الكهرباء (لكل خلطة)"),
    "labor_fee_per_ton": (2.868, "أجرة العمال لكل طن/نصف طن"),
    "theme_mode": (0.0, "الوضع اللوني: 0 نهاري / 1 ليلي"),
    "auto_update_price_from_purchase": (
        0.0,
        "تحديث سعر المادة تلقائياً من آخر توريد: 0 لا / 1 نعم",
    ),
}

# ============================================================
# 10) البيانات الافتراضية (seed)
# ============================================================

DEFAULT_FARMS: Final[list[dict[str, Any]]] = [
    {"name": "مزرعة النور", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة البركة", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة الأمل", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة الوفاء", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة الخير", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة السلام", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة الرحمة", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة الصفا", "transport_fee": 0.0, "phone": "", "notes": ""},
    {"name": "مزرعة الهدى", "transport_fee": 0.0, "phone": "", "notes": ""},
]

# (الاسم، السعر الأساسي/طن، العتالة، الهدر، نوع الوحدة)
DEFAULT_MATERIALS: Final[list[tuple[str, float, float, float, str]]] = [
    ("ذرة", 9800.0, 50.0, 20.0, "ton"),
    ("صويا", 17500.0, 60.0, 30.0, "ton"),
    ("طحن", 3600.0, 30.0, 10.0, "ton"),
    ("كسبة", 12000.0, 50.0, 20.0, "ton"),
    ("لحم", 9000.0, 40.0, 20.0, "ton"),
    ("رز", 7000.0, 40.0, 15.0, "ton"),
    ("معكرونة", 6500.0, 40.0, 15.0, "ton"),
    ("مونو كالسيوم", 15000.0, 30.0, 10.0, "ton"),
    ("بريمكس", 22000.0, 40.0, 10.0, "ton"),
    ("رمل", 800.0, 20.0, 5.0, "ton"),
    ("ملح", 1200.0, 20.0, 5.0, "ton"),
    ("nf", 30000.0, 30.0, 10.0, "ton"),
]

# ============================================================
# 11) المكتبات الاختيارية
# ============================================================

HAS_TKCALENDAR: bool = False
tkcalendar: Any = None
try:  # pragma: no cover - يعتمد على بيئة التشغيل
    import tkcalendar as _tkcalendar

    tkcalendar = _tkcalendar
    HAS_TKCALENDAR = True
except Exception:  # ImportError أو أي خطأ تهيئة
    tkcalendar = None
    HAS_TKCALENDAR = False

HAS_MATPLOTLIB: bool = False
matplotlib: Any = None
Figure: Any = None
try:  # pragma: no cover - يعتمد على بيئة التشغيل
    import matplotlib as _matplotlib
    from matplotlib.figure import Figure as _Figure

    matplotlib = _matplotlib
    Figure = _Figure
    HAS_MATPLOTLIB = True
except Exception:
    matplotlib = None
    Figure = None
    HAS_MATPLOTLIB = False

HAS_OPENPYXL: bool = False
openpyxl: Any = None
try:  # pragma: no cover - يعتمد على بيئة التشغيل
    import openpyxl as _openpyxl

    openpyxl = _openpyxl
    HAS_OPENPYXL = True
except Exception:
    openpyxl = None
    HAS_OPENPYXL = False


def describe_optional_libraries() -> dict[str, bool]:
    """يعيد حالة المكتبات الاختيارية (تظهر في تبويب الإعدادات/حول)."""
    return {
        "tkcalendar": HAS_TKCALENDAR,
        "matplotlib": HAS_MATPLOTLIB,
        "openpyxl": HAS_OPENPYXL,
    }
