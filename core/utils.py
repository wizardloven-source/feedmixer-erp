"""
core/utils.py
-------------
أدوات مساعدة عامة لا تعتمد على الواجهة:

- safe_eval_math : حساب تعبير رياضي بأمان (بدون eval) لدعم حقول الحساب السريع.
- calc_billable_tons : تحويل الوزن (كغ) إلى أنصاف أطنان قابلة للفوترة.
- material_kg_price : سعر الكيلوغرام للمادة حسب نوع وحدتها.
- أدوات أرقام ونصوص وتواريخ وتنسيق مبالغ.
- Toast : إشعار عائم (Toplevel) يظهر أسفل يمين النافذة ثم يتلاشى.
- open_with_default_app : فتح ملف HTML / CSV في البرنامج الافتراضي.
"""

from __future__ import annotations

import ast
import math
import os
import subprocess
import sys
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Mapping

from config import settings

if TYPE_CHECKING:  # الاستيراد لأغراض تلميحات الأنواع فقط
    import tkinter as tk
else:
    try:  # استيراد آمن: بيئات الاختبار/الخادم قد لا تحتوي على Tk
        import tkinter as tk
    except Exception:  # noqa: BLE001 - ImportError أو غياب libtk
        tk = None  # type: ignore[assignment]
from core.logger import get_logger

_log = get_logger("mixer.utils")

# ============================================================
# 0) العملة الافتراضية (الدولار)
# ============================================================

DEFAULT_CURRENCY: str = "$"


# ============================================================
# 1) الأرقام والنصوص
# ============================================================

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text: str) -> str:
    """يحوّل الأرقام العربية-الهندية إلى لاتينية ويزيل محددات الآلاف العربية."""
    return (
        str(text)
        .translate(_ARABIC_DIGITS)
        .replace("٫", ".")
        .replace("٬", "")
        .replace("\u200f", "")
        .replace("\u200e", "")
    )


