"""
test_validators
---------------
اختبارات وحدة لطبقة التحقق core/validators.py:
    - validate_date: صيغ متعددة → ISO، ومدخلات خاطئة → ValidationError.
    - validate_username: تطبيع لحروف صغيرة + رفض ما يبدأ برقم.
    - validate_password: حد الطول + تطابق التأكيد.
    - validate_choice: القيمة ضمن القائمة أو ValidationError.

كل الدوال تُعيد القيمة مطبَّعة أو ترفع ValidationError (رسالة عربية).

التشغيل:
    cd /workspace && python -m unittest tests.test_validators -v
"""

from __future__ import annotations

import unittest

from core.validators import (
    ValidationError,
    validate_choice,
    validate_date,
    validate_password,
    validate_username,
)


class TestValidateDate(unittest.TestCase):
    """validate_date يقبل صيغاً متعددة ويعيد ISO دائماً."""

    def test_iso_passthrough(self) -> None:
        # تاريخ بصيغة ISO يبقى كما هو
        self.assertEqual(validate_date("2026-11-04"), "2026-11-04")

    def test_slash_dmy_normalized(self) -> None:
        # صيغة يوم/شهر/سنة تتحول إلى ISO
        self.assertEqual(validate_date("01/11/2026"), "2026-11-01")

    def test_invalid_raises(self) -> None:
        # نص غير قابل للتحليل → ValidationError برسالة عربية
        with self.assertRaises(ValidationError):
            validate_date("invalid")

    def test_empty_raises(self) -> None:
        # التاريخ الفارغ مرفوض صراحة
        with self.assertRaises(ValidationError):
            validate_date("", "تاريخ الخلطة")
        with self.assertRaises(ValidationError):
            validate_date(None)

    def test_dashed_dmy(self) -> None:
        # صيغة D-M-Y مقبولة أيضاً وتُطبَّع
        self.assertEqual(validate_date("1-11-2026"), "2026-11-01")


class TestValidateUsername(unittest.TestCase):
    """validate_username: حرف بادي إنجليزي، طول 3-32، ويُطبع lowercase."""

    def test_simple_ok(self) -> None:
        self.assertEqual(validate_username("admin"), "admin")

    def test_lowercased(self) -> None:
        # الأحرف الكبيرة تُطبع تلقائياً — مهم لتوحيد أسماء الدخول
        self.assertEqual(validate_username("Admin"), "admin")

    def test_starts_with_digit_rejected(self) -> None:
        # يجب أن يبدأ بحرف لا برقم
        with self.assertRaises(ValidationError):
            validate_username("1abc")

    def test_too_short_rejected(self) -> None:
        # أقل من 3 أحرف مرفوض
        with self.assertRaises(ValidationError):
            validate_username("ab")

    def test_empty_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            validate_username("")
        with self.assertRaises(ValidationError):
            validate_username(None)

    def test_allowed_symbols(self) -> None:
        # النقاط والشرطات السفلية مسموحة بعد الحرف الأول
        self.assertEqual(validate_username("user_name-1.x"), "user_name-1.x")


class TestValidatePassword(unittest.TestCase):
    """validate_password: حد أدنى 6، بلا مسافات، وتأكيد مطابق إن وُجد."""

    def test_too_short_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            validate_password("12345")  # 5 < الحد 6

    def test_min_length_ok(self) -> None:
        self.assertEqual(validate_password("123456"), "123456")

    def test_confirm_mismatch_rejected(self) -> None:
        # عدم تطابق الحقلين يرفض فوراً
        with self.assertRaises(ValidationError):
            validate_password("123456", confirm="654321")

    def test_confirm_match_ok(self) -> None:
        self.assertEqual(validate_password("secret99", confirm="secret99"), "secret99")

    def test_spaces_rejected(self) -> None:
        # كلمة المرور لا تحتمل فراغات
        with self.assertRaises(ValidationError):
            validate_password("with space here")

    def test_empty_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            validate_password("")


class TestValidateChoice(unittest.TestCase):
    """validate_choice: القيمة يجب أن تكون إحدى المسموحات."""

    def test_valid_choice(self) -> None:
        self.assertEqual(validate_choice("cash", ["cash", "transfer"], "الطريقة"), "cash")

    def test_invalid_choice_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            validate_choice("xyz", ["cash", "transfer"], "الطريقة")

    def test_tuple_choices_and_whitespace(self) -> None:
        # يقبل أي Sequence/Iterable ويطبّع المسافات الطرفية
        self.assertEqual(validate_choice(" paid ", ("unpaid", "partial", "paid")), "paid")

    def test_empty_value_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            validate_choice("", ("a", "b"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
