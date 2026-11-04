"""
reports/exporter.py
-------------------
تصدير الجداول إلى ملفات CSV و Excel (xlsx).

الوظائف العامة:
    export_csv(headers, rows, filename_prefix)        -> Path
    export_excel(headers, rows, filename_prefix)      -> Path
    export_table(headers, rows, filename_prefix, as_excel=True) -> Path
    export_query(sql, params, filename_prefix)        -> Path  (من SQLite مباشرة)

الملاحظات:
    - CSV بترميز utf-8-sig حتى يفتح العربية بشكل سليم في Excel.
    - Excel عبر openpyxl (اختياري)؛ عند غيابه ترفع ImportError برسالة عربية.
    - كل الملفات تُحفظ في settings.EXPORT_DIR مع طابع زمني فريد.
"""

from __future__ import annotations

import csv
import datetime as _dt
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from config import settings

_log = logging.getLogger("reports.exporter")

_UNSAFE = re.compile(r"[^\w\u0600-\u06FF-]+")


def _stamp() -> str:
    """طابع زمني قصير يُضاف لأسماء الملفات."""
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(filename_prefix: str) -> str:
    """تنظيف بادئة اسم الملف إلى أحرف آمنة (عربي/إنجليزي/أرقام)."""
    cleaned = _UNSAFE.sub("_", str(filename_prefix or "export")).strip("_")
    return cleaned[:60] or "export"


def _output_path(filename_prefix: str, ext: str) -> Path:
    """يبني مساراً فريداً داخل EXPORT_DIR ويضمن وجود المجلد."""
    settings.ensure_directories()
    name = f"{_safe_name(filename_prefix)}_{_stamp()}{ext}"
    path = settings.EXPORT_DIR / name
    # تفادي التعدي على ملف قائم بنفس الثانية
    counter = 1
    while path.exists():
        path = settings.EXPORT_DIR / f"{_safe_name(filename_prefix)}_{_stamp()}_{counter}{ext}"
        counter += 1
    return path


def _cell(value: Any) -> Any:
    """تحويل الخلية إلى قيمة نصية/رقمية آمنة للملفات."""
    if value is None:
        return ""
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


# ============================================================
# CSV
# ============================================================

def export_csv(headers: Sequence[str], rows: Iterable[Sequence[Any]],
               filename_prefix: str = "export") -> Path:
    """
    يكتب جدولاً في ملف CSV (utf-8-sig + فاصلة) ويعيد مساره.

    يرفع OSError عند تعذّر الكتابة.
    """
    path = _output_path(filename_prefix, ".csv")
    try:
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=",", quoting=csv.QUOTE_MINIMAL)
            writer.writerow([str(h) for h in headers])
            count = 0
            for row in rows:
                writer.writerow([_cell(c) for c in row])
                count += 1
        _log.info("تم تصدير CSV: %s (%s صف)", path, count)
        return path
    except OSError:
        _log.exception("فشل كتابة ملف CSV: %s", path)
        raise


# ============================================================
# Excel (openpyxl اختياري)
# ============================================================

def export_excel(headers: Sequence[str], rows: Iterable[Sequence[Any]],
                 filename_prefix: str = "export") -> Path:
    """
    يكتب جدولاً في ملف xlsx بتنسيق بسيط (رأس ملوّن + عرض أعمدة تلقائي).

    يرفع ImportError إذا كانت openpyxl غير مثبتة.
    """
    if not settings.HAS_OPENPYXL:
        raise ImportError("مكتبة openpyxl غير مثبتة - استخدم التصدير CSV بدلاً منها")

    from openpyxl import Workbook  # استيراد متأخر: المكتبة اختيارية
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    path = _output_path(filename_prefix, ".xlsx")
    data_rows = [list(row) for row in rows]

    wb = Workbook()
    ws = wb.active
    ws.title = str(filename_prefix)[:28] or "Sheet"
    ws.sheet_view.rightToLeft = True  # ورقة عربية RTL

    head_fill = PatternFill("solid", fgColor="1F6F43")
    head_font = Font(color="FFFFFF", bold=True)
    ws.append([str(h) for h in headers])
    for cell in ws[1]:
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    widths = [len(str(h)) for h in headers]
    for row in data_rows:
        cells = [_cell(c) for c in row]
        ws.append(cells)
        for i, val in enumerate(cells):
            text = str(val)
            if i < len(widths):
                widths[i] = max(widths[i], min(len(text), 40))

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(10, w + 3)
    ws.freeze_panes = "A2"

    try:
        wb.save(path)
        _log.info("تم تصدير Excel: %s (%s صف)", path, len(data_rows))
        return path
    except OSError:
        _log.exception("فشل حفظ ملف Excel: %s", path)
        raise


# ============================================================
# واجهة موحّدة
# ============================================================

def export_table(headers: Sequence[str], rows: Iterable[Sequence[Any]],
                 filename_prefix: str = "export",
                 as_excel: bool = True) -> Path:
    """
    تصدير جدولة بصيغة Excel إن أمكن، وإلا CSV تلقائياً.

    Args:
        headers: عناوين الأعمدة.
        rows: iterable صفوف (أي تسلسل خلايا).
        filename_prefix: بادئة اسم الملف.
        as_excel: جرّب x أولاً؛ يفشل بأمان إلى CSV عند غياب openpyxl.
    """
    materialized = [list(r) for r in rows]
    if as_excel and settings.HAS_OPENPYXL:
        try:
            return export_excel(headers, materialized, filename_prefix)
        except Exception:  # noqa: BLE001 - أي خطأ صيغة => تراجع CSV
            _log.exception("فشل تصدير Excel - سيتم التجريب بـ CSV")
    return export_csv(headers, materialized, filename_prefix)


def export_query(sql: str, params: Sequence[Any] = (),
                 filename_prefix: str = "export",
                 as_excel: bool = True) -> Path:
    """
    ينفّذ استعلام SELECT ويصدّر نتيجته مباشرة إلى ملف.

    يعتمد على data.connection لضمان نفس قاعدة البيانات المفتوحة.
    """
    from data.connection import query_all  # استيراد متأخر لتجنب الدورة

    rows = query_all(sql, tuple(params))
    if rows:
        headers = list(rows[0].keys())
        body = [[r.get(h) for h in headers] for r in rows]
    else:
        headers, body = [], []
    return export_table(headers, body, filename_prefix, as_excel=as_excel)
