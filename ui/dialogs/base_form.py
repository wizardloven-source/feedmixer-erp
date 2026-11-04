"""
ui/dialogs/base_form.py
-----------------------
قاعدة مشتركة لحوارات النماذج (FormDialog).

توفّر:
    - نافذة Toplevel modal (transient + grab_set) بعنوان عربي وثيم current.
    - شبكة حقول موحّدة (تسمية + حقل) مع أزرار حفظ/إلغاء.
    - حالة .saved بعد الإغلاق، ويستدعي callback الحفظ الممرّر.

كل حوار متخصص (مزرعة/مادة/دفعة/مستخدم/وصفة/توريد) يرث FormDialog
ويكتب _build_fields() و _collect() و _save().
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from config import settings
from core.logger import get_logger
from ui import styles

_log = get_logger("ui.dialogs.base")


class FormDialog(tk.Toplevel):
    """حوار نموذج عام: حقول في شبكة + شريط أزرار سفلي."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        width: int = 460,
        on_save: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        super().__init__(master=parent)
        self.app_colors = settings.COLORS
        self.title(title)
        self.saved: bool = False
        self._on_save = on_save
        self.fields: dict[str, Any] = {}

        try:
            styles.apply_theme(self)
        except Exception:  # noqa: BLE001 - الثيم قد يكون مطبقاً من الأب
            _log.debug("apply_theme في الحوار فشل (متوقع غالباً)")

        self.resizable(False, False)
        try:
            self.transient(self.winfo_parent() or parent)
        except tk.TclError:
            pass
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Control-s>", lambda _e: self._try_save())

        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        self._row = 0

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.pack(fill="x")
        self.save_btn = make_save_button(footer, self._try_save)
        cancel_btn = ttk.Button(footer, text="✖ إلغاء", command=self.close)
        cancel_btn.pack(side="right", padx=6)
        self.msg_var = tk.StringVar(master=self, value="")
        ttk.Label(footer, textvariable=self.msg_var, foreground=self.app_colors["danger"],
                  font=settings.FONT_SMALL).pack(side="left")

        # توسيع العرض الأفقي عبر إطار ثابت
        spacer = ttk.Frame(self, width=width, height=1)
        spacer.pack(fill="x")
        spacer.pack_forget()

    # ------------------------------------------------------------ أدوات
    def next_row(self) -> int:
        """يعيد رقم الصف التالي في الشبكة ويزيده."""
        row = self._row
        self._row += 1
        return row

    def add_field(self, key: str, widget: tk.Widget, label: str = "",
                  colspan: int = 1) -> tk.Widget:
        """يضيف (تسمية + حقل) للصف الحالي ويعيد الحقل."""
        r = self.next_row()
        if label:
            ttk.Label(self.body, text=label, font=settings.FONT_BASE).grid(
                row=r, column=0, sticky="e", pady=3, padx=(8, 4))
        widget.grid(row=r, column=1, columnspan=colspan, sticky="we", pady=3, padx=4)
        self.fields[key] = widget
        return widget

    def add_label(self, text: str, bold: bool = False) -> ttk.Label:
        """سطر نصي كامل العرض داخل الشبكة (عنوان قسم أو ملاحظة)."""
        r = self.next_row()
        lbl = ttk.Label(self.body, text=text,
                        font=settings.FONT_BOLD if bold else settings.FONT_SMALL)
        lbl.grid(row=r, column=0, columnspan=3, sticky="we", pady=(6, 2))
        return lbl

    def set_message(self, text: str) -> None:
        self.msg_var.set(text)

    # ------------------------------------------------------------ أزرار
    def _try_save(self) -> None:
        try:
            data = self._collect()
        except ValueError as exc:
            self.set_message(str(exc))
            return
        ok = True
        if self._on_save is not None:
            try:
                ok = bool(self._on_save(data))
            except ValueError as exc:
                self.set_message(str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _log.exception("فشل حفظ الحوار")
                self.set_message(f"خطأ: {exc}")
                return
        if ok:
            self.saved = True
            self.close()

    def _collect(self) -> dict[str, Any]:  # تُستبدل في الأبناء
        return {}

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def make_save_button(parent: tk.Misc, command: Callable[[], Any]) -> ttk.Button:
    """زر حفظ بارز (primary)."""
    btn = ttk.Button(parent, text="💾 حفظ", style="Primary.TButton", command=command)
    btn.pack(side="right", padx=6)
    return btn


def dialog_result(parent: tk.Misc, title: str, fields: list[tuple[str, str, str]],
                  ) -> dict[str, str] | None:
    """
    حوار إدخال بسيط متعدد الحقول (بديل askstring الموسّع).
    fields: [(key, label, initial), ...] — يعيد قاموساً أو None عند الإلغاء.
    """
    box = FormDialog(parent, title)
    result: dict[str, str] = {}
    for key, label, initial in fields:
        entry = ttk.Entry(box.body, width=34)
        entry.insert(0, initial)
        box.add_field(key, entry, label)
        if not result and len(fields) > 0:
            result.setdefault(key, initial)

    holder: dict[str, Any] = {"data": None}

    def _collect() -> dict[str, Any]:
        return {k: v.get().strip() for k, v in box.fields.items()}

    def _save(data: dict[str, Any]) -> bool:
        holder["data"] = data
        return True

    box._collect = _collect  # type: ignore[method-assign]
    box._on_save = _save  # type: ignore[assignment]
    box.winfo_toplevel().wait_window(box)
    return holder["data"]  # type: ignore[return-value]


__all__ = ["FormDialog", "make_save_button", "dialog_result"]
