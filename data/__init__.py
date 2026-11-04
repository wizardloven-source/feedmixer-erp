"""
data
----
طبقة الوصول إلى البيانات (repositories) مع SQLite.

الوحدات الأساسية:
    connection   : اتصال ومساعدات التنفيذ والاستعلام.
    schema       : CREATE TABLE + Indexes.
    migrations   : ترقيات الأعمدة (ALTER TABLE).
    seed         : البيانات الافتراضية (admin، مزارع، مواد، إعدادات).

مستودعات (repositories):
    settings_repo, farms_repo, materials_repo, purchases_repo,
    invoices_repo, payments_repo, recipes_repo, users_repo.

كل دالة في مستودع تُعيد dict/list[dict] وتسجّل الأخطاء عبر logging.
"""

__all__: list[str] = []
