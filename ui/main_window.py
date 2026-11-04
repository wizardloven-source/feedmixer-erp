"""
ui/main_window.py
-----------------
النافذة الرئيسية FeedMixerERP(tk.Tk).

المسؤوليات:
    1) تجهيز النافذة: هندسة محفوظة، RTL، ثيم، عنوان.
    2) شريط علوي: شعار + أزرار إجراءات سريعة + اسم المستخدم/الدور + خروج.
    3) Notebook بـ 13 تبويباً — تُبنى كسولاً (lazy) عند أول فتح.
    4) شريط حالة سفلي (رسالة + مستخدم + ساعة + تنبيهات).
    5) اختصارات عامة: Ctrl+S / Ctrl+N / Ctrl+P / Ctrl+F / Ctrl+C / F5 / Del.
    6) حفظ هندسة النافذة في UI_STATE_FILE عند الإغلاق.
    7) عارض HTML للطباعة (وحدات reports تولّد النص).

كائن app المتاح لكل تبويب يوفر واجهة ثابتة:
    app.user            : dict {id, username, role, full_name}
    app.can(perm)       : فحص الصلاحيات
    app.set_status(msg) : رسالة شريط الحالة
    app.toast(msg, kind): إشعار منبثق
    app.open_tab(name)  : الانتقال لتبويب
    app.refresh_all()   : تحديث كل التبويبات المبنية
    app.show_html(title, html) : عرض/طباعة مستند HTML
    app.tabs            : registry بأشياء التبويبات (بعد البناء)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

from config import settings
from core.logger import get_logger
from core.permissions import has_permission, role_label
from core.utils import Toast
from ui import styles
from ui.widgets import add_status_bar, set_status

_log = get_logger("ui.main_window")

# ============================================================
# 1) جدول التبويبات: (المفتاح، العنوان العربي، اسم الوحدة داخل ui.tabs)
# ============================================================
TAB_DEFS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "🏠 الرئيسية", "dashboard"),
    ("mix", "🧪 خلطة", "mix"),
    ("inventory", "📦 مخزون", "inventory"),
    ("purchases", "🚚 توريدات", "purchases"),
    ("invoices", "🧾 فواتير", "invoices"),
    ("farms", "🚜 مزارع", "farms"),
    ("accounts", "💰 حسابات", "accounts"),
    ("recipes", "📝 وصفات", "recipes"),
    ("prices", "🏷️ أسعار", "prices"),
    ("reports", "📊 تقارير", "reports"),
    ("users", "👥 مستخدمون", "users"),
    ("audit", "🔍 سجل", "audit"),
    ("settings", "⚙️ إعدادات", "settings_tab"),
)

_GEOMETRY_RE = re.compile(r"^\d+x\d+[+-]\d+[+-]\d+$")


def _open_in_browser(file_uri: str) -> None:
    """يفتح رابط ملف في المتصفح الافتراضي (لطباعة HTML)."""
    try:
        if sys.platform.startswith("win"):
            import os

            os.startfile(file_uri)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", file_uri])
        else:
            subprocess.Popen(["xdg-open", file_uri])
    except Exception:
        _log.exception("تعذّر فتح المتصفح للطباعة: %s", file_uri)


class FeedMixerERP(tk.Tk):
    """النافذة الرئيسية للتطبيق."""

    def __init__(self, user: dict[str, Any]) -> None:
        super().__init__()
        self.user: dict[str, Any] = dict(user)
        self.tabs: dict[str, Any] = {}          # key -> tab controller
        self._tab_frames: dict[str, ttk.Frame] = {}
        self._tab_built: set[str] = set()
        self._build_in_progress = False

        # ---- تجهيز النافذة ----
        self.title(f"{settings.APP_NAME} v{settings.APP_VERSION}")
        self.minsize(1100, 660)
        styles.setup_styles(self)
        styles.enable_rtl(self)
        self._restore_geometry()

        # ---- البنية ----
        self._build_topbar()
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.status_bar = add_status_bar(self, str(self.user.get("username", "")),
                                         role_label(self.user))
        self._build_tabs()

        # ---- الأحداث والاختصارات ----
        self.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._bind_shortcuts()

        set_status(self, f"مرحباً {self.user.get('full_name') or self.user.get('username')} — F1 للاختصارات")
        self.after(400, self._startup_alerts)

    # ========================================================
    # الصلاحيات والحالة (واجهة mوحّدة للتبويبات)
    # ========================================================
    def can(self, permission: str) -> bool:
        """هل يملك المستخدم الحالي هذه الصلاحية؟"""
        return has_permission(self.user, permission)

    def set_status(self, message: str) -> None:
        set_status(self, message)

    def toast(self, message: str, kind: str = "info") -> None:
        Toast(self, message, kind=kind)

    # ========================================================
    # الشريط العلوي
    # ========================================================
    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, style=None)
        try:  # خلفية مميزة للشريط العلوي (تفشل بصمت لو غاب النمط)
            st = ttk.Style()
            st.configure("Top.TFrame", background=settings.COLORS["header_bg"])
            bar.configure(style="Top.TFrame")
        except Exception:  # noqa: BLE001
            pass
        bar.pack(fill="x", side="top")
        bar.columnconfigure(90, weight=1)

        title = ttk.Label(bar, text=f"🌾 {settings.APP_NAME}",
                          font=settings.FONT_TITLE_BOLD)
        title.grid(row=0, column=0, padx=10, pady=4, sticky="w")

        version = ttk.Label(bar, text=f"v{settings.APP_VERSION}",
                            font=settings.FONT_SMALL)
        version.grid(row=0, column=1, padx=2, sticky="w")

        def btn(col: int, text: str, cmd: Callable[[], Any], shortcut: str | None = None) -> None:
            b = ttk.Button(bar, text=text, command=self._safe(cmd))
            b.grid(row=0, column=col, padx=3, pady=3, sticky="ns")
            if shortcut:
                b.bind(shortcut, lambda _e: self._safe(cmd)())

        btn(10, "➕ خلطة جديدة", lambda: self.new_record(), "<Control-n>")
        btn(11, "💾 حفظ", lambda: self.save_current(), "<Control-s>")
        btn(12, "🖨️ طباعة", lambda: self.print_current(), "<Control-p>")
        btn(13, "🔍 بحث", lambda: self.focus_search(), "<Control-f>")
        btn(14, "📤 تصدير", lambda: self.export_current(), "<Control-c>")
        btn(15, "🔄 تحديث", lambda: self.refresh_current(), "<F5>")

        who = ttk.Label(bar,
                        text=f"👤 {self.user.get('username', '')}  ({role_label(self.user)})",
                        font=settings.FONT_SMALL)
        who.grid(row=0, column=95, padx=8, sticky="e")

        ttk.Button(bar, text="🚪 خروج", command=self._confirm_exit).grid(
            row=0, column=99, padx=8, pady=3, sticky="e")

    # ========================================================
    # التبويبات (بناء كسول)
    # ========================================================
    def _build_tabs(self) -> None:
        for key, label, module in TAB_DEFS:
            frame = ttk.Frame(self.notebook, padding=6)
            self.notebook.add(frame, text=label)
            self._tab_frames[key] = frame
            frame._tab_key = key  # type: ignore[attr-defined]
        # البناء الفوري للوحة الرئيسية فقط؛ الباقي عند التنقل
        self._ensure_built("dashboard")

    def _ensure_built(self, key: str) -> None:
        """يستورد وحدة التبويب ويستدعي build(parent, app) مرة واحدة."""
        if key in self._tab_built or self._build_in_progress:
            return
        module_name = next((m for k, _l, m in TAB_DEFS if k == key), None)
        if not module_name:
            return
        self._build_in_progress = True
        try:
            module = __import__(f"ui.tabs.{module_name}", fromlist=["build"])
            frame = self._tab_frames[key]
            controller = module.build(frame, self)
            self.tabs[key] = controller if controller is not None else module
            self._tab_built.add(key)
        except Exception:
            _log.exception("فشل بناء التبويب: %s", key)
            self.toast(f"خطأ في بناء تبويب {key}", "error")
        finally:
            self._build_in_progress = False

    def open_tab(self, key: str) -> None:
        """ينقل التركيز إلى تبويب بالمفتاح (مثل 'mix')."""
        for k, _label, _m in TAB_DEFS:
            if k == key:
                self._ensure_built(k)
                self.notebook.select(self._tab_frames[k])
                self.refresh_current()
                return

    def current_tab_key(self) -> str:
        """يعيد مفتاح التبويب الحالي عبر مقارنة الـ child id (ttk لا يوفر -widget)."""
        try:
            sel_id = self.notebook.select()
            for key, frame in self._tab_frames.items():
                if str(frame) == sel_id:
                    return key
        except tk.TclError:
            pass
        return ""

    def _current_controller(self) -> Any:
        return self.tabs.get(self.current_tab_key())

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        key = self.current_tab_key()
        if key:
            self._ensure_built(key)
            self.refresh_current()

    # ========================================================
    # عمليات عامة تُوجَّه للتبويب الحالي
    # ========================================================
    @staticmethod
    def _safe(fn: Callable[[], Any]) -> Callable[[], None]:
        """لفّف دالة بحيث لا يُسقط أي استثناء التطبيق."""
        def wrapper() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                _log.exception("خطأ في إجراء واجهة")
                try:
                    w = wrapper.__self__ if hasattr(wrapper, "__self__") else None
                except Exception:
                    w = None
                if isinstance(w, FeedMixerERP):
                    w.toast(f"حدث خطأ: {exc}", "error")
        return wrapper

    def _call_tab(self, method: str, *args: Any) -> bool:
        """يستدعي طريقة على كنترولر التبويب الحالي إن وُجدت."""
        ctrl = self._current_controller()
        fn = getattr(ctrl, method, None)
        if callable(fn):
            try:
                fn(*args)
                return True
            except Exception:
                _log.exception("فشل %s.%s", self.current_tab_key(), method)
                self.toast(f"تعذّر تنفيذ {method}", "error")
        return False

    def new_record(self) -> None:
        if not self._call_tab("new_record"):
            self.toast("لا يوجد إجراء (جديد) في هذا التبويب", "warning")

    def save_current(self) -> None:
        if not self._call_tab("save"):
            self.toast("لا يوجد إجراء (حفظ) في هذا التبويب", "warning")

    def print_current(self) -> None:
        if not self._call_tab("print_current"):
            self.toast("لا يمكن الطباعة من هذا التبويب", "warning")

    def focus_search(self) -> None:
        if not self._call_tab("focus_search"):
            self.toast("لا يوجد حقل بحث هنا (Ctrl+F داخل الجداول)", "warning")

    def export_current(self) -> None:
        if not self._call_tab("export_current"):
            self.toast("لا يوجد جدول قابل للتصدير هنا", "warning")

    def refresh_current(self) -> None:
        self._call_tab("refresh")

    def refresh_all(self) -> None:
        for key in list(self._tab_built):
            fn = getattr(self.tabs.get(key), "refresh", None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    _log.exception("فشل تحديث تبويب %s", key)

    # ========================================================
    # عارض HTML للطباعة
    # ========================================================
    def show_html(self, title: str, html: str) -> None:
        """يحفظ HTML في PRINT_DIR ويعرض معاينة ويطلب فتح المتصفح للطباعة."""
        import datetime as _dt

        try:
            settings.ensure_directories()
            safe_title = re.sub(r"[^\w\u0600-\u06FF-]+", "_", title)[:60] or "doc"
            stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            path: Path = settings.PRINT_DIR / f"{safe_title}_{stamp}.html"
            path.write_text(html, encoding="utf-8")
        except Exception:
            _log.exception("فشل حفظ ملف HTML للطباعة")
            self.toast("فشل تجهيز ملف الطباعة", "error")
            return

        win = tk.Toplevel(self)
        win.title(f"معاينة: {title}")
        win.geometry("900x640")
        styles.apply_theme(win)
        txt = tk.Text(win, wrap="word", bg="#ffffff", fg="#111111")
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", html)
        txt.configure(state="disabled")

        bottom = ttk.Frame(win, padding=6)
        bottom.pack(fill="x")
        ttk.Label(bottom, text=f"📄 {path}", font=settings.FONT_SMALL).pack(side="left", padx=6)
        ttk.Button(bottom, text="🌐 فتح وطباعة",
                   command=lambda: _open_in_browser(path.as_uri())).pack(side="right", padx=6)
        ttk.Button(bottom, text="إغلاق", command=win.destroy).pack(side="right", padx=6)
        self.set_status(f"تم تجهيز: {path.name}")
        self.toast("جاهز للطباعة — استخدم زر (فتح وطباعة)", "success")

    # ========================================================
    # الاختصارات العامة
    # ========================================================
    def _bind_shortcuts(self) -> None:
        # الأزرار الوظيفية والعامة غير المرتبطة بأزرار الشريط
        self.bind("<Control-q>", lambda _e: self._confirm_exit())
        self.bind("<Escape>", lambda _e: self._on_escape())
        help_text = (
            "الاختصارات العامة:\n"
            "  Ctrl+N : سجل جديد   |  Ctrl+S : حفظ\n"
            "  Ctrl+P : طباعة      |  Ctrl+F : بحث\n"
            "  Ctrl+C : تصدير CSV/Excel\n"
            "  F5     : تحديث البيانات\n"
            "  Delete : حذف المحدد (إن كان مسموحاً)\n"
            "  Ctrl+Q : خروج       |  Esc    : إغلاق نافذة منبثقة\n"
        )
        self.bind("<F1>", lambda _e: self.show_html("الاختصارات",
                 f"<html dir='rtl'><body style='font-family:Segoe UI'>"
                 f"<pre>{help_text}</pre></body></html>"))

    def _on_escape(self) -> None:
        focus = self.focus_get()
        if isinstance(focus, tk.Toplevel) or (focus and isinstance(focus.winfo_toplevel(), tk.Toplevel)):
            top = focus.winfo_toplevel()
            if top is not self:
                top.destroy()

    # ========================================================
    # الهندسة المحفوظة + الإغلاق
    # ========================================================
    def _restore_geometry(self) -> None:
        geo = settings.DEFAULT_WINDOW_GEOMETRY
        state = "normal"
        try:
            if settings.UI_STATE_FILE.exists():
                data = json.loads(settings.UI_STATE_FILE.read_text(encoding="utf-8"))
                cand = str(data.get("geometry", ""))
                if _GEOMETRY_RE.match(cand):
                    geo = cand
                state = str(data.get("state", "normal"))
        except Exception:
            _log.exception("تعذّر قراءة هندسة النافذة المحفوظة")
        self.geometry(geo)
        try:
            if state == "zoomed":
                self.state("zoomed")
        except tk.TclError:
            pass

    def _save_geometry(self) -> None:
        try:
            x, y = self.winfo_rootx(), self.winfo_rooty()
            w, h = self.winfo_width(), self.winfo_height()
            state = "zoomed" if self.state() == "zoomed" else "normal"
            payload = {"geometry": f"{w}x{h}+{x}+{y}", "state": state}
            settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            settings.UI_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False),
                                              encoding="utf-8")
        except Exception:
            _log.exception("تعذّر حفظ هندسة النافذة")

    def _confirm_exit(self) -> None:
        from tkinter import messagebox

        if messagebox.askyesno("خروج", "هل تريد إنهاء التطبيق؟", parent=self):
            self.on_close()

    def on_close(self) -> None:
        self._save_geometry()
        self.destroy()

    # ========================================================
    # تنبيهات بدء التشغيل
    # ========================================================
    def _startup_alerts(self) -> None:
        try:
            from services import alert_service

            line = alert_service.status_line()
            if line:
                self.set_status(line)
                self.toast(line, "warning")
        except Exception:
            _log.debug("تعذّر جمع التنبيهات عند البدء", exc_info=True)


if __name__ == "__main__":  # تشغيل مباشر لأغراض التطوير
    from data.connection import set_database_path
    from data.schema import init_database
    from data.seed import seed_defaults
    from data.migrations import run_migrations

    settings.ensure_directories()
    set_database_path(settings.DB_PATH)
    init_database()
    run_migrations()
    seed_defaults()
    demo_user = {"username": "admin", "role": settings.ROLE_ADMIN, "full_name": "المدير"}
    FeedMixerERP(demo_user).mainloop()
