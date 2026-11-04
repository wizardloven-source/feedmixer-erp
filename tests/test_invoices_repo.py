"""
test_invoices_repo
------------------
اختبارات وحدة لمستودع الفواتير data/invoices_repo.py (تحصين المرحلة 4):
    - add_invoice: get_invoice يعيد الفاتورة؛ حالة دفع غير صالحة → ValueError؛
      مخزون غير كافٍ → ValueError.
    - update_invoice عبر diff: الحفاظ على id البنود و price_snapshot_at،
      والحذف/الإدراج الانتقائي فقط.
    - soft_delete_invoice: رفض الحذف إذا كانت الدفعات تتجاوز صافي الفواتير
      الأخرى (رصيد سالب)، ونجاحه مع استبعاد من list_invoices الافتراضي.
    - restore_invoice: إعادة الفاتورة للظهور.

التشغيل:
    cd /workspace && python -m unittest tests.test_invoices_repo -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from core import cache
from data.connection import set_database_path


class TestInvoicesRepo(unittest.TestCase):
    """فواتير + بنود ضد قاعدة بيانات SQLite مؤقتة معزولة."""

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
        # تنظيف كل سطر اختبار: حذف الحركات فقط
        from data.connection import execute

        execute("DELETE FROM mix_items")
        execute("DELETE FROM mix_invoices")
        execute("DELETE FROM purchases")
        execute("DELETE FROM payments")
        cache.invalidate_all()

    # ------------------------------------------------------------ أدوات
    def _setup_world(self, material: str = "قمح-فحص", farm: str = "مزرعة-فحص",
                     supply_ton: float = 100.0,
                     extra_materials: tuple[str, ...] = ()) -> None:
        """يجهّز مزرعة ومادة (مواد) وتوريدها — مخزون كافٍ لكل الاختبارات."""
        from data import farms_repo, materials_repo, purchases_repo

        if farms_repo.get_farm_by_name(farm) is None:
            farms_repo.add_farm(farm, transport_fee=0.0)
        # البذور قد تحتوي مواد بأسماء مشابهة — نضمن وجود كل مادة مطلوبة
        for name in (material, *extra_materials):
            try:
                materials_repo.add_material(name, base_price=5000.0, unit_type="ton")
            except ValueError:
                pass  # موجودة مسبقاً
        cache.invalidate_materials()
        if supply_ton > 0:
            for name in (material, *extra_materials):
                purchases_repo.add_purchase(
                    purchase_date="2026-10-01", material_name=name,
                    qty_ton=supply_ton, price_per_ton=5000.0,
                )

    def _add(self, farm: str = "مزرعة-فحص", qty_kg: float = 1000.0,
             material: str = "قمح-فحص", **kw) -> str:
        """أضف فاتورة بسيطة بمادة واحدة."""
        from data import invoices_repo

        items = kw.pop("items", None) or [
            {"material_name": material, "qty_kg": qty_kg, "unit_price": 5.0}
        ]
        return invoices_repo.add_invoice(
            mix_date="2026-11-02", farm_name=farm, items=items, **kw
        )

    # ------------------------------------------------------------ add_invoice
    def test_add_invoice_roundtrip(self) -> None:
        """إضافة فاتورة بسيطة → get_invoice يعيدها بنفس البيانات والبنود."""
        from data import invoices_repo

        self._setup_world()
        number = self._add(qty_kg=1000.0)
        inv = invoices_repo.get_invoice(number)
        self.assertIsNotNone(inv)
        assert inv is not None
        self.assertEqual(inv["mix_number"], number)
        self.assertEqual(inv["farm_name"], "مزرعة-فحص")
        self.assertEqual(len(inv["items"]), 1)
        self.assertAlmostEqual(float(inv["items"][0]["qty_kg"]), 1000.0, places=3)
        self.assertEqual(inv["payment_status"], "unpaid")  # السلوك الافتراضي محفوظ

    def test_add_invoice_invalid_payment_status(self) -> None:
        """payment_status="xyz" غير صالح → ValueError (تحصين المرحلة 4)."""
        self._setup_world()
        with self.assertRaises(ValueError):
            self._add(payment_status="xyz")

    def test_add_invoice_insufficient_stock(self) -> None:
        """طلب كمية أكبر من المتاح → ValueError عجز مخزون."""
        self._setup_world(supply_ton=1.0)  # طن واحد متاح فقط
        with self.assertRaises(ValueError):
            self._add(qty_kg=5000.0)  # نطلب 5 أطنان

    # ------------------------------------------------------------ update_invoice (diff)
    def test_update_farm_only_keeps_items_and_ids(self) -> None:
        """تعديل المزرعة فقط (بدون items) → البنود وأرقام id محفوظة حرفياً."""
        from data import farms_repo, invoices_repo

        self._setup_world()
        farms_repo.add_farm("مزرعة-بديلة", transport_fee=0.0)
        number = self._add(qty_kg=1000.0)
        ids_before = [int(i["id"]) for i in invoices_repo.get_invoice(number)["items"]]
        snap_before = invoices_repo.get_invoice(number)["items"][0]["price_snapshot_at"]

        self.assertTrue(invoices_repo.update_invoice(number, farm_name="مزرعة-بديلة"))
        after = invoices_repo.get_invoice(number)
        self.assertEqual(after["farm_name"], "مزرعة-بديلة")
        ids_after = [int(i["id"]) for i in after["items"]]
        # diff: لم تُمرَّر items → لا لمس للبنود إطلاقاً
        self.assertEqual(ids_before, ids_after)
        self.assertEqual(after["items"][0]["price_snapshot_at"], snap_before)

    def test_update_items_diff_preserves_id_and_snapshot(self) -> None:
        """تغيير كمية بند موجود → UPDATE يحفظ id ولا يغيّر price_snapshot_at؛
        والبند الجديد يُدرج بـ id جديد؛ القديم المحذوف يختفي وحده."""
        from data.connection import query_all
        from data import invoices_repo

        # تجهيز ثلاث مواد بمخزون كافٍ (قمح + نخالة للقديم، ذرة للجديد)
        self._setup_world(extra_materials=("نخالة-فحص", "ذرة-فحص"))

        number = self._add(items=[
            {"material_name": "قمح-فحص", "qty_kg": 1000.0, "unit_price": 5.0},
            {"material_name": "نخالة-فحص", "qty_kg": 500.0, "unit_price": 4.0},
        ])
        before = {str(r["material_name"]): r for r in query_all(
            "SELECT * FROM mix_items WHERE mix_number = ?", (number,))}
        wheat_id = int(before["قمح-فحص"]["id"])
        wheat_snap = before["قمح-فحص"]["price_snapshot_at"]

        self.assertTrue(invoices_repo.update_invoice(number, items=[
            {"material_name": "قمح-فحص", "qty_kg": 2000.0, "unit_price": 5.0},
            {"material_name": "ذرة-فحص", "qty_kg": 300.0, "unit_price": 5.0},
        ]))
        after = {str(r["material_name"]): r for r in query_all(
            "SELECT * FROM mix_items WHERE mix_number = ?", (number,))}

        self.assertEqual(set(after), {"قمح-فحص", "ذرة-فحص"})
        # UPDATE حافظ على id البند الأصلي وطابعه السعري
        self.assertEqual(int(after["قمح-فحص"]["id"]), wheat_id)
        self.assertEqual(after["قمح-فحص"]["price_snapshot_at"], wheat_snap)
        self.assertAlmostEqual(float(after["قمح-فحص"]["qty_kg"]), 2000.0, places=3)
        # البند الجديد id مختلف (INSERT)
        self.assertNotEqual(int(after["ذرة-فحص"]["id"]), wheat_id)

    # ------------------------------------------------------------ soft_delete
    def test_soft_delete_hides_from_list(self) -> None:
        """حذف ناعم → is_deleted=1 ولا تظهر في list_invoices الافتراضية."""
        from data import invoices_repo

        self._setup_world()
        number = self._add()
        self.assertTrue(invoices_repo.soft_delete_invoice(number))
        inv = invoices_repo.get_invoice(number)
        assert inv is not None
        self.assertEqual(int(inv["is_deleted"] or 0), 1)
        numbers = [r["mix_number"] for r in invoices_repo.list_invoices()]
        self.assertNotIn(number, numbers)
        # تظهر فقط عند طلب include_deleted
        self.assertIn(number, [r["mix_number"] for r in
                               invoices_repo.list_invoices(include_deleted=True)])

    def test_soft_delete_blocked_by_orphan_payment(self) -> None:
        """دفعة تتجاوز صافي الفواتير الأخرى → حذف الفاتورة يجعل الرصيد
        سالباً → ValueError برسالة عربية واضحة (تحصين المرحلة 4)."""
        from data import invoices_repo, payments_repo

        self._setup_world()
        n1 = self._add()                       # فاتورة 1 بصافي ~5000+
        n2 = self._add()                       # فاتورة 2
        p1 = invoices_repo.get_invoice(n1)["mixer_net_cost"]
        p2 = invoices_repo.get_invoice(n2)["mixer_net_cost"]
        # دفعة أكبر من صافي الفاتورة الثانية (الأخرى بعد حذف الأولى)
        payments_repo.add_payment(farm_name="مزرعة-فحص", payment_date="2026-11-03",
                                  amount=float(p2) + 1000.0, method="cash")
        with self.assertRaises(ValueError) as ctx:
            invoices_repo.soft_delete_invoice(n1)
        msg = str(ctx.exception)
        # الرسالة يجب أن تكون عربية توضيحية (تحذير + أرصدة + توصية)
        self.assertIn("دفعات", msg)
        self.assertIn("سالباً", msg)
        # ولم تُحذف فعلياً
        self.assertEqual(int(invoices_repo.get_invoice(n1)["is_deleted"] or 0), 0)
        # أما حذف الفاتورة الثانية فد مسموحاً؟ الدفعات (p2+1000) > صافي الأولى (p1)?
        # نعم ستُرفض أيضاً — نفس المنطق الدفاعي متماثل. نتحقق بدل ذلك أن
        # الحذف ينجح عندما لا توجد دفعات إطلاقاً (اختبار سابق يكفي).
        self.assertGreater(float(p1) + float(p2), 0.0)

    def test_soft_delete_allowed_when_payments_covered(self) -> None:
        """دفعة صغيرة مغطاة بفواتير أخرى → الحذف الناعم يمر بشكل طبيعي."""
        from data import invoices_repo, payments_repo

        self._setup_world()
        n1 = self._add()
        self._add()  # فاتورة ثانية تغطي الدفعة
        payments_repo.add_payment(farm_name="مزرعة-فحص", payment_date="2026-11-03",
                                  amount=10.0, method="cash")
        self.assertTrue(invoices_repo.soft_delete_invoice(n1))

    # ------------------------------------------------------------ restore
    def test_restore_invoice(self) -> None:
        """استعادة فاتورة محذوفة → is_deleted=0 وتظهر في القائمة من جديد."""
        from data import invoices_repo

        self._setup_world()
        number = self._add()
        invoices_repo.soft_delete_invoice(number)
        self.assertTrue(invoices_repo.restore_invoice(number))
        inv = invoices_repo.get_invoice(number)
        assert inv is not None
        self.assertEqual(int(inv["is_deleted"] or 0), 0)
        self.assertIn(number, [r["mix_number"] for r in invoices_repo.list_invoices()])
        # الاستعادة مرة ثانية لا تفعل شيئاً (idempotent)
        self.assertFalse(invoices_repo.restore_invoice(number))

    # ------------------------------------------------------------ set_payment_status
    def test_set_payment_status_validation(self) -> None:
        """set_payment_status تقبل القيم النظامية وترفض ما عداها."""
        from data import invoices_repo

        self._setup_world()
        number = self._add()
        self.assertTrue(invoices_repo.set_payment_status(number, "paid"))
        self.assertEqual(invoices_repo.get_invoice(number)["payment_status"], "paid")
        with self.assertRaises(ValueError):
            invoices_repo.set_payment_status(number, "bogus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
