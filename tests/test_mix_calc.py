"""
test_mix_calc
-------------
اختبار وحدة يفرض التطابق الحرفي بين:
    services/mix_service.calculate_mix      (المعاينة في الواجهة)
    data/invoices_repo._compute_invoice_totals  (ما يُحفظ في قاعدة البيانات)

القاعدة المعتمدة (Single Source of Truth):
    feed_cost      = Σ (qty_kg × unit_price)
    elec_cost      = electricity_fee                       ← قيمة ثابتة لكل خلطة
    labor_cost     = billable_tons × labor_fee_per_ton     ← متغيرة مع الوزن
    transport_cost = farm.transport_fee                    ← قيمة ثابتة لكل فاتورة
    total_cost     = feed + elec + labor + transport
    mixer_net_cost = total_cost إلا عند التعديل اليدوي

التشغيل:
    cd /workspace && python -m unittest tests.test_mix_calc -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import cache
from data.connection import set_database_path
from data import farms_repo, materials_repo
from data.invoices_repo import _compute_invoice_totals
from data.settings_repo import set_setting
from services.mix_service import calculate_mix


class TestMixCalcConsistency(unittest.TestCase):
    """تطابق calculate_mix مع _compute_invoice_totals على تركيبات متعددة."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.TemporaryDirectory(prefix="mixerp_test_")
        set_database_path(str(Path(cls.tmpdir.name) / "test.db"))
        from data.schema import init_database
        init_database()
        set_setting("electricity_fee", 1.5, "أجرة الكهرباء (لكل خلطة)")
        set_setting("labor_fee_per_ton", 2.868, "أجرة العمال لكل طن/نصف طن")
        farms_repo.add_farm("مزرعة-أ", transport_fee=0.0)
        farms_repo.add_farm("مزرعة-ب", transport_fee=75.0)
        materials_repo.add_material("ذرة", base_price=5000.0, unit_type="ton")
        cache.invalidate_all()

    @classmethod
    def tearDownClass(cls) -> None:
        cache.invalidate_all()
        set_database_path(None)
        cls.tmpdir.cleanup()

    def setUp(self) -> None:
        cache.invalidate_all()

    # ------------------------------------------------------------
    # حالات التطابق (3 تركيبات مختلفة على الأقل)
    # ------------------------------------------------------------

    def _assert_consistent(self, items: list[dict], farm: str,
                           elec: float, labor: float) -> dict:
        c = calculate_mix(items, farm)
        t = _compute_invoice_totals(items, farm, elec, labor)
        self.assertAlmostEqual(c["feed_cost"], t["feed_cost"], places=2)
        self.assertAlmostEqual(c["elec_cost"], t["elec_fee"], places=2)
        self.assertAlmostEqual(c["labor_cost"], t["labor_fee"], places=2)
        self.assertAlmostEqual(c["transport_cost"], t["transport_fee"], places=2)
        self.assertAlmostEqual(c["total_cost"], t["total_cost"], places=2)
        self.assertAlmostEqual(c["billable_tons"], t["billable_tons"], places=6)
        self.assertAlmostEqual(c["total_weight_kg"], t["total_weight"], places=3)
        return c

    def test_case1_zero_transport(self) -> None:
        """وزن 500 كغ بسعر 5/كغ — كهرباء ثابتة 1.5 وعمال 2.868/طن."""
        items = [{"material_name": "ذرة", "qty_kg": 500.0, "unit_price": 5.0}]
        c = self._assert_consistent(items, "مزرعة-أ", 1.5, 2.868)
        # القيم المتوقعة محسوبة يدوياً حسب القاعدة المعتمدة
        self.assertAlmostEqual(c["feed_cost"], 2500.0, places=2)
        self.assertAlmostEqual(c["elec_cost"], 1.5, places=2)       # ثابتة
        self.assertAlmostEqual(c["labor_cost"], 1.43, places=2)     # 0.5 × 2.868
        self.assertAlmostEqual(c["transport_cost"], 0.0, places=2)
        self.assertAlmostEqual(c["total_cost"], 2502.93, places=2)

    def test_case2_with_transport(self) -> None:
        """وزن 1000 كغ بمزرعة نقلها 75 — النقل ثابت لا يتضاعف بالوزن."""
        items = [
            {"material_name": "ذرة", "qty_kg": 700.0, "unit_price": 5.0},
            {"material_name": "ذرة", "qty_kg": 300.0, "unit_price": 4.0},
        ]
        c = self._assert_consistent(items, "مزرعة-ب", 1.5, 2.868)
        self.assertAlmostEqual(c["feed_cost"], 4700.0, places=2)
        self.assertAlmostEqual(c["elec_cost"], 1.5, places=2)
        self.assertAlmostEqual(c["labor_cost"], 2.87, places=2)     # 1.0 × 2.868
        self.assertAlmostEqual(c["transport_cost"], 75.0, places=2)  # ثابتة
        self.assertAlmostEqual(
            c["total_cost"], round(4700.0 + 1.5 + 2.87 + 75.0, 2), places=2)

    def test_case3_heavier_mix(self) -> None:
        """وزن 5000 كغ — العمال تتغير والكهرباء والنقل ثابتتان."""
        items = [{"material_name": "ذرة", "qty_kg": 5000.0, "unit_price": 5.0}]
        c = self._assert_consistent(items, "مزرعة-ب", 1.5, 2.868)
        self.assertEqual(c["billable_tons"], 5.0)
        self.assertAlmostEqual(c["elec_cost"], 1.5, places=2)       # لم تتغير
        self.assertAlmostEqual(c["transport_cost"], 75.0, places=2)  # لم تتغير
        self.assertAlmostEqual(c["labor_cost"], round(5.0 * 2.868, 2), places=2)

    # ------------------------------------------------------------
    # خصائص إضافية مطلوبة
    # ------------------------------------------------------------

    def test_elec_is_constant_across_weights(self) -> None:
        """الكهرباء قيمة ثابتة: لا تتغير بتغير الوزن إطلاقاً."""
        light = [{"material_name": "ذرة", "qty_kg": 250.0, "unit_price": 5.0}]
        heavy = [{"material_name": "ذرة", "qty_kg": 10000.0, "unit_price": 5.0}]
        c1 = calculate_mix(light, "مزرعة-أ")
        c2 = calculate_mix(heavy, "مزرعة-أ")
        self.assertEqual(c1["elec_cost"], c2["elec_cost"])
        self.assertEqual(c1["elec_rate"], c2["elec_rate"])

    def test_net_cost_override(self) -> None:
        """التعديل اليدوي للصافي: mixer_net_cost = override + manually_edited=True."""
        items = [{"material_name": "ذرة", "qty_kg": 1000.0, "unit_price": 5.0}]
        c = calculate_mix(items, "مزرعة-أ", net_cost_override=9999.0)
        self.assertTrue(c["manually_edited"])
        self.assertAlmostEqual(c["mixer_net_cost"], 9999.0, places=2)
        # بدون تعديل: الصافي = الإجمالي
        d = calculate_mix(items, "مزرعة-أ")
        self.assertFalse(d["manually_edited"])
        self.assertEqual(d["mixer_net_cost"], d["total_cost"])

    def test_return_contract_keys(self) -> None:
        """عقد الإرجاع: كل المفاتيح الـ 13 المطلوبة موجودة في calculate_mix."""
        required = {
            "priced_items", "total_weight_kg", "billable_tons", "feed_cost",
            "elec_rate", "labor_rate", "farm_transport_fee", "elec_cost",
            "labor_cost", "transport_cost", "total_cost", "mixer_net_cost",
            "manually_edited",
        }
        items = [{"material_name": "ذرة", "qty_kg": 500.0, "unit_price": 5.0}]
        c = calculate_mix(items, "مزرعة-أ")
        self.assertTrue(required.issubset(set(c.keys())),
                        f"مفاتيح مفقودة: {required - set(c.keys())}")

    def test_frozen_price_respected(self) -> None:
        """السعر المجمّد في البند يجب أن يُستخدم ولا يُعاد حسابه حياً."""
        items = [{"material_name": "ذرة", "qty_kg": 1000.0, "unit_price": 3.3}]
        c = calculate_mix(items, "مزرعة-أ")
        self.assertAlmostEqual(c["feed_cost"], 3300.0, places=2)


if __name__ == "__main__":
    unittest.main()
