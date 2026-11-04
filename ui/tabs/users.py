"""
ui/tabs/users.py
----------------
تبويب «المستخدمون»: إدارة كاملة (admin فقط — صلاحية users.manage).

الأعمدة: # | اسم الدخول | الاسم الكامل | الدور | الحالة | تاريخ الإنشاء
الوظائف:
    - ➕ مستخدم جديد / ✏️ تعديل / 🔑 تغيير كلمة المرور / ⏸️ تفعيل-تعطيل / 🗑️ حذف.
    - منع حذف آخر admin نشِط وتمرير acting_user_id لـ users_repo للحماية المزدوجة.
    - تغيير كلمة مرور المدير لنفسه متاح دائماً حتى لغير admin (تبويب المحظورين يُخفى).

واجهة التبويب (يتوقعها ui/main_window):
    build(parent, app) -> UsersController
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from config import settings
from core.logger import get_logger
from core.permissions import has_permission
from data import users_repo
from ui.tabs._common import TabUI, build_tab

_log = get_logger("ui.tabs.users")

ROLE_TO_KEY = {v: k for k, v in settings.ROLE_LABELS.items()}


class UsersController:
    """كنترولر تبويب المستخدمين."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.can_manage = has_permission(self.app.user, "users.manage")
        self._build(parent)
        self.refresh()

    # ------------------------------------------------------------ بناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="👥 إدارة المستخدمين", font=settings.FONT_LARGE_BOLD)\
            .pack(side="right")
        if not self.can_manage:
            ttk.Label(head, text="الإدارة مقصورة على المدير (admin)",
                      font=settings.FONT_SMALL, foreground="#c62828").pack(side="left")

        buttons: list[tuple[str, str, Any]] = []
        if self.can_manage:
            buttons += [
                ("➕ مستخدم جديد", "primary", self.new_record),
                ("✏️ تعديل", "accent", self.edit_selected),
                ("⏸️ تفعيل/تعطيل", "flat", self.toggle_active),
                ("🗑️ حذف", "danger", self.delete_selected),
            ]
        buttons.append(("🔑 تغيير كلمة المرور", "flat", self.change_own_password))
        buttons.append(("🔄 تحديث", "flat", self.refresh))

        columns = ["id", "username", "full_name", "role", "active", "created_at"]
        headings = [
            ("id", "#", 45), ("username", "اسم الدخول", 150),
            ("full_name", "الاسم الكامل", 190), ("role", "الدور", 110),
            ("active", "الحالة", 90), ("created_at", "تاريخ الإنشاء", 130),
        ]
        self.ui: TabUI = build_tab(parent, self.app, columns=columns, headings=headings,
                                   buttons=buttons, weights=[0, 1.5, 2, 1, 0.8, 1.2])
        self.ui.tree.bind("<Double-1>", lambda _e: self.edit_selected())
        if self.can_manage:
            self.ui.tree.bind("<Delete>", lambda _e: self.delete_selected())
        try:
            self.ui.tree.tag_configure("inactive", foreground="#9e9e9e")
            self.ui.tree.tag_configure("self", foreground=settings.COLORS["primary"])
        except tk.TclError:
            pass

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        try:
            rows = users_repo.list_users(include_inactive=True)
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحميل المستخدمين")
            self.app.toast("فشل تحميل المستخدمين", "error")
            return
        me = str(self.app.user.get("username", ""))
        tree = self.ui.tree
        tree.delete(*tree.get_children())
        for r in rows:
            active = bool(r.get("is_active", 1))
            username = str(r.get("username", ""))
            tags: list[str] = []
            if username == me:
                tags.append("self")
            elif not active:
                tags.append("inactive")
            created = str(r.get("created_at") or "")[:16]
            if not tags and not active:
                tags.append("inactive")
            tree.insert("", "end", iid=str(r["id"]), tags=tuple(tags),
                        values=(r["id"], username, r.get("full_name", "") or "",
                                settings.ROLE_LABELS.get(str(r.get("role", "")),
                                                         str(r.get("role", ""))),
                                "✅ نشط" if active else "⏸️ معطّل", created))

    # ------------------------------------------------------------ إجراءات
    def _require_manage(self) -> bool:
        if not self.can_manage:
            self.app.toast("إدارة المستخدمين مقصورة على المدير", "error")
            return False
        return True

    def _selected_id(self) -> int:
        sel = self.ui.tree.selection()
        if not sel:
            self.app.toast("اختر مستخدماً من الجدول", "warning")
            return 0
        try:
            return int(sel[0])
        except (TypeError, ValueError):
            return 0

    def _user_or_none(self, uid: int) -> dict | None:
        try:
            return users_repo.get_user(uid)
        except Exception:  # noqa: BLE001
            _log.exception("فشل قراءة المستخدم %s", uid)
            return None

    def new_record(self) -> None:
        if not self._require_manage():
            return
        from ui.dialogs.user_dialog import UserDialog

        dlg = UserDialog(self.app, self.app)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()

    def edit_selected(self) -> None:
        if not self._require_manage():
            return
        uid = self._selected_id()
        user = self._user_or_none(uid) if uid else None
        if not user:
            return
        from ui.dialogs.user_dialog import UserDialog

        dlg = UserDialog(self.app, self.app, user=user)
        self.app.wait_window(dlg)
        if getattr(dlg, "saved", False):
            self.refresh()

    def toggle_active(self) -> None:
        if not self._require_manage():
            return
        uid = self._selected_id()
        user = self._user_or_none(uid) if uid else None
        if not user:
            return
        new_state = not bool(user.get("is_active", 1))
        if not new_state and str(user.get("username")) == str(self.app.user.get("username")):
            self.app.toast("لا يمكنك تعطيل حسابك الحالي", "warning")
            return
        try:
            ok = users_repo.set_active(uid, new_state)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل تغيير حالة المستخدم %s", uid)
            self.app.toast(str(exc), "error")
            return
        if ok:
            self.app.toast("تم التفعيل ✅" if new_state else "تم التعطيل ⏸️", "success")
            self.refresh()

    def delete_selected(self) -> None:
        if not self._require_manage():
            return
        uid = self._selected_id()
        user = self._user_or_none(uid) if uid else None
        if not user:
            return
        username = str(user.get("username", ""))
        if username == str(self.app.user.get("username")):
            self.app.toast("لا يمكنك حذف حسابك الحالي", "warning")
            return
        if not messagebox.askyesno("حذف مستخدم",
                                   f"سيُحذف المستخدم «{username}» نهائياً.\nمتأكد؟",
                                   parent=self.app):
            return
        acting_id = self.app.user.get("id")
        try:
            ok = users_repo.delete_user(uid, acting_user_id=int(acting_id) if acting_id else None)
        except Exception as exc:  # noqa: BLE001
            _log.info("رفض حذف المستخدم %s: %s", username, exc)
            self.app.toast(str(exc), "error")
            return
        if ok:
            self.app.toast(f"تم حذف «{username}»", "success")
            self.refresh()

    def change_own_password(self) -> None:
        """تغيير كلمة مرور المستخدم الحالي (يتطلب الكلمة القديمة)."""
        uid = int(self.app.user.get("id") or 0)
        if not uid:
            # جلسة قديمة بلا id — نبحث بالمستخدم name
            row = users_repo.get_user_by_username(str(self.app.user.get("username", "")))
            uid = int(row.get("id", 0)) if row else 0
        if not uid:
            self.app.toast("تعذّر تحديد حسابك الحالي", "error")
            return
        old = simpledialog.askstring("كلمة المرور الحالية", "أدخل كلمة المرور الحالية:",
                                     show="*", parent=self.app)
        if not old:
            return
        new = simpledialog.askstring("كلمة مرور جديدة", "أدخل كلمة المرور الجديدة:",
                                     show="*", parent=self.app)
        if not new:
            return
        try:
            from core.validators import validate_password

            new = validate_password(new)
        except Exception as exc:  # ValidationError برسالة عربية واضحة
            self.app.toast(str(exc), "error")
            return
        again = simpledialog.askstring("تأكيد كلمة المرور", "أعد كتابة كلمة المرور الجديدة:",
                                       show="*", parent=self.app)
        if again != new:
            self.app.toast("كلمتا المرور غير متطابقتين", "error")
            return
        try:
            ok = users_repo.change_password(uid, new, old_password=old)
        except Exception as exc:
            _log.exception("فشل تغيير كلمة المرور")
            self.app.toast(str(exc), "error")
            return
        if ok:
            self.app.toast("تم تغيير كلمة المرور بنجاح 🔑", "success")
        else:
            self.app.toast("كلمة المرور الحالية غير صحيحة", "error")

    # ------------------------------------------------------------ واجهة عامة
    def export_current(self) -> None:
        if not self._require_manage():
            return
        self.ui.export("users")

    def focus_search(self) -> None:
        try:
            self.ui.search_entry.focus_set()
        except tk.TclError:
            pass


def build(parent: tk.Misc, app: Any) -> UsersController:
    """نقطة دخول التبويب — تستدعى من main_window عند فتحه أول مرة."""
    return UsersController(parent, app)
