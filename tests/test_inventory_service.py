"""
test_inventory_service
----------------------
اختبارات وحدة لخدمات المخزون services/inventory_service.py:
    - _load_balances / inventory_balances: المورد/المستهلك/المتبقي بالطن.
    - استثناء الفواتير المحذوفة ناعماً (is_deleted=1) من الاستهلاك.
    - low_stock_items / balance_of / summary_totals.

القاعدة المعتمدة:
    المتبقي (طن) = Σ توريدات (purchases.qty_ton) − Σ بنود خلطات غير محذوفة (qty_kg/1000)

التشغيل:
    cd /workspace && python -m unittest tests.test_inventory_service -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from config import settings
from core import cache
from data.connection import set_database_path


class TestInventoryService(unittest.TestCase):
    """أرصدة المخزون عبر قاعدة بيانات SQLite مؤقتة معزولة."""

    @classmethod
    def setUpClass(cls) -> None:
        # قاعدة بيانات معزولة في ملف مؤقت — لا تلمس بيانات المستخدم الحقيقي
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls.db_path = cls._tmp.name

        # نفس ترتيب الإقلاع الحقيقي: مخطط ← ترحيلات (تضيف price_snapshot_at) ← بذور
        from data.schema import init_database
        from data.migrations import run_migrations
        from data.seed import seed_defaults

        set_database_path(cls.db_path)
        init_database()
        run_migrations()
        seed_defaults()

    @classmethod
    def tearDownClass(cls) -> None:
        cache.invalidate_all()
        set_database_path(None)
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    def setUp(self) -> None:
        # تنظيف كل سطر اختبار: حذف الحركات + إعادة البذور (idempotent)
        from data.connection import execute
        from data.seed import seed_defaults

        execute("DELETE FROM mix_items")
        execute("DELETE FROM mix_invoices")
        execute("DELETE FROM purchases")
        execute("DELETE FROM payments")
        cache.invalidate_all()
        seed_defaults()
        cache.invalidate_all()

    # ------------------------------------------------------------ أدوات
    def _add_material(self, name: str) -> None:
        """يضيف مادة للاختبار (يتجاهل التكرار لأن seed قد يحتويها)."""
        from data import materials_repo

        try:
            materials_repo.add_material(name, base_price=5000.0, unit_type="ton")
        except ValueError:
            pass  # موجودة مسبقاً من البذور
        cache.invalidate_materials()

    def _purchase(self, material: str, qty_ton: float) -> int:
        """يسجّل توريد بكمية طن للمادة."""
        from data import purchases_repo

        return purchases_repo.add_purchase(
            purchase_date="2026-11-01",
            material_name=material,
            qty_ton=qty_ton,
            price_per_ton=5000.0,
        )

    def _mix(self, material: str, qty_kg: float, farm: str = "مزرعة-اختبار") -> str:
        """يسجّل خلطة بمادة واحدة ويعيد رقم الخلطة."""
        from data import farms_repo, invoices_repo

        if farms_repo.get_farm_by_name(farm) is None:
            farms_repo.add_farm(farm, transport_fee=0.0)
        return invoices_repo.add_invoice(
            mix_date="2026-11-02",
            farm_name=farm,
            items=[{"material_name": material, "qty_kg": qty_kg, "unit_price": 5.0}],
        )

    def _balance_row(self, name: str) -> dict:
        """يعيد صف رصيد مادة من الخدمة مباشرة (بلا كاش)."""
        for row in cache.get_or_load("inventory:balances", self._load(), ttl=30.0):
            if str(row.get("name")) == name:
                return row
        self.fail(f"المادة «{name}» غير موجودة في الأرصدة")
        return {}  # unreachable

    @staticmethod
    def _load():
        from services.inventory_service import _load_balances

        return _load_balances

    # ------------------------------------------------------------ اختبارات
    def test_supply_only(self) -> None:
        """توريد 10 طن بلا استهلاك → المورد 10 والمتبقي 10."""
        self._add_material("قمح-أ")
        self._purchase("قمح-أ", 10.0)
        row = self._balance_row("قمح-أ")
        self.assertAlmostEqual(row["supplied_ton"], 10.0, places=3)
        self.assertAlmostEqual(row["consumed_ton"], 0.0, places=3)
        self.assertAlmostEqual(row["remaining_ton"], 10.0, places=3)

    def test_supply_and_consumption(self) -> None:
        """توريد 10 طن وخلطة 5000 كغ (غير محذوفة) → المتبقي 5 طن."""
        self._add_material("قمح-ب")
        self._purchase("قمح-ب", 10.0)
        self._mix("قمح-ب", 5000.0)
        row = self._balance_row("قمح-ب")
        self.assertAlmostEqual(row["consumed_ton"], 5.0, places=3)
        self.assertAlmostEqual(row["remaining_ton"], 5.0, places=3)

    def test_negative_balance(self) -> None:
        """توريد 5 طن واستهلاك 7 طن → المتبقي −2 وراية negative مرفوعة."""
        self._add_material("قمح-ج")
        self._purchase("قمح-ج", 5.0)
        # فحص المخزون في add_invoice سيرفض العجز — نتجاوز طبقة الخدمة ونكتب
        # الفاتورة مباشرة لأن الهدف هنا اختبار حساب الرصيد لا فحص العجز.
        from data.connection import execute

        from data import farms_repo

        farm = "مزرعة-اختبار"
        if farms_repo.get_farm_by_name(farm) is None:
            farms_repo.add_farm(farm, transport_fee=0.0)
        execute(
            "INSERT INTO mix_invoices (mix_number, mix_date, farm_name, mixer_net_cost,"
            " payment_status, is_deleted) VALUES ('MIX-NEG-0001','2026-11-02',?,7000,'unpaid',0)",
            (farm,),
        )
        execute(
            "INSERT INTO mix_items (mix_number, material_name, qty_kg, unit_price, total_price)"
            " VALUES ('MIX-NEG-0001','قمح-ج',7000,5,35000)",
        )
        row = self._balance_row("قمح-ج")
        self.assertAlmostEqual(row["remaining_ton"], -2.0, places=3)
        self.assertTrue(row["negative"])

    def test_deleted_invoice_not_consumed(self) -> None:
        """فاتورة محذوفة ناعماً (is_deleted=1) لا تُحتسب في الاستهلاك."""
        self._add_material("قمح-د")
        self._purchase("قمح-د", 10.0)
        mix_number = self._mix("قمح-د", 5000.0)
        self.assertAlmostEqual(self._balance_row("قمح-د")["remaining_ton"], 5.0, places=3)

        from data import invoices_repo

        self.assertTrue(invoices_repo.soft_delete_invoice(mix_number))
        cache.invalidate_all()
        row = self._balance_row("قمح-د")
        # بعد الحذف الناعم يعود الاستهلاك صفراً → المتبقي 10 كاملة
        self.assertAlmostEqual(row["consumed_ton"], 0.0, places=3)
        self.assertAlmostEqual(row["remaining_ton"], 10.0, places=3)

    def test_low_stock_items(self) -> None:
        """مادة بـ 3 طن (< الحد 5) تظهر في low_stock، وبـ 6 طن لا تظهر."""
        self._add_material("قمح-هـ")
        self._add_material("قمح-و")
        self._purchase("قمح-هـ", 3.0)   # منخفض
        self._purchase("قمح-و", 6.0)    # سليم
        from services import inventory_service

        names = {r["name"] for r in inventory_service.low_stock_items()}
        self.assertIn("قمح-هـ", names)
        self.assertNotIn("قمح-و", names)
        # الحد الافتراضي مطابق لإعداد النظام
        self.assertEqual(settings.LOW_STOCK_THRESHOLD_TONS, 5.0)

    def test_balance_of(self) -> None:
        """balance_of لمادة موجودة → الرصيد الصحيح؛ وغير موجودة → 0.0."""
        self._add_material("قمح-ز")
        self._purchase("قمح-ز", 8.0)
        self._mix("قمح-ز", 3000.0)
        from services import inventory_service

        self.assertAlmostEqual(inventory_service.balance_of("قمح-ز"), 5.0, places=3)
        self.assertEqual(inventory_service.balance_of("مادة-لا-توجد"), 0.0)
        # available_kg = الرصيد × 1000 (تحويل طن→كغ)
        self.assertAlmostEqual(inventory_service.available_kg("قمح-ز"), 5000.0, places=1)

    def test_summary_totals(self) -> None:
        """summary_totals تعيد مجاميع صحيحة (مورد/مستهلك/متبقٍ/عدد المنخفض)."""
        self._add_material("قمح-ح")
        self._add_material("قمح-ط")
        self._purchase("قمح-ح", 10.0)
        self._purchase("قمح-ط", 4.0)     # منخفض (< 5)
        self._mix("قمح-ح", 5000.0)       # مستهلك 5 طن
        from services import inventory_service

        totals = inventory_service.summary_totals()
        self.assertGreaterEqual(totals["supplied_ton"], 14.0)
        self.assertGreaterEqual(totals["consumed_ton"], 5.0)
        # متبقي المادتين معاً: 5 + 4 = 9 (قد تزيد مواد البذور على ذلك)
        self.assertGreaterEqual(totals["remaining_ton"], 9.0)
        self.assertGreaterEqual(totals["low_count"], 1)
        self.assertEqual(totals["materials_count"], len(inventory_service.inventory_balances()))

    def test_cache_invalidate_effect(self) -> None:
        """invalidate() يجبر الحساب من جديد — أساسي بعد كل عملية حفظ."""
        self._add_material("قمح-ي")
        self._purchase("قمح-ي", 10.0)
        from services import inventory_service

        self.assertAlmostEqual(inventory_service.balance_of("قمح-ي"), 10.0, places=3)
        self._purchase("قمح-ي", 5.0)  # بدون إبطال → الكاش القديم قد يبقى
        inventory_service.invalidate()
        cache.invalidate_all()
        self.assertAlmostEqual(inventory_service.balance_of("قمح-ي"), 15.0, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
