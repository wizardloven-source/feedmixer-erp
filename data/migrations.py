"""
data/migrations.py
------------------
ترقيات مخطط قاعدة البيانات (ALTER TABLE) للأعمدة التي تمت إضافتها
في إصدارات لاحقة، بهدف دعم bases قديمة (v1/v2) دون فقد بيانات.

run_migrations() idempotent: كل عمود يُضاف فقط إن كان غائباً.
"""

from __future__ import annotations

from core.logger import get_logger
from data.connection import execute, get_connection, table_columns

_log = get_logger("mixer.migrations")


# (الجدول, العمود, تعريف SQL)
_REQUIRED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # purchases
    ("purchases", "unloading_fee", "REAL NOT NULL DEFAULT 0"),
    ("purchases", "handling_fee", "REAL NOT NULL DEFAULT 0"),
    ("purchases", "transport_fee", "REAL NOT NULL DEFAULT 0"),
    ("purchases", "other_fees", "REAL NOT NULL DEFAULT 0"),
    ("purchases", "fees_total", "REAL NOT NULL DEFAULT 0"),
    ("purchases", "real_price_per_ton", "REAL NOT NULL DEFAULT 0"),
    ("purchases", "price_per_ton", "REAL NOT NULL DEFAULT 0"),
    ("purchases", "total_cost", "REAL NOT NULL DEFAULT 0"),
    # mix_invoices
    ("mix_invoices", "elec_fee", "REAL NOT NULL DEFAULT 0"),
    ("mix_invoices", "labor_fee", "REAL NOT NULL DEFAULT 0"),
    ("mix_invoices", "transport_fee", "REAL NOT NULL DEFAULT 0"),
    ("mix_invoices", "billable_tons", "REAL NOT NULL DEFAULT 0"),
    ("mix_invoices", "net_cost_manually_edited", "INTEGER NOT NULL DEFAULT 0"),
    ("mix_invoices", "is_deleted", "INTEGER NOT NULL DEFAULT 0"),
    ("mix_invoices", "deleted_at", "TEXT"),
    ("mix_invoices", "recipe_id", "INTEGER"),
    ("mix_invoices", "created_by", "TEXT"),
    ("mix_invoices", "mixer_net_cost", "REAL NOT NULL DEFAULT 0"),
    ("mix_invoices", "total_cost", "REAL NOT NULL DEFAULT 0"),
    ("mix_invoices", "payment_status", "TEXT NOT NULL DEFAULT 'unpaid'"),
    # mix_items (جديد: تتبع تجميد السعر)
    ("mix_items", "price_snapshot_at", "TEXT"),
    ("mix_items", "unit_price", "REAL NOT NULL DEFAULT 0"),
    ("mix_items", "total_price", "REAL NOT NULL DEFAULT 0"),
    # payments
    ("payments", "created_by", "TEXT"),
    ("payments", "created_at", "TEXT"),
    ("payments", "reference", "TEXT"),
    ("payments", "notes", "TEXT"),
    ("payments", "method", "TEXT NOT NULL DEFAULT 'cash'"),
    # farms
    ("farms", "is_archived", "INTEGER NOT NULL DEFAULT 0"),
    ("farms", "phone", "TEXT"),
    ("farms", "notes", "TEXT"),
    ("farms", "transport_fee", "REAL NOT NULL DEFAULT 0"),
    # materials
    ("materials", "handling_fee", "REAL NOT NULL DEFAULT 0"),
    ("materials", "loss_fee", "REAL NOT NULL DEFAULT 0"),
    ("materials", "unit_type", "TEXT NOT NULL DEFAULT 'ton'"),
    # users
    ("users", "full_name", "TEXT"),
    ("users", "is_active", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "created_at", "TEXT"),
    # recipes
    ("recipes", "farm_name", "TEXT"),
    ("recipes", "notes", "TEXT"),
    ("recipes", "created_at", "TEXT"),
)


def _add_column(table: str, column: str, definition: str) -> bool:
    """يضيف عموداً إن كان غائباً. يُعيد True عند الإضافة."""
    existing = table_columns(table)
    if column in existing:
        return False
    if table not in {t for t, _, _ in _REQUIRED_COLUMNS} and not existing:
        # جدول غير موجود - تخطّ (schema.py يُنشئه)
        return False
    try:
        execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}", commit=True)
        _log.info("تمت إضافة العمود %s.%s", table, column)
        return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("تعذر إضافة %s.%s: %s", table, column, exc)
        return False


