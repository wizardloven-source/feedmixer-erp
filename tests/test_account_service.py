"""
test_account_service
--------------------
اختبارات وحدة لخدمات الحسابات services/account_service.py:
    - farm_invoices_total: Σ صافي الفواتير غير المحذوفة.
    - farm_summary: (مطلوب − مدفوع) مع الحالة (عليه/مسدد/له).
    - account_statement: entries مرتبة زمنياً + running_balance تراكمي.
    - totals_overview: المجاميع العامة وعدد المدينين.

القاعدة المعتمدة:
    المستحق على المزرعة = Σ mixer_net_cost (غير محذوفة) − Σ payments.amount

التشغيل:
    cd /workspace && python -m unittest tests.test_account_service -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from core import cache
from data.connection import set_database_path


class TestAccountService(unittest.TestCase):
    """حسابات المزارع ضد قاعدة بيانات SQLite مؤقتة معزولة."""

    @classmethod
    def setUpClass(cls) -> None:
        # قاعدة بيانات معزولة في ملف مؤقت — لا تلمس بيانات المستخدم الحقيقي
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls.db_path = cls._tmp.name

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
        # تنظيف كل سطر اختبار: حذف الحركات فقط (المزارع والمواد تبقى)
        from data.connection import execute

        execute("DELETE FROM mix_items")
        execute("DELETE FROM mix_invoices")
        execute("DELETE FROM purchases")
        execute("DELETE FROM payments")
        cache.invalidate_all()

    # ------------------------------------------------------------ أدوات
    def _farm(self, name: str) -> None:
        """يتأكد من وجود مزرعة للاختبار."""
        from data import farms_repo

        if farms_repo.get_farm_by_name(name) is None:
            farms_repo.add_farm(name, transport_fee=0.0)

    def _material(self, name: str) -> None:
        """يتأكد من وجود مادة للاختبار (فحص المخزون يتطلبها)."""
        from data import materials_repo

        try:
            materials_repo.add_material(name, base_price=1000.0, unit_type="ton")
        except ValueError:
            pass
        cache.invalidate_materials()

    def _invoice(self, farm: str, net: float, date: str = "2026-11-02") -> str:
        """
        يدرج فاتورة بصافي محدد مباشرة (net_cost_override) بعد تأمين
        مخزون كافٍ للمادة المستخدمة حتى لا يرفض add_invoice العجز.
        """
        self._farm(farm)
        mat = "مادة-محاسبية"
        self._material(mat)
        from data import invoices_repo, purchases_repo

        # توريد احتياطي كبير لتفادي رفض فحص المخزون (الكمية صغيرة: 1 كغ)
        purchases_repo.add_purchase(
            purchase_date="2026-10-01", material_name=mat,
            qty_ton=1000.0, price_per_ton=1000.0,
        )
        return invoices_repo.add_invoice(
            mix_date=date,
            farm_name=farm,
            items=[{"material_name": mat, "qty_kg": 1.0, "unit_price": 1.0}],
            net_cost_override=net,
        )

    def _payment(self, farm: str, amount: float, date: str = "2026-11-03") -> int:
        """يسجّل دفعة للمزرعة."""
        from data import payments_repo

        self._farm(farm)
        return payments_repo.add_payment(
            farm_name=farm, payment_date=date, amount=amount, method="cash",
        )

    # ------------------------------------------------------------ اختبارات
    def test_farm_invoices_total(self) -> None:
        """فاتورتان (1000 + 2000) → 3000؛ والفاتورة المحذوفة لا تُحسب."""
        from services import account_service

        n1 = self._invoice("مزرعة-س", 1000.0)
        self._invoice("مزرعة-س", 2000.0)
        self.assertAlmostEqual(account_service.farm_invoices_total("مزرعة-س"), 3000.0, places=2)

        # حذف ناعم للأولى (لا دفعات → مسموح) → يتبقى 2000 فقط
        from data import invoices_repo

        invoices_repo.soft_delete_invoice(n1)
        cache.invalidate_all()
        self.assertAlmostEqual(account_service.farm_invoices_total("مزرعة-س"), 2000.0, places=2)

    def test_farm_summary_debtor(self) -> None:
        """فاتورة 1000 + دفعة 400 → balance 600 والحالة «عليه»."""
        from services import account_service

        self._invoice("مزرعة-د", 1000.0)
        self._payment("مزرعة-د", 400.0)
        s = account_service.farm_summary("مزرعة-د")
        self.assertAlmostEqual(s["billed_total"], 1000.0, places=2)
        self.assertAlmostEqual(s["paid_total"], 400.0, places=2)
        self.assertAlmostEqual(s["balance"], 600.0, places=2)
        self.assertEqual(s["status"], "عليه")
        self.assertEqual(s["invoices_count"], 1)

    def test_farm_summary_settled(self) -> None:
        """فاتورة 1000 + دفعة 1000 → balance صفر والحالة «مسدد»."""
        from services import account_service

        self._invoice("مزرعة-م", 1000.0)
        self._payment("مزرعة-م", 1000.0)
        s = account_service.farm_summary("مزرعة-م")
        self.assertAlmostEqual(s["balance"], 0.0, places=2)
        self.assertEqual(s["status"], "مسدد")

    def test_farm_summary_credit(self) -> None:
        """فاتورة 1000 + دفعة 1500 → balance −500 والحالة «له» (دفع زيادة)."""
        from services import account_service

        self._invoice("مزرعة-ل", 1000.0)
        self._payment("مزرعة-ل", 1500.0)
        s = account_service.farm_summary("مزرعة-ل")
        self.assertAlmostEqual(s["balance"], -500.0, places=2)
        self.assertEqual(s["status"], "له")

    def test_account_statement_entries_and_running_balance(self) -> None:
        """فاتورتان ودفعة واحدة → 3 entries مرتبة زمنياً ورصيد تراكمي صحيح."""
        from services import account_service

        # فاتورة 1000 في 2026-11-01، دفعة 300 في 2026-11-02، فاتورة 500 في 2026-11-03
        self._invoice("مزرعة-ك", 1000.0, date="2026-11-01")
        self._payment("مزرعة-ك", 300.0, date="2026-11-02")
        self._invoice("مزرعة-ك", 500.0, date="2026-11-03")

        st = account_service.account_statement("مزرعة-ك")
        entries = st["entries"]
        self.assertEqual(len(entries), 3)
        # ترتيب زمني تصاعدي
        dates = [e["date"] for e in entries]
        self.assertEqual(dates, sorted(dates))
        # الأنواع: فاتورة ← دفعة ← فاتورة
        self.assertEqual([e["kind"] for e in entries], ["invoice", "payment", "invoice"])
        # الرصيد التراكمي: 1000 → 700 → 1200
        self.assertAlmostEqual(entries[0]["running_balance"], 1000.0, places=2)
        self.assertAlmostEqual(entries[1]["running_balance"], 700.0, places=2)
        self.assertAlmostEqual(entries[2]["running_balance"], 1200.0, places=2)
        # المجاميع: مدين 1500 / دائن 300
        self.assertAlmostEqual(st["total_debit"], 1500.0, places=2)
        self.assertAlmostEqual(st["total_credit"], 300.0, places=2)
        self.assertAlmostEqual(st["period_balance"], 1200.0, places=2)

    def test_totals_overview(self) -> None:
        """totals_overview: billed/paid/outstanding/debtors_count صحيحة."""
        from services import account_service

        # مزرعة مدينة: فاتورة 1000 + دفعة 400 → مستحق 600
        self._invoice("مزرعة-ع", 1000.0)
        self._payment("مزرعة-ع", 400.0)
        # مزرعة مسددة بالكامل: فاتورة 200 + دفعة 200 → مستحق 0
        self._invoice("مزرعة-غ", 200.0)
        self._payment("مزرعة-غ", 200.0)

        ov = account_service.totals_overview()
        self.assertGreaterEqual(ov["billed_total"], 1200.0)
        self.assertGreaterEqual(ov["paid_total"], 600.0)
        # outstanding يجمع الأرصدة الموجبة فقط (مدينون) — لا يدخل فيه المسدد
        self.assertGreaterEqual(ov["outstanding"], 600.0)
        self.assertGreaterEqual(ov["debtors_count"], 1.0)
        # التأكد أن مزرعة-غ ليست ضمن المتأخرات: ملخصها لا يظهر كمدين
        summaries = {s["farm_name"]: s for s in account_service.all_farms_summary()}
        self.assertAlmostEqual(summaries["مزرعة-غ"]["balance"], 0.0, places=2)
        self.assertAlmostEqual(summaries["مزرعة-ع"]["balance"], 600.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
