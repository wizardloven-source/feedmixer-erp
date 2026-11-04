"""
services/backup_service.py
--------------------------
خدمة النسخ الاحتياطي والاسترجاع وفحص سلامة قاعدة البيانات.

الوظائف العامة:
    create_backup(dest_dir=None) -> str   : نسخة آمنة عبر sqlite3 «Backup API»
                                            (متوافقة حتى مع وجود اتصال مفتوح).
    list_backups() -> list[dict]          : أحدث النسخ في BACKUP_DIR.
    restore_backup(path) -> bool          : استرجاع آمن — ينشّط نسخة أمان
                                            تلقائياً قبل الاستبدال.
    check_integrity(quick=True) -> dict   : PRAGMA integrity_check / quick_check.

الأمان:
    - كل عملية تُسجَّل في audit_log (action=backup/restore/db_check).
    - لا ترفع الدوال استثناءات للمنادي إلا عند تعذّر العملية فعلياً؛
      تُستخدم logging لتفاصيل الأعطال.
"""

from __future__ import annotations

import datetime as _dt
import random as _random
import sqlite3
from pathlib import Path
from typing import Any

from config import settings
from core.logger import get_logger, log_audit
from data import connection

_log = get_logger("services.backup")

# امتداد موحّد لملفات النسخ حتى يلتقطها نافذ اختيار الملفات في تبويب الإعدادات
BACKUP_SUFFIX = ".db"


def _timestamp_name(prefix: str = "backup") -> str:
    """اسم ملف فريد مبني على التاريخ والوقت + بادئة عشوائية.

    الطابع الزمني وحده بدقة الثانية قد يتصادم عند إنشاء نسختين في
    نفس الثانية (مثلاً نسخة أساسية ثم نسخة الأمان داخل الاسترجاع)،
    لذا تُضاف لاحقة عشوائية قصيرة لضمان عدم الكتابة فوق نسخة قائمة.
    """
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = "".join(_random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))
    return f"{prefix}_{stamp}_{rand}{BACKUP_SUFFIX}"


def _checkpoint(path: Path) -> None:
    """يفتح قاعدة بيانات مؤقتاً لتشغيل PRAGMA wal_checkpoint(TRUNCATE).

    الهدف: دمج ملف WAL في ملف القاعدة الرئيسي قبل النسخ أو القياس،
    حتى لا تبقى المعاملات الأخيرة حبيسة في WAL يُحذف لاحقاً.
    """
    if not path.exists():
        return
    try:
        con = sqlite3.connect(str(path))
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            con.close()
    except sqlite3.Error as exc:
        _log.warning("تعذّر الدمج من WAL لـ %s: %s", path, exc)


def _cleanup_sidecars(path: Path) -> None:
    """يحذف ملفات WAL/SHM الجانبية التي قد يخلّفها الاتصال المؤقت."""
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:
            _log.warning("تعذّر حذف ملف جانبي: %s", sidecar)


