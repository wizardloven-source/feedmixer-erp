"""
services/inventory_service.py
-----------------------------
حساب أرصدة المخزون للمواد.

القاعدة المعتمدة في النظام:
    المتبقي (طن) = المورد (Σ توريدات) - المستهلك (Σ بنود الخلطات غير المحذوفة)

ملاحظات:
    * بنود الخلطات مخزّنة بالكيلوغرام (qty_kg) بينما التوريدات بالأطنان،
      لذلك تُحوَّل كل الكميات إلى أطنان قبل الطرح.
    * الفواتير المكشوفة محذوفاً (soft delete, is_deleted=1) لا تُحتسب
      ضمن الاستهلاك لأنها قابلة للاسترجاع.
    * النتائج تُخزَّن في كاش قصير العمر (core.cache) لتفادي تكرار
      استعلامات JOIN الثقيلة عند تحديث الواجهة.

إصلاح المرحلة 3: حُذفت الدالة الوهمية set_manual_remaining() نهائياً —
كانت ترجع False دائماً بلا أي أثر فعلي، واستدعاؤها الوحيد كان من
adjust_quantity في ui/tabs/inventory.py (حُذفت هي الأخرى). المتبقي يبقى
محسوباً دائماً من (المورد − المستهلك) للحفاظ على سلامة البيانات.
"""

from __future__ import annotations

from typing import Any

from config import settings
from core import cache
from core.logger import get_logger
from core.utils import kg_to_tons, round_qty
from data.connection import execute, query_all, query_one

log = get_logger("services.inventory")


# ============================================================
# الحساب الخام (بدون كاش)
# ============================================================

def _load_balances() -> list[dict[str, Any]]:
    """
    يحسب رصيد كل مادة معرَّفة في جدول materials مباشرة من قاعدة البيانات.

    يعيد قائمة قوامها:
        {name, unit_type, supplied_ton, consumed_ton, remaining_ton, missing}
    حيث `missing` = كميات استُخدمت في خلطات/توريدات لمادة غير مسجَّلة
    في جدول المواد (بيانات يتيماء يجب تنبيه المستخدم إليها).
    """
    try:
        supply_rows = query_all(
            "SELECT material_name, COALESCE(SUM(qty_ton), 0) AS total"
            " FROM purchases GROUP BY material_name"
        )
        consume_rows = query_all(
            "SELECT mi.material_name, COALESCE(SUM(mi.qty_kg), 0) AS total_kg"
            " FROM mix_items mi"
            " JOIN mix_invoices mv ON mv.mix_number = mi.mix_number"
            " WHERE COALESCE(mv.is_deleted, 0) = 0"
            " GROUP BY mi.material_name"
        )
        material_rows = query_all(
            "SELECT name, unit_type FROM materials ORDER BY name"
        )
    except Exception:
        log.exception("فشل حساب أرصدة المخزون")
        return []

    supplied = {str(r.get("material_name") or ""): float(r.get("total") or 0.0)
                for r in supply_rows}
    consumed_kg = {str(r.get("material_name") or ""): float(r.get("total_kg") or 0.0)
                   for r in consume_rows}

    result: list[dict[str, Any]] = []
    known_names: set[str] = set()
    for m in material_rows:
        name = str(m.get("name") or "")
        known_names.add(name)
        sup = supplied.get(name, 0.0)
        con = kg_to_tons(consumed_kg.get(name, 0.0))
        remaining = round_qty(sup - con)
        result.append({
            "name": name,
            "unit_type": str(m.get("unit_type") or "ton"),
            "supplied_ton": round_qty(sup),
            "consumed_ton": round_qty(con),
            "remaining_ton": remaining,
            "low": remaining < settings.LOW_STOCK_THRESHOLD_TONS,
            "negative": remaining < 0,
        })

    # بيانات يتيماء: مواد وردت في حركة المخزون لكنها غير مسجلة في materials
    orphan_names = (set(supplied) | set(consumed_kg)) - known_names
    for name in sorted(n for n in orphan_names if n):
        sup = supplied.get(name, 0.0)
        con = kg_to_tons(consumed_kg.get(name, 0.0))
        remaining = round_qty(sup - con)
        result.append({
            "name": name,
            "unit_type": "؟",
            "supplied_ton": round_qty(sup),
            "consumed_ton": round_qty(con),
            "remaining_ton": remaining,
            "low": True,
            "negative": remaining < 0,
            "missing": True,
        })

    return result


# ============================================================
# واجهة القراءة العامة (مع كاش)
# ============================================================

_CACHE_KEY = "inventory:balances"
_CACHE_TTL = 30.0


def inventory_balances(force_refresh: bool = False) -> list[dict[str, Any]]:
    """أرصدة كل المواد (مورد/مستهلك/متبقي) بوحدة الطن."""
    return cache.get_or_load(_CACHE_KEY, _load_balances,
                             ttl=_CACHE_TTL, force=force_refresh)


def balance_of(material_name: str) -> float:
    """المتبقي بوحدة الطن لمادة واحدة (0.0 إن لم توجد)."""
    target = str(material_name or "").strip()
    for row in inventory_balances():
        if str(row.get("name")) == target:
            return float(row.get("remaining_ton", 0.0))
    return 0.0


def available_kg(material_name: str) -> float:
    """المتبقي بالكيلوغرام — يُستخدم في فحوص عجز الخلطات."""
    return balance_of(material_name) * settings.KG_PER_TON


def low_stock_items(threshold_tons: float | None = None) -> list[dict[str, Any]]:
    """الأصناف التي دون حد التنبيه (افتراضياً LOW_STOCK_THRESHOLD_TONS)."""
    limit = (settings.LOW_STOCK_THRESHOLD_TONS
             if threshold_tons is None else float(threshold_tons))
    return [r for r in inventory_balances()
            if float(r.get("remaining_ton", 0.0)) < limit]


def negative_stock_items() -> list[dict[str, Any]]:
    """الأصناف برصيد سالب (استهلاك تجاوز التوريد - حالة شاذة تستحق المتابعة)."""
    return [r for r in inventory_balances()
            if float(r.get("remaining_ton", 0.0)) < 0]


def summary_totals() -> dict[str, float]:
    """إجماليات لوحة التحكم: مورد / مستهلك / متبقٍ / عدد الأصناف المنخفضة."""
    rows = inventory_balances()
    supplied = sum(float(r.get("supplied_ton", 0.0)) for r in rows)
    consumed = sum(float(r.get("consumed_ton", 0.0)) for r in rows)
    remaining = sum(float(r.get("remaining_ton", 0.0)) for r in rows)
    return {
        "materials_count": len(rows),
        "supplied_ton": round_qty(supplied),
        "consumed_ton": round_qty(consumed),
        "remaining_ton": round_qty(remaining),
        "low_count": sum(1 for r in rows if r.get("low")),
        "negative_count": sum(1 for r in rows if r.get("negative")),
    }


def invalidate() -> None:
    """إبطال كاش المخزون — تُستدعى بعد كل عملية توريد/خلطة/حذف."""
    cache.invalidate(_CACHE_KEY)

# ملاحظة: كانت هنا الدالة set_manual_remaining() — حُذفت في المرحلة 3
# لأنها وهمية (ترجع False دائماً) واستدعاؤها الوحيد كان من كود ميت.
# التسوية اليدوية للمخزون تتم عبر تسجيل توريد/خصم حقيقي في الفواتير
# وليس بتجاوز الحساب التلقائي — وهذا يحمي سلامة البيانات (Audit Trail).
