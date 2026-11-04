"""
data/schema.py
--------------
إنشاء مخطط قاعدة البيانات (CREATE TABLE + Indexes).

init_database() يُستدعى مرة واحدة при بدء التطبيق (idempotent:
CREATE TABLE IF NOT EXISTS)، كما يُفعّل foreign_keys.

الجداول (11): audit_log, users, farms, materials, purchases,
mix_invoices, mix_items, payments, recipes, recipe_items, settings.
"""

from __future__ import annotations

from core.logger import get_logger
from data.connection import execute, get_connection

_log = get_logger("mixer.schema")


_DDL_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        action      TEXT    NOT NULL,
        table_name  TEXT    NOT NULL,
        record_id   TEXT,
        old_value   TEXT,
        new_value   TEXT,
        timestamp   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
        user        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        username       TEXT    NOT NULL UNIQUE,
        password_hash  TEXT    NOT NULL,
        salt           TEXT    NOT NULL,
        role           TEXT    NOT NULL DEFAULT 'viewer',
        full_name      TEXT,
        is_active      INTEGER NOT NULL DEFAULT 1,
        created_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS farms (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT    NOT NULL UNIQUE,
        transport_fee  REAL    NOT NULL DEFAULT 0,
        is_archived    INTEGER NOT NULL DEFAULT 0,
        phone          TEXT,
        notes          TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS materials (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT    NOT NULL UNIQUE,
        base_price    REAL    NOT NULL DEFAULT 0,
        handling_fee  REAL    NOT NULL DEFAULT 0,
        loss_fee      REAL    NOT NULL DEFAULT 0,
        unit_type     TEXT    NOT NULL DEFAULT 'ton'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS purchases (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_date      TEXT    NOT NULL,
        material_name      TEXT    NOT NULL,
        qty_ton            REAL    NOT NULL DEFAULT 0,
        supplier           TEXT,
        details            TEXT,
        price_per_ton      REAL    NOT NULL DEFAULT 0,
        total_cost         REAL    NOT NULL DEFAULT 0,
        unloading_fee      REAL    NOT NULL DEFAULT 0,
        handling_fee       REAL    NOT NULL DEFAULT 0,
        transport_fee      REAL    NOT NULL DEFAULT 0,
        other_fees         REAL    NOT NULL DEFAULT 0,
        fees_total         REAL    NOT NULL DEFAULT 0,
        real_price_per_ton REAL    NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mix_invoices (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        mix_number              TEXT    NOT NULL UNIQUE,
        mix_date                TEXT    NOT NULL,
        farm_name               TEXT    NOT NULL,
        worker_name             TEXT,
        total_weight            REAL    NOT NULL DEFAULT 0,
        total_cost              REAL    NOT NULL DEFAULT 0,
        mixer_net_cost          REAL    NOT NULL DEFAULT 0,
        payment_status          TEXT    NOT NULL DEFAULT 'unpaid',
        notes                   TEXT,
        elec_fee                REAL    NOT NULL DEFAULT 0,
        labor_fee               REAL    NOT NULL DEFAULT 0,
        transport_fee           REAL    NOT NULL DEFAULT 0,
        billable_tons           REAL    NOT NULL DEFAULT 0,
        net_cost_manually_edited INTEGER NOT NULL DEFAULT 0,
        is_deleted              INTEGER NOT NULL DEFAULT 0,
        deleted_at              TEXT,
        recipe_id               INTEGER,
        created_by              TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mix_items (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        mix_number    TEXT    NOT NULL,
        material_name TEXT    NOT NULL,
        qty_kg        REAL    NOT NULL DEFAULT 0,
        unit_price    REAL    NOT NULL DEFAULT 0,
        total_price   REAL    NOT NULL DEFAULT 0,
        FOREIGN KEY (mix_number) REFERENCES mix_invoices(mix_number) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        farm_name     TEXT    NOT NULL,
        payment_date  TEXT    NOT NULL,
        amount        REAL    NOT NULL DEFAULT 0,
        method        TEXT    NOT NULL DEFAULT 'cash',
        reference     TEXT,
        notes         TEXT,
        created_by    TEXT,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recipes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL UNIQUE,
        farm_name   TEXT,
        notes       TEXT,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recipe_items (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id     INTEGER NOT NULL,
        material_name TEXT    NOT NULL,
        qty_kg        REAL    NOT NULL DEFAULT 0,
        FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key          TEXT PRIMARY KEY,
        value        REAL,
        description  TEXT
    )
    """,
)

_DDL_INDEXES: tuple[str, ...] = (
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


def init_database() -> None:
    """
    يُنشئ كل الجداول والفهارس إن لم تكن موجودة.
    آمن للنداء المتكرر (idempotent).
    """
    try:
        conn = get_connection()
        try:
            conn.execute("BEGIN")
            for ddl in _DDL_TABLES:
                conn.execute(ddl)
            for ddl in _DDL_INDEXES:
                conn.execute(ddl)
            conn.commit()
            _log.info("تم تهيئة مخطط قاعدة البيانات (%d جدول)", len(_DDL_TABLES))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل تهيئة قاعدة البيانات: %s", exc)
        raise