def safe_float(value: Any, default: float = 0.0) -> float:
    """يحوّل أي قيمة إلى float بأمان (يرجع default عند الفشل)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    try:
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            text = normalize_digits(str(value)).strip().replace(",", "")
            if not text:
                return default
            result = float(text)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """يحوّل أي قيمة إلى int بأمان."""
    try:
        return int(round(safe_float(value, float(default))))
    except (TypeError, ValueError):
        return default


def clamp(value: float, minimum: float, maximum: float) -> float:
    """يحصر قيمة بين حدّين."""
    return max(minimum, min(maximum, value))


def round_money(value: float) -> float:
    """تقريب المبالغ المالية إلى منزلتين."""
    return round(safe_float(value), settings.ROUND_MONEY)


def round_qty(value: float) -> float:
    """تقريب الكميات إلى 3 منازل."""
    return round(safe_float(value), settings.ROUND_QTY)


def format_money(value: float, currency: str | None = None) -> str:
    """
    تنسيق مبلغ مالي بالدولار (الرمز قبل الرقم — العُرف الدولي).
    مثال: $1,234.56
    """
    symbol = DEFAULT_CURRENCY if currency is None else str(currency)
    return f"{symbol}{safe_float(value):,.2f}"


def format_money_after(value: float, currency: str | None = None) -> str:
    """
    تنسيق مبلغ برمز بعد الرقم (للعملات العربية إن لزم).
    مثال: 1,234.56 $
    """
    symbol = DEFAULT_CURRENCY if currency is None else str(currency)
    return f"{safe_float(value):,.2f} {symbol}"


def format_number(value: float, decimals: int = 2) -> str:
    """تنسيق رقم بفواصل الآلاف."""
    return f"{safe_float(value):,.{max(0, decimals)}f}"


def format_tons(qty_ton: float) -> str:
    """تنسيق كمية بالطن مع وحدة القياس."""
    return f"{safe_float(qty_ton):,.3f} طن"


def truncate(text: Any, length: int = 60) -> str:
    """يقصّ نصاً طويلاً مع علامة حذف."""
    value = str(text or "")
    return value if len(value) <= length else value[: max(0, length - 1)] + "…"


# ============================================================
# 2) حساب آمن للتعبيرات الرياضية
# ============================================================

_MAX_EXPR_LEN = 120
_MAX_POW_EXP = 12
_MAX_ABS_RESULT = 1e12

_ALLOWED_BINOPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


def _eval_node(node: ast.AST, depth: int = 0) -> float:
    """تقييم عقدة AST مسموحة فقط (بدون أسماء أو نداءات دوال)."""
    if depth > 20:
        raise ValueError("تعبير متشعب أكثر من اللازم")
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("قيمة غير رقمية")
        return float(node.value)
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ValueError("عملية غير مسموحة")
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        elif isinstance(node.op, ast.Div):
            result = left / right
        elif isinstance(node.op, ast.FloorDiv):
            result = left // right
        elif isinstance(node.op, ast.Mod):
            result = left % right
        else:  # ast.Pow
            if abs(right) > _MAX_POW_EXP or abs(left) > 1e6:
                raise ValueError("أس كبير غير مسموح")
            result = left**right
        if not math.isfinite(result):
            raise ValueError("نتيجة غير منتهية")
        return float(result)
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARY):
            raise ValueError("عملية أحادية غير مسموحة")
        operand = _eval_node(node.operand, depth + 1)
        return -operand if isinstance(node.op, ast.USub) else operand
    raise ValueError("عنصر غير مسموح في التعبير")


def safe_eval_math(expression: Any, default: float = 0.0) -> float:
    """
    يقيّم تعبيراً رياضياً بسيطاً بأمان: + - * / // % ** والأقواس فقط.

    >>> safe_eval_math("2+3*4")
    14.0
    >>> safe_eval_math("abc")
    0.0
    """
    if expression is None:
        return default
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return float(expression)
    try:
        text = normalize_digits(str(expression)).strip()
        if not text:
            return default
        text = text.replace("×", "*").replace("÷", "/").replace("^", "**").replace("،", "")
        if len(text) > _MAX_EXPR_LEN:
            return default
        tree = ast.parse(text, mode="eval")
        value = _eval_node(tree.body)
        if not math.isfinite(value) or abs(value) > _MAX_ABS_RESULT:
            return default
        return float(value)
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError, OverflowError):
        return default
    except Exception as exc:  # noqa: BLE001 - لا يجب أن يسقط الإدخال التطبيق
        _log.debug("safe_eval_math(%r) failed: %s", expression, exc)
        return default


# ============================================================
# 3) قواعد الحساب المحاسبي
# ============================================================

def calc_billable_tons(weight_kg: float | str | None) -> float:
    """
    يحوّل الوزن بالكيلوغرام إلى أنصاف أطنان قابلة للفوترة.

    الصيغة المعتمدة (حسب مواصفات النظام):
        int((kg + 249) / 500) * 0.5

    أمثلة:
        500  -> 0.5
        1000 -> 1.0
        2000 -> 2.0
        250  -> 0.0
        251  -> 0.5
    """
    kg = safe_float(weight_kg, 0.0)
    if kg <= 0:
        return 0.0
    return int((kg + 249) / 500) * 0.5


def material_kg_price(material: Mapping[str, Any] | None) -> float:
    """
    سعر الكيلوغرام الواحد من المادة (شامل العتالة والهدر حسب الوحدة):
        ton   : (base + handling + loss) / 1000
        kg    : base + handling + loss
        fixed : base
    """
    if not material:
        return 0.0
    base = safe_float(material.get("base_price"))
    handling = safe_float(material.get("handling_fee"))
    loss = safe_float(material.get("loss_fee"))
    unit = str(material.get("unit_type", "ton"))
    if unit == "ton":
        return (base + handling + loss) / settings.KG_PER_TON
    if unit == "kg":
        return base + handling + loss
    return base


def tons_to_kg(qty_ton: float) -> float:
    """طن -> كغ."""
    return safe_float(qty_ton) * settings.KG_PER_TON


def kg_to_tons(qty_kg: float) -> float:
    """كغ -> طن."""
    return safe_float(qty_kg) / settings.KG_PER_TON


# ============================================================
# 4) التواريخ
# ============================================================

def today_str() -> str:
    """تاريخ اليوم بصيغة YYYY-MM-DD."""
    return date.today().strftime("%Y-%m-%d")


def now_str() -> str:
    """التاريخ والوقت الحاليان."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_month() -> str:
    """الشهر الحالي بصيغة YYYY-MM."""
    return date.today().strftime("%Y-%m")


def month_bounds(year_month: str) -> tuple[str, str]:
    """
    يحوّل 'YYYY-MM' إلى (أول يوم، آخر يوم) بصيغة ISO.
    يرجع حدود الشهر الحالي عند إدخال غير صالح.
    """
    try:
        year, month = (int(part) for part in str(year_month).split("-")[:2])
        first = date(year, month, 1)
        last = date(year + (month == 12), (month % 12) + 1, 1)
        return first.isoformat(), date.fromordinal(last.toordinal() - 1).isoformat()
    except Exception:  # noqa: BLE001
        first = date.today().replace(day=1)
        last = date(first.year + (first.month == 12), (first.month % 12) + 1, 1)
        return first.isoformat(), date.fromordinal(last.toordinal() - 1).isoformat()


def month_label(year_month: str) -> str:
    """وصف عربي لشهر: '2026-11' -> 'نوفمبر 2026'."""
    months = (
        "يناير",
        "فبراير",
        "مارس",
        "أبريل",
        "مايو",
        "يونيو",
        "يوليو",
        "أغسطس",
        "سبتمبر",
        "أكتوبر",
        "نوفمبر",
        "ديسمبر",
    )
    try:
        year, month = (int(part) for part in str(year_month).split("-")[:2])
        return f"{months[month - 1]} {year}"
    except Exception:  # noqa: BLE001
        return str(year_month)


# ============================================================
# 5) الملفات
# ============================================================

def ensure_dir(path: str | os.PathLike[str]) -> str:
    """ينشئ مجلداً إن لم يكن موجوداً ويعيد مساره كنص."""
    target = str(path)
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        _log.warning("تعذر إنشاء المجلد %s: %s", target, exc)
    return target


