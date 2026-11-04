"""
test_permissions
----------------
اختبارات وحدة لمصفوفة الصلاحيات core/permissions.py:
    - has_permission: admin يملك "*"، operator مجموعة محددة، viewer للقراءة فقط.
    - require_permission: لا يرفع لـ admin ويرفع PermissionDenied لـ viewer.
    - role_label: أسماء الأدوار بالعربية من settings.ROLE_LABELS.

ملاحظة: الدوال تقبل قاموس مستخدم {"role": ...} أو نص الدور مباشرة.

التشغيل:
    cd /workspace && python -m unittest tests.test_permissions -v
"""

from __future__ import annotations

import unittest

from core.permissions import (
    PermissionDenied,
    has_permission,
    require_permission,
    role_label,
)


class TestHasPermission(unittest.TestCase):
    """استعلام الصلاحيات حسب الدور."""

    def test_admin_all(self) -> None:
        # admin يملك "*" → أي صلاحية بماها إدارة المستخدمين
        self.assertTrue(has_permission({"role": "admin"}, "users.manage"))
        self.assertTrue(has_permission({"role": "admin"}, "mix.create"))
        self.assertTrue(has_permission({"role": "admin"}, "أي.صلاحية.جديدة"))

    def test_viewer_cannot_create_mix(self) -> None:
        # viewer يملك "view" فقط → لا إنشاء ولا حذف
        self.assertFalse(has_permission({"role": "viewer"}, "mix.create"))
        self.assertFalse(has_permission({"role": "viewer"}, "invoices.delete"))

    def test_viewer_can_view(self) -> None:
        self.assertTrue(has_permission({"role": "viewer"}, "view"))

    def test_operator_can_create_mix(self) -> None:
        # operator ضمن مجموعته: mix.create مسموح
        self.assertTrue(has_permission({"role": "operator"}, "mix.create"))

    def test_operator_cannot_manage_users(self) -> None:
        # users.manage مقصور على admin — ليس في مجموعة operator
        self.assertFalse(has_permission({"role": "operator"}, "users.manage"))
        self.assertFalse(has_permission({"role": "operator"}, "settings.edit"))

    def test_role_string_accepted(self) -> None:
        # تقبل نص الدور مباشرة بدل القاموس (نفس النتيجة)
        self.assertTrue(has_permission("admin", "backup.restore"))
        self.assertFalse(has_permission("viewer", "backup.run"))

    def test_unknown_and_none_roles_denied(self) -> None:
        # دور مجهول أو None → viewer افتراضياً → رفض الإجراءات الكتابة
        self.assertFalse(has_permission(None, "mix.create"))
        self.assertFalse(has_permission({"role": "ghost"}, "mix.create"))

    def test_empty_permission_denied(self) -> None:
        # مفتاح فارغ لا يطابق شيئاً أبداً حتى لـ admin
        self.assertFalse(has_permission({"role": "admin"}, ""))


class TestRequirePermission(unittest.TestCase):
    """require_permission: تمرير صامت أو رفع PermissionDenied."""

    def test_admin_passes_any(self) -> None:
        # لا يستثني شيء لـ admin — أي صلاحية تمر بصمت
        require_permission({"role": "admin"}, "any.perm")

    def test_viewer_raises(self) -> None:
        with self.assertRaises(PermissionDenied):
            require_permission({"role": "viewer"}, "mix.create")

    def test_operator_passes_own_perm(self) -> None:
        require_permission({"role": "operator"}, "payments.create")

    def test_error_message_arabic(self) -> None:
        # الرسالة عربية وتذكر اسم الصلاحية للمساءلة
        with self.assertRaises(PermissionDenied) as ctx:
            require_permission({"role": "viewer"}, "recipes.delete")
        self.assertIn("recipes.delete", str(ctx.exception))
        # PermissionDenied مشتق من PermissionError — تلتقطه معالجات الأخطاء العامة
        self.assertIsInstance(ctx.exception, PermissionError)


class TestRoleLabel(unittest.TestCase):
    """role_label يعيد التسمية العربية من settings.ROLE_LABELS."""

    def test_labels(self) -> None:
        self.assertEqual(role_label({"role": "admin"}), "مدير النظام")
        self.assertEqual(role_label({"role": "operator"}), "مشغّل")
        self.assertEqual(role_label({"role": "viewer"}), "مشاهد")

    def test_unknown_role_falls_back(self) -> None:
        # دور غير معروف → يُعاد كما هو بدل الانهيار (سلوك آمن للعرض)
        self.assertEqual(role_label({"role": "auditor"}), "auditor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
