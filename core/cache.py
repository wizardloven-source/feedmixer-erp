"""
core/cache.py
-------------
كاش خفيف في الذاكرة للمواد والإعدادات والمزارع لتقليل استعلامات SQLite
على العمليات المتكررة (شاشة الخلطة تطلب الأسعار عشرات المرات).

المبادئ:
- مفتاح -> (وقت الانتهاء، القيمة).
- TTL افتراضي 60 ثانية، ويمكن إبطال الكاش فوراً بعد أي كتابة.
- كل محمّل (loader) يُستورد كسولاً من data/ لتجنب الاستيراد الدوري.
"""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

DEFAULT_TTL: float = 60.0
FOREVER: float = float("inf")

_store: dict[str, tuple[float, Any]] = {}


# ============================================================
# النواة
# ============================================================

def get_or_load(
    key: str,
    loader: Callable[[], T],
    ttl: float = DEFAULT_TTL,
    force: bool = False,
) -> T:
    """
    يعيد القيمة المخزنة إن كانت صالحة، وإلا ينفّذ loader ويخزّن الناتج.
    ttl <= 0 يعني تخزيناً بلا انتهاء (حتى إبطال يدوي).
    """
    now = time.monotonic()
    if not force and key in _store:
        expires_at, value = _store[key]
        if expires_at > now:
            return value  # type: ignore[return-value]

    value = loader()
    _store[key] = (now + ttl if ttl > 0 else FOREVER, value)
    return value


def invalidate(*keys: str) -> None:
    """يبطل مفاتيح محددة."""
    for key in keys:
        _store.pop(key, None)


def invalidate_prefix(prefix: str) -> None:
    """يبطل كل المفاتيح التي تبدأ بمقطع معيّن."""
    for key in [k for k in _store if k.startswith(prefix)]:
        _store.pop(key, None)


def invalidate_all() -> None:
    """يفرغ الكاش بالكامل (بعد استعادة نسخة احتياطية مثلاً)."""
    _store.clear()


def stats() -> dict[str, int]:
    """معلومات تشخيصية لعرضها في تبويب الإعدادات."""
    return {"entries": len(_store)}


# ============================================================
# المواد
# ============================================================

def materials(force: bool = False) -> list[dict[str, Any]]:
    """قائمة المواد كاملة (dict) من الكاش."""
    from data.materials_repo import list_materials

    return get_or_load("materials", list_materials, force=force)


def material_map(force: bool = False) -> dict[str, dict[str, Any]]:
    """خريطة اسم المادة -> بياناتها."""
    return get_or_load(
        "materials_map",
        lambda: {row["name"]: row for row in materials(force=force)},
        force=force,
    )


def material_names(force: bool = False) -> list[str]:
    """أسماء المواد فقط (لتعبئة القوائم المنسدلة)."""
    return [row["name"] for row in materials(force=force)]


def invalidate_materials() -> None:
    """يُستدعى بعد أي تعديل على جدول materials أو purchases."""
    invalidate("materials", "materials_map")


# ============================================================
# الإعدادات
# ============================================================

def all_settings(force: bool = False) -> dict[str, float]:
    """كل الإعدادات كقاموس key -> value."""
    from data.settings_repo import get_all_settings

    return get_or_load("settings", get_all_settings, ttl=0.0, force=force)


def setting(key: str, default: float = 0.0, force: bool = False) -> float:
    """قيمة إعداد واحد مع قيمة افتراضية عند الغياب."""
    from config import settings as app_settings

    fallback = default
    if key in app_settings.DEFAULT_SETTINGS:
        fallback = app_settings.DEFAULT_SETTINGS[key][0]
    try:
        value = all_settings(force=force).get(key, fallback)
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def invalidate_settings() -> None:
    """يُستدعى بعد set_setting."""
    invalidate("settings")


# ============================================================
# المزارع
# ============================================================

def farms(include_archived: bool = False, force: bool = False) -> list[dict[str, Any]]:
    """قائمة المزارع (نشطة فقط افتراضياً)."""
    from data.farms_repo import list_farms

    key = f"farms:{int(bool(include_archived))}"
    return get_or_load(
        key,
        lambda: list_farms(include_archived=include_archived),
        force=force,
    )


def farm_names(include_archived: bool = False, force: bool = False) -> list[str]:
    """أسماء المزارع فقط."""
    return [row["name"] for row in farms(include_archived=include_archived, force=force)]


def farm_map(include_archived: bool = False, force: bool = False) -> dict[str, dict[str, Any]]:
    """خريطة اسم المزرعة -> بياناتها (لأجرة النقل)."""
    return {
        row["name"]: row
        for row in farms(include_archived=include_archived, force=force)
    }


def invalidate_farms() -> None:
    """يُستدعى بعد أي تعديل على جدول farms."""
    invalidate_prefix("farms:")