def unique_file_path(directory: str | os.PathLike[str], prefix: str, extension: str) -> str:
    """يولّد مسار ملف غير موجود: prefix_YYYYmmdd_HHMMSS.ext (مع لاحقة عند التكرار)."""
    ensure_dir(directory)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = extension if extension.startswith(".") else f".{extension}"
    candidate = os.path.join(str(directory), f"{prefix}_{stamp}{ext}")
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(
            str(directory), f"{prefix}_{stamp}_{counter}{ext}"
        )
        counter += 1
    return candidate


def open_with_default_app(path: str | os.PathLike[str]) -> bool:
    """يفتح ملفاً بالبرنامج الافتراضي في النظام. يعيد نجاح المحاولة."""
    target = os.path.abspath(str(path))
    if not os.path.exists(target):
        _log.warning("الملف غير موجود: %s", target)
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("تعذر فتح الملف %s: %s", target, exc)
        return False


# ============================================================
# 6) Toast - إشعار عائم
# ============================================================

_TOAST_PALETTE = {
    "success": "success",
    "error": "danger",
    "danger": "danger",
    "warning": "warning",
    "info": "info",
}


class Toast:
    """
    إشعار عائم غير معطّل (overrideredirect) يظهر أسفل يمين النافذة الأب،
    يبقى مدة قصيرة ثم يتلاشى تدريجياً. لا يرفع استثناء عند فشل العرض.
    """

    _active: ClassVar[list["Toast"]] = []

    def __init__(
        self,
        parent: tk.Misc,
        message: str,
        kind: str = "info",
        duration: int = 2600,
        width: int = 340,
    ) -> None:
        self._parent = parent
        self._width = max(220, int(width))
        self._duration = max(700, int(duration))
        self._closed = False
        self._top: tk.Toplevel | None = None
        self._message = str(message)

        try:
            colors = settings.COLORS
            bg = colors[_TOAST_PALETTE.get(kind, "info")]
            top = tk.Toplevel(parent)
            top.withdraw()
            top.overrideredirect(True)
            try:
                top.attributes("-topmost", True)
            except tk.TclError:
                pass
            top.configure(bg=bg, bd=1, relief="solid")

            label = tk.Label(
                top,
                text=self._message,
                bg=bg,
                fg="#ffffff",
                font=settings.FONT_BOLD,
                justify="right",
                anchor="e",
                wraplength=self._width - 36,
                padx=16,
                pady=12,
            )
            label.pack(fill="both", expand=True)

            top.update_idletasks()
            height = max(52, top.winfo_reqheight())
            x, y = self._position(height)
            top.geometry(f"{self._width}x{height}+{x}+{y}")
            top.deiconify()
            top.lift()

            self._top = top
            Toast._active.append(self)
            top.after(self._duration, self._start_fade)
        except Exception as exc:  # noqa: BLE001
            _log.debug("تعذر عرض Toast: %s", exc)
            self._top = None

    # --------------------------------------------------------
    def _position(self, height: int) -> tuple[int, int]:
        """يحسب مكان الظهور أسفل يمين النافذة الأب مع تكديس الإشعارات."""
        try:
            self._parent.update_idletasks()
            px = self._parent.winfo_rootx()
            py = self._parent.winfo_rooty()
            pw = self._parent.winfo_width()
            ph = self._parent.winfo_height()
        except tk.TclError:
            px = py = 0
            pw = self._parent.winfo_screenwidth() if hasattr(self._parent, "winfo_screenwidth") else 1280
            ph = 800
        if pw <= 1 or ph <= 1:
            pw, ph = 1280, 800

        margin = 24
        x = px + pw - self._width - margin
        slot = max(0, len(Toast._active))
        y = py + ph - height - 64 - slot * (height + 10)
        y = max(py + 10, y)
        x = max(px + 10, x)
        return int(x), int(y)

    def _start_fade(self) -> None:
        """يبدأ تلاشي الإشعار بعد انتهاء المدة."""
        self._fade(0.95)

    def _fade(self, alpha: float) -> None:
        if self._closed:
            return
        try:
            if self._top is None or not self._top.winfo_exists():
                self._closed = True
                return
            next_alpha = alpha - 0.12
            if next_alpha <= 0.05:
                self.destroy()
                return
            self._top.attributes("-alpha", next_alpha)
            self._top.after(30, lambda: self._fade(next_alpha))
        except tk.TclError:
            self._closed = True

    def destroy(self) -> None:
        """يغلق الإشعار فوراً بأمان."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._top is not None and self._top.winfo_exists():
                self._top.destroy()
        except tk.TclError:
            pass
        finally:
            self._top = None
            if self in Toast._active:
                Toast._active.remove(self)


def show_toast(
    parent: tk.Misc,
    message: str,
    kind: str = "info",
    duration: int = 2600,
) -> Toast | None:
    """اختصار لإنشاء Toast وإرجاعه (أو None عند الفشل)."""
    try:
        return Toast(parent, message, kind=kind, duration=duration)
    except Exception as exc:  # noqa: BLE001
        _log.warning("show_toast failed: %s", exc)
        return None