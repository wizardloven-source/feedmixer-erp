"""
config
------
حزمة الإعدادات المركزية للتطبيق.

تُستخدم كالتالي:
    from config import settings
    settings.COLORS["primary"]
    settings.get_colors(dark=True)
"""

from config import settings

__all__ = ["settings"]
