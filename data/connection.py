"""
data/connection.py
-----------------
طبقة الاتصال بـ SQLite (نقطة دخول وحيدة لقاعدة البيانات).

- set_database_path : تحديد مسار DB (يُستخدم في app.py والـ tests).
- get_connection     : اتصال مع row_factory=Row و foreign_keys=ON.
- execute            : تنفيذ + commit مع معالجة أخطاء.
- query_all / query_one : استعلامات قراءة تُعيد dict/list[dict].
- transaction        : context manager لعمليات متعددة.
- rows_to_dicts      : تحويل sqlite3.Row إلى dict.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Any, Iterator

from config import settings

_log = logging.getLogger("mixer.connection")

_DB_PATH: str | None = None


def set_database_path(path: str | None) -> None:
    """تحديد مسار قاعدة البيانات (يُستدعى قبل init_database)."""
    global _DB_PATH
    _DB_PATH = None if path is None else str(path)


def _resolve_path() -> str:
    return _DB_PATH if _DB_PATH else str(settings.DB_PATH)


def get_connection() -> sqlite3.Connection:
    """
    يُنشئ اتصالاً جديداً بـ SQLite مع الإعدادات المناسبة.
    (لا تُستخدم connection مشتركة بين الخيوط — Tkinter خيط واحد.)
    """
    conn = sqlite3.connect(
        _resolve_path(),
        timeout=30.0,
        check_same_thread=False,
        isolation_level=None,  # ندير المعاملات يدوياً
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as exc:
        _log.warning("تعذر ضبط PRAGMA: %s", exc)
    return conn


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    """تحويل iterable من sqlite3.Row إلى list[dict]."""
    if rows is None:
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            result.append({key: row[key] for key in row.keys()})
        except Exception:  # noqa: BLE001 - صف غير قياسي
            try:
                result.append(dict(row))
            except Exception:  # noqa: BLE001
                result.append({"value": row})
    return result


def row_to_dict(row: Any) -> dict[str, Any] | None:
    """تحويل صف واحد إلى dict أو None."""
    if row is None:
        return None
    dicts = rows_to_dicts([row])
    return dicts[0] if dicts else None


def execute(
    sql: str,
    params: tuple[Any, ...] | list[Any] | dict[str, Any] = (),
    *,
    commit: bool = True,
    connection: sqlite3.Connection | None = None,
) -> sqlite3.Cursor:
    """
    يُنفّذ عبارة SQL (INSERT/UPDATE/DELETE/DDL) ويلتزم (commit) افتراضياً.
    يُعيد cursor (lastrowid متاح). عند الفشل يُسجّل الخطأ ويُعيد رفعه.
    """
    owns_connection = connection is None
    conn = connection or get_connection()
    try:
        cursor = conn.execute(sql, params)
        if commit and owns_connection:
            conn.commit()
        return cursor
    except sqlite3.Error as exc:
        if owns_connection:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        _log.error("SQL error: %s | sql=%s | params=%r", exc, sql, params)
        raise
    finally:
        if owns_connection:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def query_all(
    sql: str,
    params: tuple[Any, ...] | list[Any] | dict[str, Any] = (),
    *,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """استعلام SELECT يُعيد قائمة dict."""
    owns_connection = connection is None
    conn = connection or get_connection()
    try:
        cursor = conn.execute(sql, params)
        return rows_to_dicts(cursor.fetchall())
    except sqlite3.Error as exc:
        _log.error("SQL query error: %s | sql=%s", exc, sql)
        return []
    finally:
        if owns_connection:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def query_one(
    sql: str,
    params: tuple[Any, ...] | list[Any] | dict[str, Any] = (),
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """استعلام SELECT يُعيد dict واحد أو None."""
    rows = query_all(sql, params, connection=connection)
    return rows[0] if rows else None


def fetch_scalar(
    sql: str,
    params: tuple[Any, ...] | list[Any] = (),
    default: Any = None,
) -> Any:
    """استعلام يُعيد قيمة واحدة (العمود الأول من أول صف)."""
    row = query_one(sql, params)
    if not row:
        return default
    try:
        return next(iter(row.values()))
    except StopIteration:
        return default


def table_exists(table_name: str) -> bool:
    """هل الجدول موجود في قاعدة البيانات؟"""
    row = query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return row is not None


def table_columns(table_name: str) -> list[str]:
    """قائمة أعمدة جدول (PRAGMA table_info)."""
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            return [row["name"] for row in cursor.fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


@contextlib.contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """
    context manager لعدة عمليات في معاملة واحدة:
        with transaction() as conn:
            execute("INSERT ...", ..., connection=conn, commit=False)
            execute("UPDATE ...", ..., connection=conn, commit=False)
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def database_path() -> str:
    """المسار الفعلي لقاعدة البيانات (للنسخ الاحتياطي/التشخيص)."""
    return _resolve_path()
