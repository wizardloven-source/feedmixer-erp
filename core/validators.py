"""
core/validators.py
------------------
التحقق من صحة المدخلات قبل الوصول إلى قاعدة البيانات.

الأسلوب: كل دالة تُعيد القيمة بعد التطبيع (normalized)، أو ترفع
ValidationError برسالة عربية جاهزة للعرض في الواجهة.

أمثلة:
    try:
        date_text = validate_date(entry.get(), "تاريخ الخلطة")
    except ValidationError as exc:
        show_toast(self, str(exc), "error")
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Sequence

from core.utils import normalize_digits, safe_float

MIN_PASSWORD_LENGTH = 6
MAX_NAME_LENGTH = 80
MAX_NOTES_LENGTH = 500

_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
)

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{2,31}$")
_PHONE_RE = re.compile(r"^[0-9+\-\s()]{0,20}$")


class ValidationError(ValueError):
    """خطأ تحقق يحمل رسالة عربية قابلة للعرض مباشرة للمستخدم."""


# ============================================================
# التواريخ
# ============================================================

def validate_date(value: str | None, field: str = "التاريخ") -> str:
    """
    يتحقق من تاريخ ويعيده بصيغة ISO (YYYY-MM-DD).
    يقبل 2026-11-01 و 01/11/2026 و 1-11-2026 وغيرها.
    """
    text = normalize_digits(str(value or "")).strip()
    if not text:
        raise ValidationError(f"{field} مطلوب")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValidationError(f"{field} غير صالح، استخدم الصيغة YYYY-MM-DD")


def validate_month(value: str | None, field: str = "الشهر") -> str:
    """يتحقق من 'YYYY-MM' ويعيده."""
    text = normalize_digits(str(value or "")).strip()
    if not re.fullmatch(r"\d{4}-\d{1,2}", text):
        raise ValidationError(f"{field} غير صالح، استخدم الصيغة YYYY-MM")
    year, month = (int(part) for part in text.split("-"))
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        raise ValidationError(f"{field} خارج النطاق المسموح")
    return f"{year:04d}-{month:02d}"


def validate_year(value: str | int | None, field: str = "السنة") -> int:
    """يتحقق من سنة ميلادية."""
    try:
        year = int(normalize_digits(str(value or "")).strip())
    except ValueError as exc:
        raise ValidationError(f"{field} يجب أن تكون رقماً") from exc
    if not 2000 <= year <= 2100:
        raise ValidationError(f"{field} خارج النطاق المسموح (2000-2100)")
    return year


# ============================================================
# المستخدمون
# ============================================================

def validate_username(username: str | None) -> str:
    """
    اسم مستخدم لاتيني: حرف في البداية ثم 2-31 حرفاً/رقماً/._-
    يُعاد بأحرف صغيرة.
    """
    text = str(username or "").strip().lower()
    if not text:
        raise ValidationError("اسم المستخدم مطلوب")
    if not _USERNAME_RE.fullmatch(text):
        raise ValidationError(
            "اسم المستخدم يجب أن يبدأ بحرف إنجليزي ويحتوي 3-32 حرفاً/رقماً فقط"
        )
    return text


def validate_password(
    password: str | None,
    confirm: str | None = None,
    min_length: int = MIN_PASSWORD_LENGTH,
) -> str:
    """كلمة مرور بحد أدنى للطول، بلا فراغات، مع تأكيد مطابق إن أُرسل."""
    text = str(password or "")
    if not text:
        raise ValidationError("كلمة المرور مطلوبة")
    if len(text) < min_length:
        raise ValidationError(f"كلمة المرور يجب ألا تقل عن {min_length} أحرف")
    if len(text) > 128:
        raise ValidationError("كلمة المرور طويلة جداً (128 حرفاً كحد أقصى)")
    if any(ch.isspace() for ch in text):
        raise ValidationError("كلمة المرور يجب ألا تحتوي على مسافات")
    if confirm is not None and text != str(confirm):
        raise ValidationError("كلمتا المرور غير متطابقتين")
    return text


def validate_full_name(name: str | None, field: str = "الاسم الكامل") -> str:
    """اسم شخص/جهة: مطلوب بطول 2-80."""
    text = " ".join(str(name or "").split())
    if len(text) < 2:
        raise ValidationError(f"{field} مطلوب (حرفان على الأقل)")
    if len(text) > MAX_NAME_LENGTH:
        raise ValidationError(f"{field} طويل جداً (الحد {MAX_NAME_LENGTH} حرفاً)")
    return text


# ============================================================
# الأسماء والأرقام
# ============================================================

def validate_name(
    value: str | None,
    field: str = "الاسم",
    min_length: int = 2,
    max_length: int = MAX_NAME_LENGTH,
) -> str:
    """اسم كيان (مزرعة/مادة/وصفة): يوحّد المسافات ويتحقق من الطول."""
    text = " ".join(str(value or "").split())
    if len(text) < min_length:
        raise ValidationError(f"{field} مطلوب (حرفان على الأقل)")
    if len(text) > max_length:
        raise ValidationError(f"{field} طويل جداً (الحد {max_length} حرفاً)")
    return text


def validate_notes(notes: str | None, field: str = "الملاحظات") -> str:
    """ملاحظات اختيارية بحد أقصى 500 حرف."""
    text = str(notes or "").strip()
    if len(text) > MAX_NOTES_LENGTH:
        raise ValidationError(f"{field} طويلة جداً (الحد {MAX_NOTES_LENGTH} حرفاً)")
    return text


def validate_phone(phone: str | None) -> str:
    """هاتف اختياري: أرقام و + - ( ) ومسافات، بحد 20 خانة."""
    text = normalize_digits(str(phone or "")).strip()
    if text and not _PHONE_RE.fullmatch(text):
        raise ValidationError("رقم الهاتف يحتوي رموزاً غير مسموحة")
    return text


def validate_number(
    value: str | float | None,
    field: str = "القيمة",
    minimum: float | None = None,
    maximum: float | None = None,
    allow_zero: bool = True,
) -> float:
    """رقم عشري ضمن نطاق اختياري."""
    number = safe_float(value, default=float("nan"))
    if number != number:  # NaN -> إدخال غير رقمي
        raise ValidationError(f"{field} يجب أن يكون رقماً")
    if not allow_zero and number == 0:
        raise ValidationError(f"{field} يجب أن يكون أكبر من صفر")
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} يجب ألا يقل عن {minimum:g}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field} يجب ألا يزيد عن {maximum:g}")
    return float(number)


def validate_quantity(value: str | float | None, field: str = "الكمية") -> float:
    """كمية موجبة (> 0) بحد أقصى معقول."""
    return validate_number(value, field, minimum=0.001, maximum=1_000_000, allow_zero=False)


def validate_money(
    value: str | float | None,
    field: str = "المبلغ",
    allow_zero: bool = True,
    maximum: float = 1_000_000_000,
) -> float:
    """مبلغ مالي غير سالب."""
    return validate_number(value, field, minimum=0.0, maximum=maximum, allow_zero=allow_zero)


def validate_int(
    value: str | int | None,
    field: str = "العدد",
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """عدد صحيح ضمن نطاق اختياري."""
    try:
        number = int(float(normalize_digits(str(value or "")).strip()))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} يجب أن يكون عدداً صحيحاً") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} يجب ألا يقل عن {minimum}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field} يجب ألا يزيد عن {maximum}")
    return number


# ============================================================
# الاختيارات من القوائم
# ============================================================

def validate_choice(
    value: str | None,
    choices: Sequence[str] | Iterable[str],
    field: str = "الاختيار",
) -> str:
    """يتأكد أن القيمة إحدى القيم المسموحة."""
    text = str(value or "").strip()
    allowed = tuple(choices)
    if text not in allowed:
        raise ValidationError(f"{field} غير صالح (المسموح: {'، '.join(allowed)})")
    return text
