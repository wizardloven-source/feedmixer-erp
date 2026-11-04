"""
core/permissions.py
-------------------
مصفوفة الصلاحيات حسب الدور (admin / operator / viewer).

الاستخدام في الواجهة:
    if has_permission(self.app.current_user, "mix.create"):
        make_button(...)
    require_permission(user, "users.manage")  # يرفع PermissionDenied

المفاتيح تُبنى على النمط "المورد.الإجراء"، ويدعم النظام:
- "*"            : كل الصلاحيات (admin).
- "مورد.*"        : كل إجراءات مورد معين.
- مطابقة تامة     : "mix.create".
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from config import settings

# ============================================================
# 1) قائمة الصلاحيات المعروفة (تُستخدم أيضاً في الواجهة لعرض الأدوار)
# ============================================================

ALL_PERMISSIONS: Final[tuple[str, ...]] = (
    "view",
    "mix.create",
    "mix.edit",
    "mix.delete",
    "inventory.export",
    "purchases.create",
    "purchases.edit",
    "purchases.delete",
    "purchases.import",
    "invoices.delete",
    "invoices.restore",
    "invoices.edit_net",
    "farms.edit",
    "farms.delete",
    "materials.edit",
    "materials.delete",
    "payments.create",
    "payments.delete",
    "recipes.edit",
    "recipes.delete",
    "reports.export",
    "users.manage",
    "settings.edit",
    "audit.view",
    "backup.run",
    "backup.restore",
    "db.integrity",
)

# ============================================================
# 2) المصفوفة
# ============================================================

_OPERATOR_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        "view",
        "mix.create",
        "mix.edit",
        "mix.delete",
        "inventory.export",
        "purchases.create",
        "purchases.edit",
        "purchases.delete",
        "purchases.import",
        "invoices.delete",
        "invoices.restore",
        "invoices.edit_net",
        "farms.edit",
        "payments.create",
        "payments.delete",
        "recipes.edit",
        "recipes.delete",
        "reports.export",
        "materials.edit",
        "backup.run",
    }
)

PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    settings.ROLE_ADMIN: frozenset({"*"}),
    settings.ROLE_OPERATOR: _OPERATOR_PERMISSIONS,
    settings.ROLE_VIEWER: frozenset({"view"}),
}


class PermissionDenied(PermissionError):
    """يُرفع عند محاولة إجراء غير مسموح للدور الحالي."""


# ============================================================
# 3) الاستعلامات
# ============================================================

def _role_of(user: Mapping[str, Any] | str | None) -> str:
    """يستخرج الدور من قاموس مستخدم أو نص دور."""
    if user is None:
        return settings.ROLE_VIEWER
    if isinstance(user, str):
        return user
    if isinstance(user, Mapping):
        return str(user.get("role") or settings.ROLE_VIEWER)
    role = getattr(user, "role", None)
    return str(role or settings.ROLE_VIEWER)


def permissions_for(role: str) -> frozenset[str]:
    """يعيد مجموعة صلاحيات الدور كما هي معرّفة."""
    return PERMISSIONS.get(str(role or ""), frozenset())


def has_permission(
    user: Mapping[str, Any] | str | None,
    permission: str,
) -> bool:
    """
    هل يملك المستخدم صلاحية معينة؟

    >>> has_permission({"role": "viewer"}, "mix.create")
    False
    >>> has_permission({"role": "admin"}, "users.manage")
    True
    """
    perm = str(permission or "").strip()
    if not perm:
        return False
    granted = permissions_for(_role_of(user))
    if "*" in granted or perm in granted:
        return True
    module = perm.split(".", 1)[0]
    return f"{module}.*" in granted or module in granted


def require_permission(
    user: Mapping[str, Any] | str | None,
    permission: str,
) -> None:
    """يرفع PermissionDenied إذا لم تكن الصلاحية متاحة."""
    if not has_permission(user, permission):
        raise PermissionDenied(f"لا تملك صلاحية تنفيذ هذا الإجراء ({permission})")


def can_manage_users(user: Mapping[str, Any] | str | None) -> bool:
    """إدارة المستخدمين مقصورة على admin."""
    return has_permission(user, "users.manage")


def can_edit_settings(user: Mapping[str, Any] | str | None) -> bool:
    """تعديل الإعدادات/النسخ الاحتياطي مقصور على admin."""
    return has_permission(user, "settings.edit")


def is_viewer(user: Mapping[str, Any] | str | None) -> bool:
    """هل الدور للقراءة فقط؟"""
    return _role_of(user) == settings.ROLE_VIEWER


def role_label(user: Mapping[str, Any] | str | None) -> str:
    """اسم الدور بالعربية للعرض في الشريط العلوي."""
    role = _role_of(user)
    return settings.ROLE_LABELS.get(role, role)
