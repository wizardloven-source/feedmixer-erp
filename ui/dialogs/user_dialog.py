"""
ui/dialogs/user_dialog.py
-------------------------
حوار إدارة المستخدم (admin فقط): إنشاء مستخدم جديد أو تعديل مستخدم.

حقول: اسم مستخدم + الاسم الكامل + الدور + تفعيل + كلمة مرور (اختيارية للتعديل).
عند التعديل يمكن ترك كلمة المرور فارغة = عدم تغييرها.
يتحقق من قواعد users_repo (منع تخفيض آخر admin ... عبر الـ repo نفسه).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.validators import validate_password, validate_username
from data import users_repo
from ui.dialogs.base_form import FormDialog

_log = get_logger("ui.dialogs.user")

_ROLE_LABELS = {
    settings.ROLE_ADMIN: "🛡️ مدير (admin)",
    settings.ROLE_OPERATOR: "⚙️ عامل (operator)",
    settings.ROLE_VIEWER: "👁️ مشاهد (viewer)",
}
_LABEL_TO_ROLE = {v: k for k, v in _ROLE_LABELS.items()}


class UserDialog(FormDialog):
    """نموذج مستخدم واحد (إنشاء/تعديل)."""

    def __init__(self, parent: tk.Misc, app: Any, user: dict | None = None) -> None:
        self.app = app
        self.user = dict(user) if user else None
        title = "✏️ تعديل مستخدم" if self.user else "➕ مستخدم جديد"
        super().__init__(parent, title, width=450, on_save=self._save)
        self._build_fields()

    # ------------------------------------------------------------ الحقول
    def _build_fields(self) -> None:
        u = self.user or {}
        self.add_label("بيانات المستخدم", bold=True)

        uname = ttk.Entry(self.body, width=24, font=settings.FONT_BASE)
        uname.insert(0, str(u.get("username", "")))
        if self.user is not None:
            uname.configure(state="disabled")
        else:
            uname.focus_set()
        self.add_field("username", uname, "اسم المستخدم:")

        full = ttk.Entry(self.body, width=28, font=settings.FONT_BASE)
        full.insert(0, str(u.get("full_name") or ""))
        self.add_field("full_name", full, "الاسم الكامل:")

        role_key = str(u.get("role") or settings.ROLE_VIEWER)
        self.role_var = tk.StringVar(
            master=self, value=_ROLE_LABELS.get(role_key, _ROLE_LABELS[settings.ROLE_VIEWER]))
        combo = ttk.Combobox(self.body, textvariable=self.role_var,
                             values=list(_ROLE_LABELS.values()),
                             state="readonly", width=22, font=settings.FONT_BASE)
        self.add_field("role", combo, "الدور:")

        self.active_var = tk.BooleanVar(master=self, value=bool(u.get("is_active", True)))
        chk = ttk.Checkbutton(self.body, text="حساب نشط", variable=self.active_var)
        self.add_field("is_active", chk, "")

        self.add_label("كلمة المرور" +
                       (" (اتركها فارغة لعدم التغيير)" if self.user else ""))
        pwd = ttk.Entry(self.body, width=24, show="•", font=settings.FONT_BASE)
        self.add_field("password", pwd, "كلمة المرور:")

        confirm = ttk.Entry(self.body, width=24, show="•", font=settings.FONT_BASE)
        self.add_field("confirm", confirm, "تأكيد كلمة المرور:")
        if self.user is None:
            pwd.focus_set()

        hint = ttk.Label(self.body,
                         text="الحد الأدنى 6 أحرف/أرقام — يُفضّل مزيج أطوال ورموز.",
                         font=settings.FONT_SMALL)
        hint.grid(row=self.next_row(), column=0, columnspan=3, sticky="e")

        self.body.columnconfigure(1, weight=1)

    # ------------------------------------------------------------ الحفظ
    def _collect(self) -> dict[str, Any]:
        username = str(self.fields["username"].get()).strip()
        password = str(self.fields["password"].get())
        confirm = str(self.fields["confirm"].get())
        if self.user is None:
            try:
                validate_username(username)
            except ValueError as exc:
                raise ValueError(str(exc)) from None
        if password or confirm:
            if password != confirm:
                raise ValueError("كلمتا المرور غير متطابقتين")
            try:
                validate_password(password)
            except ValueError as exc:
                raise ValueError(str(exc)) from None
        elif self.user is None:
            raise ValueError("كلمة المرور مطلوبة للمستخدم الجديد")
        return {
            "username": username,
            "full_name": str(self.fields["full_name"].get()).strip(),
            "role": _LABEL_TO_ROLE.get(self.role_var.get(), settings.ROLE_VIEWER),
            "is_active": bool(self.active_var.get()),
            "password": password or None,
        }

    def _save(self, data: dict[str, Any]) -> bool:
        if self.user is not None:
            users_repo.update_user(
                int(self.user["id"]),
                full_name=data["full_name"],
                role=data["role"],
                is_active=data["is_active"],
                password=data["password"],
            )
        else:
            users_repo.create_user(
                username=data["username"],
                password=str(data["password"]),
                role=data["role"],
                full_name=data["full_name"],
                is_active=data["is_active"],
            )
        return True


__all__ = ["UserDialog"]
