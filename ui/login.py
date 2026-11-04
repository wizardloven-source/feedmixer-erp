"""
ui/login.py
-----------
نافذة تسجيل الدخول (LoginDialog) — Toplevel modal تُعرض قبل النافذة الرئيسية.

السلوك:
    - حقل مستخدم + كلمة مرور (show='*') + زر إظهار/إخفاء.
    - Enter = دخول، Esc = إلغاء.
    - 5 محاولات فاشلة → قفل 60 ثانية مع عدّ تنازلي في شريط سفلي.
    - بعد النجاح يمرّر .user (قاموس من core.auth.authenticate) ويغلق.
    - يقرأ/يكتب اسم آخر مستخدم ناجح من ملف حالة الواجهة لراحته.
    - يعرض معلومات الإصدار وحالة قاعدة البيانات في الأسفل.

الاستخدام (من app.py):
    dlg = LoginDialog(root); root.wait_window(dlg); user = dlg.user
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from config import settings
from core.auth import authenticate
from core.logger import get_logger

_log = get_logger("ui.login")

_MAX_ATTEMPTS = 5
_LOCK_SECONDS = 60


class LoginDialog(tk.Toplevel):
    """حوار تسجيل الدخول Modal. بعد wait_window اقرأ الخاصية `.user`."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.user: dict[str, object] | None = None
        self._attempts = 0
        self._lock_left = 0
        self._show_password = False

        self.title(f"تسجيل الدخول — {settings.APP_TITLE}")
        self.resizable(False, False)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.configure(bg=settings.COLORS["bg"])
        self.grid_columnconfigure(0, weight=1)

        self._remember_file = str(settings.UI_STATE_FILE)
        last_user = self._load_last_username()

        self._build_ui(last_user)
        self._center_over_master()
        self.grab_set()
        self.focus_force()
        self.entry_user.focus_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    # ------------------------------------------------------------------ UI
    def _build_ui(self, last_user: str) -> None:
        c = settings.COLORS
        pad = {"padx": 18, "pady": 6}

        header = tk.Frame(self, bg=c["primary"], height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(header, text="🌾 " + settings.APP_NAME, bg=c["primary"],
                 fg=c["header_fg"], font=settings.FONT_LARGE_BOLD).pack(pady=(14, 0))
        tk.Label(header, text=f"نظام إدارة خلاطة الأعلاف — الإصدار {settings.APP_VERSION}",
                 bg=c["primary"], fg=c["header_fg"],
                 font=settings.FONT_SMALL).pack()

        body = tk.Frame(self, bg=c["bg"])
        body.grid(row=1, column=0, sticky="nsew")

        tk.Label(body, text="اسم المستخدم", **pad, anchor="e",
                 font=settings.FONT_BASE).grid(row=1, column=0, sticky="e")
        self.var_user = tk.StringVar(master=body, value=last_user)
        self.entry_user = ttk.Entry(body, textvariable=self.var_user,
                                    width=28, font=settings.FONT_MEDIUM)
        self.entry_user.grid(row=1, column=1, columnspan=2, sticky="ew", **pad)

        tk.Label(body, text="كلمة المرور", **pad, anchor="e",
                 font=settings.FONT_BASE).grid(row=2, column=0, sticky="e")
        self.var_pass = tk.StringVar(master=body)
        self.entry_pass = ttk.Entry(body, textvariable=self.var_pass, width=28,
                                    show="*", font=settings.FONT_MEDIUM)
        self.entry_pass.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)

        self.btn_toggle = ttk.Button(body, text="👁", width=3,
                                     command=self._toggle_visibility)
        self.btn_toggle.grid(row=2, column=3, padx=(0, 12))

        self.lbl_error = tk.Label(body, text="", bg=c["bg"], fg=c["danger"],
                                  font=settings.FONT_SMALL, anchor="e",
                                  wraplength=340, justify="right")
        self.lbl_error.grid(row=3, column=0, columnspan=4, sticky="ew", padx=18)

        btns = tk.Frame(body, bg=c["bg"])
        btns.grid(row=4, column=0, columnspan=4, pady=(10, 14), sticky="ew")
        btn_login = ttk.Button(btns, text="🔓 دخول", style="Primary.TButton",
                               command=self.try_login)
        btn_login.pack(side="right", padx=(18, 6))
        btn_cancel = ttk.Button(btns, text="إلغاء", style="Flat.TButton",
                                command=self.cancel)
        btn_cancel.pack(side="left", padx=(6, 18))

        footer = tk.Label(
            self,
            text=f"المستخدم الافتراضي: admin / admin123   •   {settings.DB_PATH.name}",
            bg=c["surface_alt"], fg=c["text_muted"], font=settings.FONT_SMALL,
        )
        footer.grid(row=5, column=0, sticky="ew")

        body.grid_columnconfigure(1, weight=1)
        self.bind("<Return>", lambda _e: self.try_login())
        self.bind("<KP_Enter>", lambda _e: self.try_login())
        self.bind("<Escape>", lambda _e: self.cancel())

    def _center_over_master(self) -> None:
        try:
            self.update_idletasks()
            master = self.master
            if master is not None and master.winfo_exists():
                mx, my = master.winfo_rootx(), master.winfo_rooty()
                mw, mh = max(master.winfo_width(), 300), max(master.winfo_height(), 200)
            else:
                mx, my = 0, 0
                mw, mh = self.winfo_screenwidth(), self.winfo_screenheight()
            w, h = 420, 300
            x = mx + max((mw - w) // 2, 0)
            y = my + max((mh - h) // 2 - 40, 0)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError as exc:
            _log.debug("تعذّر توسيط نافذة الدخول: %s", exc)

    # ------------------------------------------------------------ helpers
    def _toggle_visibility(self) -> None:
        self._show_password = not self._show_password
        self.entry_pass.configure(show="" if self._show_password else "*")
        self.btn_toggle.configure(text="🙈" if self._show_password else "👁")

    def _load_last_username(self) -> str:
        try:
            with open(self._remember_file, encoding="utf-8") as fh:
                data = json.load(fh)
            return str(data.get("last_username", ""))
        except (OSError, ValueError):
            return ""

    def _save_last_username(self, username: str) -> None:
        data: dict[str, object] = {}
        try:
            with open(self._remember_file, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            pass
        data["last_username"] = username
        try:
            settings.ensure_directories()
            with open(self._remember_file, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            _log.debug("تعذّر حفظ اسم المستخدم الأخير: %s", exc)

    def _set_error(self, message: str) -> None:
        self.lbl_error.configure(text=message)

    # ------------------------------------------------------------ actions
    def try_login(self) -> None:
        """يحاول المصادقة؛ يعالج القفل والرسائل والمحاولات الفاشلة."""
        if self._lock_left > 0:
            return
        username = self.var_user.get().strip().lower()
        password = self.var_pass.get()
        if not username or not password:
            self._set_error("أدخل اسم المستخدم وكلمة المرور")
            return

        try:
            user = authenticate(username, password)
        except Exception as exc:  # noqa: BLE001 - لا نسقط نافذة الدخول أبداً
            _log.exception("خطأ غير متوقع أثناء المصادقة")
            self._set_error(f"خطأ في النظام: {exc}")
            return

        if user is not None:
            self._save_last_username(username)
            self.user = user
            self.destroy()
            return

        self._attempts += 1
        remaining = _MAX_ATTEMPTS - self._attempts
        self.var_pass.set("")
        self.entry_pass.focus_set()
        if remaining <= 0:
            self._start_lock()
        else:
            self._set_error(
                f"بيانات الدخول غير صحيحة — المحاولات المتبقية: {remaining}"
            )

    def _start_lock(self) -> None:
        self._lock_left = _LOCK_SECONDS
        self._set_error("تم إيقاف المحاولات مؤقتاً لأسباب أمنية")
        self._tick_lock()

    def _tick_lock(self) -> None:
        if not self.winfo_exists():
            return
        if self._lock_left <= 0:
            self._attempts = 0
            self._set_error("")
            self.entry_user.focus_set()
            return
        self.lbl_error.configure(
            text=f"⛔ حاول مرة أخرى بعد {self._lock_left} ثانية")
        self._lock_left -= 1
        self.after(1000, self._tick_lock)

    def cancel(self) -> None:
        """إلغاء الدخول — .user تبقى None فيُنهي app.py التطبيق."""
        self.user = None
        self.destroy()
