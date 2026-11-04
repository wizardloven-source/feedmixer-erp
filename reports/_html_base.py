"""
reports/_html_base.py
---------------------
أساس مشترك لتوليد مستندات HTML العربية القابلة للطباعة (RTL):
    - قالب صفحة موحّد مع تنسيقات @media print.
    - عناصر مساعدة: ترويسة، جداول، صفوف ملخص، أزرار طباعة.

تستخدمه الوحدات: invoice_html / statement_html / receipt_html.
"""

from __future__ import annotations

import datetime as _dt
from html import escape as _esc
from typing import Any, Iterable, Mapping

from config import settings
from core.utils import safe_float


def esc(value: Any) -> str:
    """تهريب آمن للنصوص داخل HTML."""
    return _esc(str(value if value is not None else ""))


def money(value: Any) -> str:
    """تنسيق مبلغ مالي بألف فاصلة وآللتين بعدد ثابت."""
    return f"{safe_float(value):,.2f}"


def num(value: Any, digits: int = 0) -> str:
    """تنسيق كمية مع عدد خانات عشرية محدد."""
    return f"{safe_float(value):,.{digits}f}"


_CSS = """
* { box-sizing: border-box; }
body {
    font-family: "Segoe UI", Tahoma, Arial, sans-serif;
    direction: rtl; text-align: right;
    background: #eef1f5; color: #22303c;
    margin: 0; padding: 18px;
}
.sheet {
    background: #fff; max-width: 900px; margin: 0 auto;
    border-radius: 10px; box-shadow: 0 2px 14px rgba(0,0,0,.12);
    padding: 26px 30px; overflow: hidden;
}
.doc-head { display:flex; justify-content:space-between; align-items:flex-start;
            border-bottom: 3px solid #1f6f43; padding-bottom: 12px; margin-bottom: 14px; }
.brand h1 { margin: 0; font-size: 22px; color: #1f6f43; }
.brand small { color:#667; }
.doc-meta { text-align:left; font-size: 12px; color:#445; }
.doc-title { text-align:center; font-size: 18px; font-weight:700; margin: 6px 0 14px;
             background:#f2f7f4; border:1px solid #d7e6dd; border-radius:8px; padding:6px; }
table { width:100%; border-collapse: collapse; margin: 8px 0 14px; font-size: 13px; }
th { background:#1f6f43; color:#fff; padding:7px 8px; text-align:right; }
td { padding:6px 8px; border-bottom:1px solid #e3e8ee; }
tr:nth-child(even) td { background:#f7faf8; }
.totals { width: 320px; margin-right:auto; }
.totals th { background:#2b4c3f; }
.grand td { font-weight:700; background:#eaf6ef !important; border-top:2px solid #1f6f43; }
.info-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:6px 16px; margin-bottom:10px; }
.info-grid div { font-size:13px; }
.info-grid b { color:#1f6f43; }
.footer { margin-top:16px; border-top:1px dashed #ccd; padding-top:8px;
          font-size:11px; color:#667; display:flex; justify-content:space-between; }
.sign { margin-top:34px; display:flex; justify-content:space-between; font-size:12px; color:#445; }
.sign span { border-top:1px solid #99a; padding-top:4px; min-width:160px; display:inline-block; text-align:center; }
.badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:11px; font-weight:700; }
.badge.ok   { background:#e2f4e6; color:#1c7a34; }
.badge.warn { background:#fdf1dc; color:#9a6a10; }
.badge.bad  { background:#fbe4e4; color:#a32020; }
.toolbar { max-width:900px; margin:0 auto 12px; display:flex; gap:8px; justify-content:center; }
.toolbar button { font-family:inherit; font-size:14px; padding:8px 22px; border:none;
                  border-radius:8px; cursor:pointer; background:#1f6f43; color:#fff; }
.toolbar button.secondary { background:#5b7083; }
@media print {
    body { background:#fff; padding:0; }
    .sheet { box-shadow:none; border-radius:0; max-width:100%; padding:8mm 10mm; }
    .toolbar { display:none !important; }
    tr { page-break-inside: avoid; }
}
"""


