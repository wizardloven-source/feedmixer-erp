"""
test_utils
----------
اختبارات وحدة لطبقة الأدوات المشتركة core/utils.py:
    - calc_billable_tons : قاعدة "كل 500 كغ = 0.5 طن" (تقريب لأقرب نصف طن).
    - safe_eval_math     : تقييم آمن للتعبيرات الحسابية.
    - material_kg_price  : سعر الكيلو حسب نوع الوحدة (ton/kg/fixed).
    - أدوات مساعدة       : normalize_digits / safe_float / round_money / month_bounds.

التشغيل:
    cd mixer_erp && python -m unittest tests.test_utils -v
"""

from __future__ import annotations

import unittest

from core.utils import (
    calc_billable_tons,
    material_kg_price,
    month_bounds,
    normalize_digits,
    round_money,
    safe_eval_math,
    safe_float,
)


class TestCalcBillableTons(unittest.TestCase):
    """القاعدة المعتمدة: int((kg + 249) / 500) * 0.5"""

    def test_exact_half_steps(self) -> None:
        self.assertEqual(calc_billable_tons(500), 0.5)
        self.assertEqual(calc_billable_tons(1000), 1.0)
        self.assertEqual(calc_billable_tons(1500), 1.5)
        self.assertEqual(calc_billable_tons(2000), 2.0)
        self.assertEqual(calc_billable_tons(10000), 10.0)

    def test_rounding_boundary(self) -> None:
        # التقريب لأقرب نصف طن حسب الصيغة المعتمدة int((kg+249)/500)*0.5
        self.assertEqual(calc_billable_tons(250), 0.0)
        self.assertEqual(calc_billable_tons(251), 0.5)
        self.assertEqual(calc_billable_tons(749), 0.5)
        self.assertEqual(calc_billable_tons(750), 0.5)   # الحد الفاصل (تحت)
        self.assertEqual(calc_billable_tons(751), 1.0)   # يتجاوز الحد -> طن
        self.assertEqual(calc_billable_tons(1249), 1.0)
        self.assertEqual(calc_billable_tons(1251), 1.5)

    def test_invalid_inputs(self) -> None:
        for value in (None, "", "abc", -100, 0):
            with self.subTest(value=value):
                self.assertEqual(calc_billable_tons(value), 0.0)

    def test_string_input(self) -> None:
        self.assertEqual(calc_billable_tons("2000"), 2.0)


class TestSafeEvalMath(unittest.TestCase):
    """تقييم تعبيرات آمنة بدون eval."""

    def test_basic_arithmetic(self) -> None:
        self.assertEqual(safe_eval_math("3*500+200"), 1700.0)
        self.assertEqual(safe_eval_math("(10+5)/3"), 5.0)
        self.assertEqual(safe_eval_math("2 ** 10"), 1024.0)
        self.assertEqual(safe_eval_math("-5+2"), -3.0)

    def test_plain_numbers(self) -> None:
        self.assertEqual(safe_eval_math("123.5"), 123.5)
        self.assertEqual(safe_eval_math(42), 42.0)

    def test_rejects_names_and_calls(self) -> None:
        # لا يُسمح بالأسماء أو استدعاء الدوال (حماية من الحقن)
        self.assertEqual(safe_eval_math("__import__('os')"), 0.0)
        self.assertEqual(safe_eval_math("open('x')"), 0.0)
        self.assertEqual(safe_eval_math("a+b"), 0.0)

    def test_rejects_overflow_exponent(self) -> None:
        self.assertEqual(safe_eval_math("9" * 5000), 0.0)

    def test_empty_and_garbage(self) -> None:
        self.assertEqual(safe_eval_math(""), 0.0)
        self.assertEqual(safe_eval_math(None), 0.0)
        self.assertEqual(safe_eval_math("3 +"), 0.0)
        self.assertEqual(safe_eval_math("1/0"), 0.0)


class TestMaterialKgPrice(unittest.TestCase):
    """سعر الكيلو: ton=(base+handling+loss)/1000 ، kg=المجموع ، fixed=base."""

    def test_ton_unit(self) -> None:
        mat = {"base_price": 5000, "handling_fee": 300, "loss_fee": 200,
               "unit_type": "ton"}
        self.assertAlmostEqual(material_kg_price(mat), 5.5)

    def test_kg_unit(self) -> None:
        mat = {"base_price": 12, "handling_fee": 1, "loss_fee": 0.5,
               "unit_type": "kg"}
        self.assertAlmostEqual(material_kg_price(mat), 13.5)

    def test_fixed_unit_ignores_fees(self) -> None:
        mat = {"base_price": 800, "handling_fee": 100, "loss_fee": 50,
               "unit_type": "fixed"}
        self.assertEqual(material_kg_price(mat), 800.0)

    def test_missing_material(self) -> None:
        self.assertEqual(material_kg_price(None), 0.0)
        self.assertEqual(material_kg_price({}), 0.0)


class TestHelpers(unittest.TestCase):
    """أدوات نصية ورقمية سريعة."""

    def test_normalize_digits_arabic(self) -> None:
        self.assertEqual(normalize_digits("١٢٣٤٫٥"), "1234.5")
        # الأرقام الفارسية (U+06F0..U+06F9) خارج نطاق التحويل المعتمد
        self.assertEqual(normalize_digits("۵۷"), "۵۷")

    def test_safe_float(self) -> None:
        self.assertEqual(safe_float("12.5"), 12.5)
        self.assertEqual(safe_float("abc", 9.0), 9.0)
        self.assertEqual(safe_float(None, 1.0), 1.0)

    def test_round_money(self) -> None:
        self.assertEqual(round_money(10.005), 10.01)
        self.assertEqual(round_money(7.1234), 7.12)

    def test_month_bounds(self) -> None:
        self.assertEqual(month_bounds("2026-02"), ("2026-02-01", "2026-02-28"))
        self.assertEqual(month_bounds("2024-02"), ("2024-02-01", "2024-02-29"))
        self.assertEqual(month_bounds("2026-12"), ("2026-12-01", "2026-12-31"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