def run_migrations() -> None:
    """
    يُطبّق كل الترقيات (idempotent). لا يرفع استثناء: فشل ترقية
    عمود واحد لا يمنع بقية الترقيات.
    """
    applied = 0
    skipped = 0
    failed = 0
    for table, column, definition in _REQUIRED_COLUMNS:
        # تخطّ الجداول غير الموجودة (schema.py يُنشئها لاحقاً/سابقاً)
        from data.connection import table_exists

        if not table_exists(table):
            skipped += 1
            continue
        try:
            if _add_column(table, column, definition):
                applied += 1
            else:
                skipped += 1
        except Exception:  # noqa: BLE001
            failed += 1
    _log.info(
        "الترقيات: %d مُطبَّقة، %d مُتجاهَلة، %d فاشلة",
        applied,
        skipped,
        failed,
    )
    # فهرسة إضافية (idempotent) لقواعد قديمة
    _ensure_indexes()
    # تعبئة أسعار البنود القديمة (مرة واحدة فقط)
    _backfill_mix_item_prices()


def _ensure_indexes() -> None:
    """يضمن وجود الفهارس (لقواعد قديمة قبل v3)."""
    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_purchases_material ON purchases(material_name)",
        "CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(purchase_date)",
        "CREATE INDEX IF NOT EXISTS idx_mix_items_material ON mix_items(material_name)",
        "CREATE INDEX IF NOT EXISTS idx_mix_invoices_date ON mix_invoices(mix_date)",
        "CREATE INDEX IF NOT EXISTS idx_mix_invoices_farm ON mix_invoices(farm_name)",
        "CREATE INDEX IF NOT EXISTS idx_mix_invoices_deleted ON mix_invoices(is_deleted)",
        "CREATE INDEX IF NOT EXISTS idx_payments_farm ON payments(farm_name)",
        "CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date)",
        "CREATE INDEX IF NOT EXISTS idx_mix_items_invoice ON mix_items(mix_number)",
        "CREATE INDEX IF NOT EXISTS idx_recipe_items_recipe ON recipe_items(recipe_id)",
    )
    conn = None
    try:
        conn = get_connection()
        conn.execute("BEGIN")
        for ddl in indexes:
            conn.execute(ddl)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        _log.warning("تعذر ضمان الفهارس: %s", exc)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _backfill_mix_item_prices() -> None:
    """
    يملأ unit_price/total_price للبنود القديمة التي قيمتها 0
    (قواعد v1/v2 قبل إضافة التجميد).
    يعتمد على آخر real_price_per_ton متاح لكل مادة.
    """
    conn = None
    try:
        conn = get_connection()
        rows = conn.execute("""
            SELECT mi.id, mi.material_name, mi.qty_kg
            FROM mix_items mi
            WHERE (mi.unit_price IS NULL OR mi.unit_price = 0)
              AND mi.qty_kg > 0
        """).fetchall()

        if not rows:
            return

        updated = 0
        for r in rows:
            price_row = conn.execute("""
                SELECT real_price_per_ton FROM purchases
                WHERE material_name = ? AND real_price_per_ton > 0
                ORDER BY purchase_date DESC, id DESC LIMIT 1
            """, (r["material_name"],)).fetchone()
            if not price_row or not price_row[0]:
                continue
            unit = float(price_row[0]) / 1000.0
            total = float(r["qty_kg"]) * unit
            conn.execute("""
                UPDATE mix_items
                SET unit_price = ?, total_price = ?,
                    price_snapshot_at = 'BACKFILL'
                WHERE id = ?
            """, (unit, total, r["id"]))
            updated += 1

        if updated:
            conn.execute("""
                UPDATE mix_invoices
                SET total_cost = (
                    SELECT COALESCE(SUM(total_price), 0) FROM mix_items
                    WHERE mix_items.mix_number = mix_invoices.mix_number
                )
                WHERE total_cost = 0
                  AND EXISTS (SELECT 1 FROM mix_items
                              WHERE mix_items.mix_number = mix_invoices.mix_number)
            """)
        conn.commit()
        if updated:
            _log.info("backfill mix_items: تم تحديث %d بنداً", updated)
    except Exception as exc:  # noqa: BLE001
        _log.warning("تعذر backfill mix_items: %s", exc)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass