"""
app.py
------
نقطة انطلاق FeedMixer ERP v3.0.

التسلسل:
    1) تهيئة التسجيل (logs/app.log).
    2) تجهيز قاعدة البيانات: schema + migrations + seed.
    3) عرض نافذة تسجيل الدخول (LoginDialog).
    4) فتح النافذة الرئيسية مع المستخدم المسجّل.

التشغيل:  python app.py
"""

from __future__ import annotations

import sys

from config import settings
from core.logger import get_logger, set_current_user, setup_logging
from data.connection import set_database_path
from data.migrations import run_migrations
from data.schema import init_database
from data.seed import seed_defaults


def _prepare_database() -> None:
    """يُنشئ المجلدات والجداول ويطبّق الترقيات ويزرع البيانات الافتراضية."""
    settings.ensure_directories()
    set_database_path(settings.DB_PATH)
    init_database()
    run_migrations()
    seed_defaults()


def main() -> int:
    """يشغّل التطبيق بالكامل ويعيد رمز الخروج."""
    setup_logging()
    log = get_logger("app")
    try:
        _prepare_database()
    except Exception:
        log.exception("فشل تجهيز قاعدة البيانات - لا يمكن بدء التطبيق")
        return 1

    import tkinter as tk

    from ui.login import LoginDialog
    from ui.main_window import FeedMixerERP

    root = tk.Tk()
    root.withdraw()
    login = LoginDialog(root)
    root.wait_window(login)
    user = login.user
    root.destroy()

    if not user:
        log.info("تم إلغاء تسجيل الدخول - إنهاء التطبيق")
        return 0

    set_current_user(str(user.get("username", "")))
    log.info("بدء الجلسة للمستخدم: %s (%s)", user.get("username"), user.get("role"))
    FeedMixerERP(user).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
