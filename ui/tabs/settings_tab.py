"""
ui/tabs/settings_tab.py
-----------------------
تبويب «الإعدادات» (⚙️): تعديل الإعدادات الرقمية + المظهر + النسخ الاحتياطي.

الأقسام:
    1) إعدادات التشغيل (جدول app_settings القابل للتعديل) — صلاحية settings.edit.
    2) المظهر: تبديل الوضع نهاري/ليلي (settings.set_theme + إعادة تطبيق الثيم).
    3) النسخ الاحتياطي: إنشاء نسخة الآن / استرجاع من ملف — صلاحيات backup.*.
    4) معلومات النظام: مسار قاعدة البيانات والإصدارات.

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> SettingsController
"""

from __future__ import annotations

import datetime as _dt
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data import settings_repo
from ui.tabs._common import fmt

_log = get_logger("ui.tabs.settings")


class SettingsController:
    """كنترولر تبويب الإعدادات."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.can_edit = has_permission(self.app.user, "settings.edit")
        self._build(parent)
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="⚙️ الإعدادات", font=settings.FONT_LARGE_BOLD).pack(side="right")
        if not self.can_edit:
            ttk.Label(head, text="للعرض فقط — التعديل مقصور على المدير",
                      font=settings.FONT_SMALL, foreground="#c62828").pack(side="left")

        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True)

        # ---------- 1) إعدادات التشغيل ----------
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="إعدادات التشغيل")
        columns = ["key", "value", "description"]
        headings = [("key", "المفتاح", 220), ("value", "القيمة", 120),
                    ("description", "الوصف", 420)]
        from ui.tabs._common import TabUI, build_tab  # محلي لتجنب دوران الاستيراد

        buttons: list[tuple[str, str, Any]] = []
        if self.can_edit:
            buttons.append(("💾 حفظ القيمة المحددة", "primary", self.save_value))
        buttons.append(("🔄 تحديث", "flat", self.refresh))
        self.ui: TabUI = build_tab(frame, self.app, columns=columns, headings=headings,
                                   buttons=buttons, weights=[1.5, 1, 3])
        edit_state = "normal" if self.can_edit else "disabled"
        self.value_entry = ttk.Entry(frame, width=20, font=settings.FONT_BASE)
        self.value_entry.configure(state=edit_state)
        self.value_entry.pack(anchor="e", pady=(4, 0))
        ttk.Label(frame, text="القيمة الجديدة للمفتاح المحدد:",
                  font=settings.FONT_SMALL).pack(anchor="e")
        self.ui.tree.bind("<<TreeviewSelect>>", lambda _e: self._echo_selected())

        # ---------- 2) المظهر ----------
        look = ttk.Frame(notebook, padding=12)
        notebook.add(look, text="المظهر")
        ttk.Label(look, text="وضع الألوان:", font=settings.FONT_BOLD).pack(anchor="e")
        self.theme_var = tk.StringVar(master=look,
                                      value="dark" if settings.is_dark_mode() else "light")
        for value, label in (("light", "☀️ نهاري"), ("dark", "🌙 ليلي")):
            ttk.Radiobutton(look, text=label, value=value, variable=self.theme_var,
                            command=self.apply_theme_choice).pack(anchor="e", pady=3)
        ttk.Label(look, text="يُطبَّق التغيير فوراً على كل النوافذ.",
                  font=settings.FONT_SMALL).pack(anchor="e", pady=(8, 0))

        # ---------- 3) النسخ الاحتياطي ----------
        backup = ttk.Frame(notebook, padding=12)
        notebook.add(backup, text="النسخ الاحتياطي")
        row1 = ttk.Frame(backup)
        row1.pack(fill="x", pady=4)
        self.backup_btn = ttk.Button(row1, text="💾 إنشاء نسخة الآن",
                                     command=self.create_backup)
        self.backup_btn.pack(side="right")
        self.restore_btn = ttk.Button(row1, text="♻️ استرجاع من ملف…",
                                      command=self.restore_backup)
        self.restore_btn.pack(side="right", padx=6)
        if not has_permission(self.app.user, "backup.run"):
            self.backup_btn.configure(state="disabled")
        if not has_permission(self.app.user, "backup.restore"):
            self.restore_btn.configure(state="disabled")
        self.backups_label = ttk.Label(backup, text="", font=settings.FONT_SMALL)
        self.backups_label.pack(anchor="e", pady=6)
        ttk.Label(backup, text=f"مجلد النسخ: {settings.BACKUP_DIR}",
                  font=settings.FONT_SMALL).pack(anchor="e")
        row2 = ttk.Frame(backup)
        row2.pack(fill="x", pady=(8, 4))
        self.check_btn = ttk.Button(row2, text="🩺 فحص سلامة قاعدة البيانات",
                                    command=self.run_integrity_check)
        self.check_btn.pack(side="right")
        if not has_permission(self.app.user, "db.integrity"):
            self.check_btn.configure(state="disabled")
        self.check_label = ttk.Label(backup, text="", font=settings.FONT_SMALL)
        self.check_label.pack(anchor="e", pady=2)

        # ---------- 4) معلومات النظام ----------
        about = ttk.Frame(notebook, padding=12)
        notebook.add(about, text="حول النظام")
        info_lines = [
            f"التطبيق: {settings.APP_NAME} v{settings.APP_VERSION}",
            f"قاعدة البيانات: {settings.DB_PATH}",
            f"ملفات التصدير: {settings.EXPORT_DIR}",
            f"سجلات التشغيل: {settings.LOG_DIR}",
            f"تاريخ العرض: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        for line in info_lines:
            ttk.Label(about, text=line, font=settings.FONT_BASE).pack(anchor="e", pady=2)

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        """يعيد قراءة جدول app_settings وقائمة النسخ الموجودة."""
        try:
            rows = [settings_repo.get_setting_row(k) or {"key": k, "value": v,
                                                         "description": ""}
                    for k, v in settings.DEFAULT_SETTINGS.items()]
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحميل الإعدادات")
            self.app.toast("فشل تحميل الإعدادات", "error")
            return
        tree = self.ui.tree
        tree.delete(*tree.get_children())
        for r in rows:
            key = str(r.get("key", ""))
            tree.insert("", "end", iid=key, values=(key, fmt(r.get("value")),
                                                    r.get("description", "") or ""))
        self._list_backups()

    def _echo_selected(self) -> None:
        """يعرض قيمة المفتاح المحدد داخل حقل التحرير جاهزة للتعديل."""
        sel = self.ui.tree.selection()
        if not sel:
            return
        try:
            value = settings_repo.get_setting(str(sel[0]), 0.0)
        except Exception:  # noqa: BLE001
            return
        if self.can_edit:
            self.value_entry.configure(state="normal")
            self.value_entry.delete(0, "end")
            self.value_entry.insert(0, f"{value:g}")
            self.value_entry.configure(state="readonly")
            self.value_entry.configure(state="normal")

    # ------------------------------------------------------------ حفظ قيمة
    def save_value(self) -> None:
        if not self.can_edit:
            self.app.toast("لا تملك صلاحية تعديل الإعدادات", "error")
            return
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر مفتاحاً من الجدول أولاً", "warning")
            return
        raw = str(self.value_entry.get()).strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            self.app.toast("أدخل رقماً صحيحاً", "error")
            return
        key = str(sel[0])
        try:
            settings_repo.set_setting(key, value)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل حفظ الإعداد %s", key)
            self.app.toast(str(exc), "error")
            return
        try:
            from core import cache

            cache.invalidate_settings()
        except Exception:  # noqa: BLE001
            pass
        self.app.toast(f"تم حفظ {key} = {value:g} ✅", "success")
        self.refresh()
        self.app.refresh_all()

    # ------------------------------------------------------------ المظهر
    def apply_theme_choice(self) -> None:
        dark = self.theme_var.get() == "dark"
        try:
            settings.set_theme(dark)
            if self.can_edit:
                settings_repo.set_setting("theme_mode", 1.0 if dark else 0.0)
        except Exception:  # noqa: BLE001
            _log.exception("فشل حفظ تفضيل المظهر")
        try:
            from ui import styles

            styles.apply_theme(self.app)
            self.app.toast("تم تطبيق المظهر 🎨", "success")
        except Exception:  # noqa: BLE001
            _log.exception("فشل إعادة تطبيق الثيم")
            self.app.toast("تعذّر إعادة تطبيق الثيم — أعد تشغيل التطبيق", "warning")

    # ------------------------------------------------------------ فحص السلامة
    def run_integrity_check(self) -> None:
        """يشغّل PRAGMA quick_check ويعرض النتيجة داخل التبويب."""
        if not has_permission(self.app.user, "db.integrity"):
            self.app.toast("لا تملك صلاحية فحص قاعدة البيانات", "error")
            return
        try:
            report = self._backup_service().check_integrity(quick=True)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل فحص سلامة قاعدة البيانات")
            self.app.toast(f"فشل الفحص: {exc}", "error")
            return
        ok = bool(report.get("ok"))
        text = (f"النتيجة: {report.get('result', '')} | "
                f"الجداول: {report.get('table_count', 0)} | "
                f"الوقت: {report.get('checked_at', '')}")
        self.check_label.configure(text=text,
                                   foreground="#2e7d32" if ok else "#c62828")
        self.app.toast("قاعدة البيانات سليمة 🩺✅" if ok
                       else "تحذير: نتائج الفحص غير سليمة — راجع السجل",
                       "success" if ok else "warning")

    # ------------------------------------------------------------ نسخ احتياطي
    def _backup_service(self) -> Any:
        from services import backup_service

        return backup_service

    def create_backup(self) -> None:
        if not has_permission(self.app.user, "backup.run"):
            self.app.toast("لا تملك صلاحية النسخ الاحتياطي", "error")
            return
        try:
            path = self._backup_service().create_backup()
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل إنشاء النسخة الاحتياطية")
            self.app.toast(f"فشل النسخ: {exc}", "error")
            return
        self.app.toast(f"تم إنشاء نسخة: {path}", "success")
        self._list_backups()

    def restore_backup(self) -> None:
        if not has_permission(self.app.user, "backup.restore"):
            self.app.toast("استرجاع النسخ مقصور على المدير", "error")
            return
        initial = str(settings.BACKUP_DIR)
        path = filedialog.askopenfilename(title="اختر ملف نسخة احتياطية",
                                          initialdir=initial,
                                          filetypes=[("SQLite", "*.db *.sqlite *.bak"),
                                                     ("الكل", "*.*")])
        if not path:
            return
        if not messagebox.askyesno(
                "استرجاع نسخة احتياطية",
                "سيتم استبدال قاعدة البيانات الحالية بالنسخة المختارة\n"
                "(تُنشَّط نسخة أمان تلقائياً قبل الاستبدال).\n\nمتأكد؟",
                parent=self.app):
            return
        try:
            ok = self._backup_service().restore_backup(path)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل الاسترجاع من %s", path)
            self.app.toast(f"فشل الاسترجاع: {exc}", "error")
            return
        if ok:
            self.app.toast("تم الاسترجاع — حدّث الشاشات بـ F5 ♻️", "success")
            self.app.refresh_all()
        else:
            self.app.toast("تعذّر الاسترجاع (راجع السجل)", "error")

    def _list_backups(self) -> None:
        try:
            files = sorted(settings.BACKUP_DIR.glob("*"), key=lambda p: p.stat().st_mtime,
                           reverse=True)[:5]
        except Exception:  # noqa: BLE001
            files = []
        names = ", ".join(f.name for f in files) or "لا توجد نسخ بعد"
        self.backups_label.configure(text=f"أحدث النسخ: {names}")


def build(parent: tk.Misc, app: Any) -> SettingsController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return SettingsController(parent, app)