def render_page(title: str, body_html: str, *, with_toolbar: bool = True) -> str:
    """
    يغلّف محتوى المستند في صفحة HTML عربية RTL جاهزة للطباعة،
    مع شريط أدوات (طباعة/إغلاق) يظهر على الشاشة فقط.
    """
    toolbar = ""
    if with_toolbar:
        toolbar = (
            '<div class="toolbar">'
            '<button onclick="window.print()">🖨️ طباعة</button>'
            '<button class="secondary" onclick="window.close()">✖ إغلاق</button>'
            "</div>"
        )
    stamp = _dt.datetime.now().strftime("%Y/%m/%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
{toolbar}
<div class="sheet">
{body_html}
<div class="footer">
  <span>{esc(settings.APP_NAME)} v{esc(settings.APP_VERSION)}</span>
  <span>تاريخ الإصدار: {stamp}</span>
</div>
</div>
</body>
</html>"""


def doc_header(subtitle: str) -> str:
    """ترويسة موحّدة باسم التطبيق."""
    return (
        '<div class="doc-head">'
        f'<div class="brand"><h1>🌾 {esc(settings.APP_NAME)}</h1>'
        f"<small>{esc(subtitle)}</small></div>"
        '<div class="doc-meta">خلاطة الأعلاف<br>نظام إدارة متكامل</div>'
        "</div>"
    )


def info_grid(pairs: Iterable[tuple[str, Any]]) -> str:
    """شبكة معلومات (عنوان: قيمة) فوق الجداول."""
    cells = "".join(f"<div><b>{esc(k)}:</b> {v if _is_raw(v) else esc(v)}</div>"
                    for k, v in pairs)
    return f'<div class="info-grid">{cells}</div>'


def _is_raw(value: Any) -> bool:
    """القيم المغلفة بـ RawHTML تُمرَّر كما هي (للشارات الملونة)."""
    return isinstance(value, RawHTML)


class RawHTML(str):
    """نص HTML جاهز لا يُهرَّب (استخدم بحذر مع قيم داخلية موثوقة فقط)."""

    __slots__ = ()


def table(headers: Iterable[str], rows: Iterable[Iterable[Any]],
          align_left_cols: Iterable[int] = ()) -> str:
    """جدول عام؛ خلايا RowHTML/RawHTML تُمرَّر دون تهريب."""
    ths = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body_parts: list[str] = []
    for row in rows:
        tds: list[str] = []
        for idx, cell in enumerate(row):
            content = str(cell) if _is_raw(cell) else esc(cell)
            style = ' style="text-align:left"' if idx in set(align_left_cols) else ""
            tds.append(f"<td{style}>{content}</td>")
        body_parts.append(f"<tr>{''.join(tds)}</tr>")
    if not body_parts:
        cols = len(list(headers)) or 1
        body_parts.append(f'<tr><td colspan="{cols}" style="text-align:center;color:#889">'
                          "لا توجد بيانات</td></tr>")
    return f"<table><thead><tr>{ths}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>"


def totals_table(rows: Iterable[tuple[str, str]], grand: tuple[str, str] | None = None) -> str:
    """جدول مجاميع صغير (سطر إجمالي أخير بارز إن وُجد)."""
    parts = ["<table class='totals'>"]
    for label, value in rows:
        parts.append(f"<tr><th>{esc(label)}</th><td style='text-align:left'>{esc(value)}</td></tr>")
    if grand:
        parts.append(f"<tr class='grand'><td>{esc(grand[0])}</td>"
                     f"<td style='text-align:left'>{esc(grand[1])}</td></tr>")
    parts.append("</table>")
    return "".join(parts)


def status_badge(text: Any) -> RawHTML:
    """شارة حالة دفع ملونة حسب النص العربي."""
    t = str(text or "")
    cls = "ok"
    if "جزئ" in t:
        cls = "warn"
    elif "متأخر" in t or "غير" in t or t in ("", "دين"):
        cls = "bad"
    return RawHTML(f'<span class="badge {cls}">{esc(t)}</span>')


def signatures(*names: str) -> str:
    """أماكن توقيع أسفل المستند."""
    spans = "".join(f"<div><span>{esc(n)}</span></div>" for n in names)
    return f'<div class="sign">{spans}</div>'


def map_of(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """تحويل صف sqlite إلى dict عادي بأمان."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:  # noqa: BLE001
        return {}