def create_backup(dest_dir: str | Path | None = None) -> str:
    """ينشئ نسخة احتياطية من قاعدة البيانات ويعيد مسار الملف الجديد.

    يستخدم واجهة النسخ الرسمية في SQLite (Connection.backup) بدل نسخ
    الملف خاماً، لضمان اتساق البيانات حتى أثناء وجود جلسات مفتوحة.
    """
    settings.ensure_directories()
    target_dir = Path(dest_dir) if dest_dir else Path(settings.BACKUP_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _timestamp_name("backup")

    source_path = connection.database_path()
    src: sqlite3.Connection | None = None
    dst: sqlite3.Connection | None = None
    try:
        # 1) دمج WAL أولاً — اتصال readonly لن يرى المعاملات غير المدمجة
        _checkpoint(Path(source_path))
        src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        dst = sqlite3.connect(str(target))
        with dst:
            src.backup(dst)
        # إغلاق الوجهة قبل قياس الحجم — وبعد الإغلاق يُغلق الملف بحجمه النهائي
        dst.close()
        dst = None
        _cleanup_sidecars(target)  # لا نريد ملفات WAL/SHM بجانب نسخة مستقلة
        size = target.stat().st_size
        log_audit("INSERT", "audit_log_meta", record_id=None,
                  old_value=None, new_value={"backup": str(target), "bytes": size})
        _log.info("تم إنشاء نسخة احتياطية: %s (%d بايت)", target, size)
        return str(target)
    except Exception:
        # تنظيف جزئي عند الفشل ثم إعادة الرمي للمنادي ليُظهر Toast مناسب
        try:
            if target.exists():
                target.unlink()
        except OSError:
            _log.warning("تعذّر حذف ملف نسخة فاشل: %s", target)
        _log.exception("فشل إنشاء النسخة الاحتياطية من %s", source_path)
        raise
    finally:
        for con in (src, dst):
            if con is not None:
                try:
                    con.close()
                except sqlite3.Error:
                    pass


def list_backups(limit: int = 10) -> list[dict[str, Any]]:
    """يعيد قائمة بأحدث النسخ: {name, path, size, mtime} مرتبة الأحدث أولاً."""
    folder = Path(settings.BACKUP_DIR)
    items: list[dict[str, Any]] = []
    try:
        files = [p for p in folder.glob("*") if p.is_file() and _is_backup_main(p)]
    except OSError:
        _log.exception("تعذّر قراءة مجلد النسخ %s", folder)
        return items
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[: max(1, int(limit))]:
        try:
            st = p.stat()
            items.append({
                "name": p.name,
                "path": str(p),
                "size": st.st_size,
                "mtime": _dt.datetime.fromtimestamp(st.st_mtime)
                        .strftime("%Y-%m-%d %H:%M"),
            })
        except OSError:
            continue
    return items


def restore_backup(backup_path: str | Path) -> bool:
    """يستبدل قاعدة البيانات الحالية بالنسخة المختارة بعد تنشيط نسخة أمان.

    يعيد True عند النجاح. يرفض المسارات غير الموجودة أو التي ليست ملفات DB
    مقروءة بصيغة SQLite (عبر فحص الترويسة) لحماية المستخدم من خطأ الاختيار.
    """
    src = Path(backup_path)
    if not src.is_file():
        _log.error("ملف النسخة غير موجود: %s", src)
        return False
    if not _looks_like_sqlite(src):
        _log.error("الملف ليس قاعدة بيانات SQLite صالحة: %s", src)
        return False

    # 1) نسخة أمان من الحالة الحالية قبل أي تغيير
    safety = create_backup(dest_dir=settings.BACKUP_DIR)
    _log.info("نسخة الأمان قبل الاسترجاع: %s", safety)

    target_path = Path(connection.database_path())
    try:
        # دمج WAL الحالي أولاً حتى تُنسخ الحالة كاملة إلى نسخة الأمان،
        # ثم ندمج الملف المصدر (النسخة) قبل قراءته.
        _checkpoint(target_path)
        _checkpoint(src)
        src_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        dst_con = sqlite3.connect(str(target_path))
        try:
            with dst_con:
                src_con.backup(dst_con)
        finally:
            src_con.close()
            dst_con.close()
        # بعد الاستبدال نفحص السلامة مباشرة — أي خلل يمنع اعتبار العملية ناجحة
        post = check_integrity(quick=True)
        if not post.get("ok"):
            raise RuntimeError(f"فشل فحص السلامة بعد الاسترجاع: {post.get('result')}")
        log_audit("UPDATE", "database", record_id=None,
                  old_value={"snapshot": safety},
                  new_value={"restored_from": str(src)})
        _log.info("تم استرجاع قاعدة البيانات من %s", src)
        return True
    except Exception:
        _log.exception("فشل الاسترجاع من %s — نسخة الأمان محفوظة في %s", src, safety)
        # محاولة الرجوع لنسخة الأمان حتى لا يبقى النظام بحالة نصف-مسترجعة
        try:
            rescue_src = sqlite3.connect(f"file:{safety}?mode=ro", uri=True)
            rescue_dst = sqlite3.connect(str(target_path))
            with rescue_dst:
                rescue_src.backup(rescue_dst)
            rescue_src.close()
            rescue_dst.close()
            _log.info("تمت إعادة الحالة الأصلية من نسخة الأمان بنجاح")
        except Exception:
            _log.exception("فشلت أيضاً إعادة الحالة من نسخة الأمان %s", safety)
        return False
    finally:
        # تنظيف ملفات WAL/SHM الجانبية التي قد يخلّفها الاتصال المؤقت
        _cleanup_sidecars(target_path)
        _cleanup_sidecars(src)
        try:
            from core import cache

            cache.invalidate_all()
        except Exception:  # noqa: BLE001
            pass


def check_integrity(quick: bool = True) -> dict[str, Any]:
    """يفحص سلامة قاعدة البيانات ويعيد تقريراً قابلاً للعرض.

    الصيغة: {"ok": bool, "result": str, "table_count": int, "checked_at": str}
    """
    sql = "PRAGMA quick_check" if quick else "PRAGMA integrity_check"
    report: dict[str, Any] = {
        "ok": False,
        "result": "",
        "table_count": 0,
        "checked_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        rows = connection.query_all(sql, ())
        # query_all قد يرجع قواميس أو صفوفات تبعاُ لإعداد الطبقة — نتعامل مع الحالتين
        cleaned: list[str] = []
        for r in rows:
            if isinstance(r, dict):
                vals = list(r.values())
                cleaned.append(str(vals[0]) if vals else "")
            elif isinstance(r, (list, tuple)):
                cleaned.append(str(r[0]) if r else "")
            else:
                cleaned.append(str(r))
        joined = " ; ".join(c for c in cleaned if c)
        report["result"] = joined
        report["ok"] = joined.strip().lower() == "ok"
        count_row = connection.query_one(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
            ())
        if isinstance(count_row, dict):
            report["table_count"] = int(count_row.get("c", 0))
        elif isinstance(count_row, (list, tuple)) and count_row:
            report["table_count"] = int(count_row[0])
    except Exception as exc:  # noqa: BLE001
        _log.exception("فشل فحص سلامة قاعدة البيانات")
        report["result"] = f"خطأ: {exc}"
    log_audit("CHECK", "database", record_id=None, old_value=None, new_value=report)
    return report


def _looks_like_sqlite(path: Path) -> bool:
    """يتحقق من ترويسة SQLite القياسية «SQLite format 3\\x00»."""
    try:
        with path.open("rb") as fh:
            header = fh.read(16)
        return header.startswith(b"SQLite format 3")
    except OSError:
        return False


def _is_backup_main(path: Path) -> bool:
    """ملف نسخة رئيسي صالح — يستبعد ملفات WAL/SHM الجانبية."""
    name = path.name.lower()
    if name.endswith(("-wal", "-shm", "-journal")):
        return False
    return path.suffix.lower() in (".db", ".sqlite", ".bak") or not path.suffix


def prune_old_backups(keep: int = 20) -> int:
    """يحذف النسخ الأقدم من `keep` ويعيد عدد المحذوفات (استدعاء اختياري)."""
    removed = 0
    backups = list_backups(limit=10_000)
    for item in backups[max(1, int(keep)):]:
        try:
            Path(item["path"]).unlink()
            removed += 1
        except OSError:
            _log.warning("تعذّر حذف نسخة قديمة: %s", item.get("path"))
    if removed:
        _log.info("تم تنظيف %d نسخة قديمة", removed)
    return removed
