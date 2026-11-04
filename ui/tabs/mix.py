"""
ui/tabs/mix.py
--------------
تبويب «الخلطة»: شاشة إنشاء/تعديل فاتورة الخلطة.

إصلاح تجميد السعر:
    - عند تحميل فاتورة قائمة (load_invoice): نحمل unit_price المجمّد من mix_items.
    - عند العرض (_render_items): نستخدم price_item_frozen للسعر المجمّد.
    - عند الحفظ في وضع التعديل: نستخدم price_items_frozen — لا نُعيد التسعير حيًّا.
    - عند الإنشاء الجديد: السعر حيّ من materials (سلوك مقصود).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from config import settings
from core import cache
from core.logger import get_logger
from core.permissions import has_permission
from core.utils import format_money, safe_eval_math, safe_float, today_str
from data import invoices_repo
from services import mix_service
from ui.tabs._common import clear_tree
from ui.widgets import make_date_entry

_log = get_logger("ui.tabs.mix")


class MixController:
    """منطق شاشة الخلطة كاملة."""

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app = app
        self.items: list[dict[str, Any]] = []
        self.current_mix_number: str = ""
        self.last_saved_number: str = ""
        self._loaded_invoice_items: dict[str, float] = {}
        self._build(parent)
        self.refresh()
        self._recalc()

    # ============================================================ البناء
    def _build(self, parent: tk.Misc) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(0, 4))
        self.title_lbl = ttk.Label(head, text="🧪 خلطة جديدة", font=settings.FONT_LARGE_BOLD)
        self.title_lbl.pack(side="right")
        self.number_lbl = ttk.Label(head, text="", font=settings.FONT_MEDIUM)
        self.number_lbl.pack(side="right", padx=12)

        form = ttk.LabelFrame(parent, text="بيانات الخلطة", padding=6)
        form.pack(fill="x", pady=4)

        r1 = ttk.Frame(form)
        r1.pack(fill="x", pady=2)

        ttk.Label(r1, text="التاريخ:", width=10, anchor="e").pack(side="right")
        self.date_field = make_date_entry(r1, initial=today_str())

        ttk.Label(r1, text="المزرعة:", width=10, anchor="e").pack(side="right", padx=(14, 0))
        self.farm_var = tk.StringVar(master=r1)
        self.farm_combo = ttk.Combobox(r1, textvariable=self.farm_var, width=20,
                                       state="readonly", values=[])
        self.farm_combo.pack(side="right", padx=3)
        self.farm_combo.bind("<<ComboboxSelected>>", lambda _e: self._recalc())

        ttk.Label(r1, text="الحالة:", width=8, anchor="e").pack(side="right", padx=(14, 0))
        self.pay_var = tk.StringVar(master=r1)
        self.pay_combo = ttk.Combobox(r1, textvariable=self.pay_var, width=9,
                                      state="readonly",
                                      values=list(settings.PAYMENT_STATUSES))
        self.pay_combo.set("unpaid")
        self.pay_combo.pack(side="right", padx=3)

        r2 = ttk.Frame(form)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="العامل:", width=10, anchor="e").pack(side="right")
        self.worker_var = tk.StringVar(master=r2)
        ttk.Entry(r2, textvariable=self.worker_var, width=20).pack(side="right", padx=3)

        ttk.Label(r2, text="وصفة:", width=8, anchor="e").pack(side="right", padx=(14, 0))
        self.recipe_var = tk.StringVar(master=r2)
        self.recipe_combo = ttk.Combobox(r2, textvariable=self.recipe_var, width=20,
                                         state="readonly", values=[])
        self.recipe_combo.pack(side="right", padx=3)
        make_btn = ttk.Button(r2, text="تطبيق", command=self.apply_recipe)
        make_btn.pack(side="right", padx=3)

        ttk.Label(r2, text="ملاحظات:", width=8, anchor="e").pack(side="right", padx=(14, 0))
        self.notes_var = tk.StringVar(master=r2)
        ttk.Entry(r2, textvariable=self.notes_var, width=40).pack(side="right", padx=3)

        # جدول البنود
        items_frame = ttk.LabelFrame(parent, text="المكونات (تعديل مباشر داخل الجدول)",
                                     padding=4)
        items_frame.pack(fill="both", expand=True, pady=4)

        cols = ("material", "qty_kg", "unit_price", "total", "source")
        self.tree = ttk.Treeview(items_frame, columns=cols, show="headings",
                                 selectmode="browse")
        headings = (("material", "المادة", 180), ("qty_kg", "الكمية (كغ)", 110),
                    ("unit_price", "سعر الكغ", 110), ("total", "الإجمالي", 120),
                    ("source", "مصدر السعر", 100))
        for col, title, width in headings:
            self.tree.heading(col, text=title, anchor="center")
            self.tree.column(col, width=width, anchor="center", stretch=True)
        vsb = ttk.Scrollbar(items_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.edit_selected_item())
        self.tree.bind("<Delete>", lambda _e: self.remove_selected_item())

        btns = ttk.Frame(parent)
        btns.pack(fill="x", pady=2)
        for text, cmd in (("➕ إضافة بند", self.add_item_dialog),
                          ("✏️ تعديل البند", self.edit_selected_item),
                          ("➖ حذف البند", self.remove_selected_item),
                          ("🧹 تفريغ", self.clear_items)):
            ttk.Button(btns, text=text, command=cmd).pack(side="right", padx=3)

        # لوحة المعاينة
        calc = ttk.LabelFrame(parent, text="الحساب التلقائي", padding=6)
        calc.pack(fill="x", pady=4)
        self.preview_vars: dict[str, tk.StringVar] = {}
        keys = (("weight", "الوزن"), ("billable", "أطنان فوترة"), ("feed", "العلف"),
                ("elec", "كهرباء"), ("labor", "عمال"), ("transport", "نقل"),
                ("total", "الإجمالي"))
        for row_i, pair in enumerate((keys[:4], keys[4:])):
            line = ttk.Frame(calc)
            line.pack(fill="x", pady=1)
            for key, label in pair:
                var = tk.StringVar(master=line, value="-")
                self.preview_vars[key] = var
                cell = ttk.Frame(line)
                cell.pack(side="right", expand=True, fill="x", padx=4)
                ttk.Label(cell, text=f"{label}:", font=settings.FONT_SMALL).pack(anchor="e")
                ttk.Label(cell, textvariable=var, font=settings.FONT_MEDIUM).pack(anchor="e")

        net_row = ttk.Frame(calc)
        net_row.pack(fill="x", pady=(6, 0))
        ttk.Label(net_row, text="صافي الخلطة:", font=settings.FONT_BOLD).pack(side="right")
        self.net_var = tk.StringVar(master=net_row, value="-")
        self.net_entry = ttk.Entry(net_row, textvariable=self.net_var, width=16,
                                   font=settings.FONT_MEDIUM, justify="center")
        self.net_entry.pack(side="right", padx=4)
        self.net_edit_flag = tk.BooleanVar(master=net_row, value=False)
        ttk.Checkbutton(net_row, text="تعديل يدوي للصافي",
                        variable=self.net_edit_flag,
                        command=self._on_manual_net_toggle).pack(side="right", padx=6)
        self.net_status_lbl = ttk.Label(net_row, text="", font=settings.FONT_SMALL)
        self.net_status_lbl.pack(side="left")

        # أزرار الحفظ
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(4, 2))
        can_write = has_permission(self.app.user, "mix.create")
        self.save_btn = ttk.Button(actions, text="💾 حفظ الخلطة (Ctrl+S)",
                                   command=self.save_current,
                                   style="Primary.TButton" if hasattr(ttk.Style(), "") else None)
        self.save_btn.pack(side="right", padx=3)
        if not can_write:
            self.save_btn.configure(state="disabled")
        ttk.Button(actions, text="🆕 جديدة (Ctrl+N)", command=self.new_record)\
            .pack(side="right", padx=3)
        ttk.Button(actions, text="🖨️ طباعة (Ctrl+P)", command=self.print_current)\
            .pack(side="right", padx=3)
        self.load_hint = ttk.Label(actions, text="", font=settings.FONT_SMALL)
        self.load_hint.pack(side="left")

    # ============================================================ تحديث
    def refresh(self) -> None:
        try:
            farms = cache.farm_names(force=True)
            recipes = [f"{r['id']}|{r['name']}" for r in self._list_recipes()]
        except Exception:  # noqa: BLE001
            _log.exception("فشل تحديث قوائم الخلطة")
            return
        self.farm_combo.configure(values=farms)
        if farms and not self.farm_var.get():
            self.farm_var.set(farms[0])
        self.recipe_combo.configure(values=["|بدون وصفة"] + recipes)
        self._recalc()

    @staticmethod
    def _list_recipes() -> list[dict[str, Any]]:
        from data import recipes_repo
        try:
            return recipes_repo.list_recipes()
        except Exception:  # noqa: BLE001
            _log.exception("تعذّر قراءة الوصفات")
            return []

    # ============================================================ البنود
    def add_item_dialog(self) -> None:
        win = self._item_window(title="إضافة بند", item=None)
        win.deiconify()

    def edit_selected_item(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.app.toast("اختر بنداً من الجدول أولاً", "warning")
            return
        self._item_window(title="تعديل بند", item=self.items[idx])

    def remove_selected_item(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        del self.items[idx]
        self._render_items()
        self._recalc()

    def clear_items(self) -> None:
        if self.items and not self._confirm("تفريغ كل البنود؟"):
            return
        self.items = []
        self._render_items()
        self._recalc()

    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except (TypeError, ValueError):
            return None

    def _item_window(self, title: str, item: dict[str, Any] | None) -> tk.Toplevel:
        """نافذة إدخال/تعديل بند مع حساب لحظي للإجمالي."""
        top = tk.Toplevel(self.tree.winfo_toplevel())
        top.title(title)
        top.geometry("420x260")
        top.transient(self.tree.winfo_toplevel())
        frame = ttk.Frame(top, padding=10)
        frame.pack(fill="both", expand=True)

        names = cache.material_names(force=True)
        ttk.Label(frame, text="المادة:").grid(row=0, column=1, sticky="e", pady=4)
        mat_var = tk.StringVar(master=frame, value=(item or {}).get("material_name", ""))
        combo = ttk.Combobox(frame, textvariable=mat_var, values=names, width=22)
        combo.grid(row=0, column=0, sticky="ew", pady=4)

        ttk.Label(frame, text="الكمية (كغ) — يُقبل تعبير مثل 3*500:").grid(
            row=1, column=1, sticky="e", pady=4)
        qty_var = tk.StringVar(master=frame,
                               value=str((item or {}).get("qty_kg", "")) if item else "")
        qty_entry = ttk.Entry(frame, textvariable=qty_var, width=24)
        qty_entry.grid(row=1, column=0, sticky="ew", pady=4)

        ttk.Label(frame, text="سعر الكغ (0 = تلقائي من المواد):").grid(
            row=2, column=1, sticky="e", pady=4)

        # السعر الافتراضي: المجمّد إن وُجد، وإلا اتركه فارغًا ليُحسب تلقائيًا
        initial_price = ""
        if item:
            frozen = float(item.get("unit_price") or 0)
            if frozen > 0:
                initial_price = f"{frozen:.6f}"
            else:
                initial_price = str(item.get("unit_price_override", "") or "")
        price_var = tk.StringVar(master=frame, value=initial_price)
        ttk.Entry(frame, textvariable=price_var, width=24).grid(row=2, column=0,
                                                                sticky="ew", pady=4)

        live = ttk.Label(frame, text="", font=settings.FONT_MEDIUM)
        live.grid(row=3, column=0, columnspan=2, pady=6)

        def _preview(*_a: Any) -> None:
            priced = mix_service.price_item(mat_var.get(),
                                            safe_eval_math(qty_var.get()),
                                            safe_eval_math(price_var.get()) or None)
            live.configure(text=f"سعر الكغ: {priced['unit_price']:.4f} | "
                                f"الإجمالي: {format_money(priced['total_price'])}")

        for var in (mat_var, qty_var, price_var):
            var.trace_add("write", _preview)
        _preview()

        def _save() -> None:
            name = mat_var.get().strip()
            kg = safe_eval_math(qty_var.get())
            override = safe_eval_math(price_var.get())
            if not name:
                self.app.toast("اختر المادة", "error")
                return
            if kg <= 0:
                self.app.toast("الكمية يجب أن تكون أكبر من صفر", "error")
                return
            entry: dict[str, Any] = {"material_name": name, "qty_kg": kg}
            if override > 0:
                entry["unit_price_override"] = override
                entry["unit_price"] = override      # ← جمّده في البند
            idx = self._selected_index() if item is not None else None
            if item is not None and idx is not None:
                self.items[idx] = entry
            else:
                self.items.append(entry)
            self._render_items()
            self._recalc()
            top.destroy()

        bar = ttk.Frame(frame)
        bar.grid(row=4, column=0, columnspan=2, pady=8)
        ttk.Button(bar, text="✅ موافق", command=_save).pack(side="right", padx=4)
        ttk.Button(bar, text="إلغاء", command=top.destroy).pack(side="right", padx=4)
        qty_entry.focus_set()
        top.bind("<Return>", lambda _e: _save())
        top.bind("<Escape>", lambda _e: top.destroy())
        return top

    def _render_items(self) -> None:
        """
        يعرض البنود في الجدول.
        يستخدم السعر المجمّد إن وُجد، وإلا السعر الحي (بند جديد).
        """
        clear_tree(self.tree)
        for i, it in enumerate(self.items):
            frozen = safe_float(it.get("unit_price"), 0.0)
            if frozen > 0:
                priced = mix_service.price_item_frozen(
                    it["material_name"], it["qty_kg"], frozen)
            else:
                priced = mix_service.price_item(
                    it["material_name"], it["qty_kg"], it.get("unit_price_override"))
            self.tree.insert("", "end", iid=str(i), values=(
                priced["material_name"],
                f"{priced['qty_kg']:,.0f}",
                f"{priced['unit_price']:.4f}",
                f"{priced['total_price']:,.2f}",
                priced["source"],
            ))

    # ============================================================ الحساب
    def _on_manual_net_toggle(self) -> None:
        manual = bool(self.net_edit_flag.get())
        state = "normal" if manual else "readonly"
        try:
            self.net_entry.configure(state=state)
        except tk.TclError:
            pass
        if not manual:
            self._recalc()
        self.net_status_lbl.configure(
            text="✍️ صافي يدوي" if manual else "محسوب تلقائياً")

    def _recalc(self) -> None:
        farm = self.farm_var.get() if hasattr(self, "farm_var") else ""
        try:
            preview = mix_service.preview_totals_for_ui(self.items, farm)
        except Exception:  # noqa: BLE001
            _log.exception("فشل المعاينة الحسابية")
            return
        for key, text in (("weight", preview["weight"]), ("billable", preview["billable"]),
                          ("feed", preview["feed"]), ("elec", preview["elec"]),
                          ("labor", preview["labor"]), ("transport", preview["transport"]),
                          ("total", preview["total"])):
            self.preview_vars[key].set(text)
        if not self.net_edit_flag.get():
            self.net_var.set(preview["total"])

    # ============================================================ الوصفات
    def apply_recipe(self, recipe_id: int | None = None) -> None:
        if recipe_id is not None:
            target = f"{int(recipe_id)}|"
            values = [str(v) for v in self.recipe_combo.cget("values") or []]
            match = next((v for v in values if v.startswith(target)), "")
            if match:
                self.recipe_var.set(match)
            else:
                try:
                    self.refresh()
                except Exception:  # noqa: BLE001
                    pass
                values = [str(v) for v in self.recipe_combo.cget("values") or []]
                match = next((v for v in values if v.startswith(target)), "")
                if not match:
                    self.app.toast("الوصفة غير موجودة في قائمة الخلطة", "warning")
                    return
                self.recipe_var.set(match)
        raw = self.recipe_var.get()
        rid = raw.split("|", 1)[0].strip()
        if not rid.isdigit():
            self.app.toast("اختر وصفة من القائمة ثم اضغط تطبيق", "warning")
            return
        try:
            items = mix_service.recipe_to_items(int(rid))
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل تطبيق الوصفة")
            self.app.toast(f"فشل تطبيق الوصفة: {exc}", "error")
            return
        if not items:
            self.app.toast("الوصفة لا تحتوي بنوداً", "warning")
            return
        self.items = list(items)
        self._render_items()
        self._recalc()
        name = raw.split("|", 1)[-1]
        self.app.toast(f"تم تطبيق الوصفة «{name}» ({len(items)} بند)", "success")

    # ============================================================ نموذج
    def new_record(self) -> None:
        self.current_mix_number = ""
        self._loaded_invoice_items = {}
        self.date_field["set"](today_str())
        if self.farm_combo["values"]:
            self.farm_var.set(self.farm_combo["values"][0])
        self.worker_var.set("")
        self.notes_var.set("")
        self.pay_combo.set("unpaid")
        self.recipe_combo.set("|بدون وصفة")
        self.net_edit_flag.set(False)
        self._on_manual_net_toggle()
        self.items = []
        self._render_items()
        self._recalc()
        self.title_lbl.configure(text="🧪 خلطة جديدة")
        self.number_lbl.configure(text="")
        self.load_hint.configure(text="")
        self.app.set_status("نموذج خلطة جديد جاهز")

    def load_invoice(self, mix_number: str) -> None:
        """
        يفتح فاتورة قائمة للتعديل — يحمل السعر المجمّد من mix_items.unit_price.
        """
        inv = invoices_repo.get_invoice(mix_number)
        if not inv:
            self.app.toast(f"الفاتورة {mix_number} غير موجودة", "error")
            return
        self.current_mix_number = mix_number
        self.date_field["set"](str(inv.get("mix_date", today_str())))
        self.farm_var.set(str(inv.get("farm_name", "")))
        self.worker_var.set(str(inv.get("worker_name", "")))
        self.notes_var.set(str(inv.get("notes", "") or ""))
        self.pay_combo.set(str(inv.get("payment_status", "unpaid")))
        # نحمل unit_price المجمّد + نضعه أيضاً في unit_price_override
        self.items = [
            {
                "material_name": str(r.get("material_name")),
                "qty_kg": float(r.get("qty_kg", 0) or 0),
                "unit_price": float(r.get("unit_price", 0) or 0),         # ← المجمّد
                "unit_price_override": float(r.get("unit_price", 0) or 0) or None,
            }
            for r in (inv.get("items") or [])
        ]
        self._loaded_invoice_items = {i["material_name"]: i["qty_kg"] for i in self.items}
        manual = bool(inv.get("net_cost_manually_edited"))
        self.net_edit_flag.set(manual)
        self._on_manual_net_toggle()
        if manual:
            self.net_var.set(f"{float(inv.get('mixer_net_cost', 0)):,.2f}")
        self._render_items()
        self._recalc()
        self.title_lbl.configure(text=f"🧪 تعديل فاتورة")
        self.number_lbl.configure(text=f"رقم: {mix_number}")
        self.load_hint.configure(text="⚠️ أنت في وضع تعديل فاتورة قائمة")
        self.app.open_tab("mix")

    # ============================================================ الحفظ
    def save_current(self) -> None:
        if not has_permission(self.app.user, "mix.create"):
            self.app.toast("لا تملك صلاحية حفظ الخلطات", "error")
            return
        if not self.items:
            self.app.toast("أضف بنداً واحداً على الأقل", "warning")
            return
        farm = self.farm_var.get().strip()
        if not farm:
            self.app.toast("اختر المزرعة", "warning")
            return

        deficits = mix_service.check_items_availability(
            self.items, self.current_mix_number or None)
        if deficits:
            report = mix_service.format_deficits_report(deficits)
            if not self._confirm(report + "\n\nالحفظ رغم العجز؟ (سيُسجَّل تحذير)",
                                 danger=True):
                self.app.toast("تم إيقاف الحفظ بسبب عجز المخزون", "warning")
                return

        net_override: float | None = None
        if self.net_edit_flag.get():
            val = safe_eval_math(self.net_var.get().replace(",", ""))
            if val <= 0:
                self.app.toast("الصافي اليدوي غير صالح", "error")
                return
            net_override = val

        recipe_id: int | None = None
        rid_raw = self.recipe_var.get().split("|", 1)[0].strip()
        if rid_raw.isdigit():
            recipe_id = int(rid_raw)

        user = str(self.app.user.get("username", "")) if hasattr(self.app, "user") else None
        try:
            if self.current_mix_number:
                # ==== وضع التعديل: احترم السعر المجمّد ====
                items_for_repo = mix_service.price_items_frozen(self.items)
                ok = invoices_repo.update_invoice(
                    self.current_mix_number,
                    farm_name=farm,
                    worker_name=self.worker_var.get().strip(),
                    items=items_for_repo,
                    notes=self.notes_var.get().strip(),
                    payment_status=self.pay_var.get(),
                    net_cost_override=net_override,
                )
                if not ok:
                    raise ValueError("فشل التحديث")
                number = self.current_mix_number
            else:
                # ==== إنشاء جديد: السعر حيّ (سلوك مقصود) ====
                number = mix_service.save_mix(
                    mix_date=self.date_field["get"](),
                    farm_name=farm,
                    worker_name=self.worker_var.get().strip(),
                    items=self.items,
                    notes=self.notes_var.get().strip(),
                    payment_status=self.pay_var.get(),
                    net_cost_override=net_override,
                    recipe_id=recipe_id,
                    created_by=user,
                )
        except ValueError as exc:
            _log.warning("رفض حفظ الخلطة: %s", exc)
            self.app.toast(f"رفض الحفظ: {exc}", "error")
            return
        except Exception as exc:  # noqa: BLE001
            _log.exception("خطأ غير متوقع أثناء الحفظ")
            self.app.toast(f"خطأ أثناء الحفظ: {exc}", "error")
            return

        self.last_saved_number = number
        self.current_mix_number = ""
        self.app.toast(f"✅ تم حفظ الخلطة {number}", "success")
        try:
            saved = invoices_repo.get_invoice(number) or {}
            net = float(saved.get("mixer_net_cost", 0) or 0)
        except Exception:  # noqa: BLE001
            net = 0.0
        self.app.set_status(f"حُفظت الخلطة {number} — الصافي {format_money(net)}")
        self.new_record()

    # ============================================================ الطباعة
    def print_current(self) -> None:
        number = self.current_mix_number or self.last_saved_number
        if not number:
            self.app.toast("احفظ الخلطة أولاً ثم اطبعها", "warning")
            return
        try:
            from reports.invoice_html import generate_invoice_html
            html = generate_invoice_html(number)
        except Exception as exc:  # noqa: BLE001
            _log.exception("فشل توليد الفاتورة")
            self.app.toast(f"تعذّر تجهيز الطباعة: {exc}", "error")
            return
        self.app.show_html(f"فاتورة خلطة {number}", html)

    # ============================================================ أدوات
    def _confirm(self, message: str, danger: bool = False) -> bool:
        return bool(messagebox.askyesno(
            "تنبيه مخزون" if danger else "تأكيد", message, icon="warning"))

    def focus_search(self) -> None:
        self.app.open_tab("invoices")


def build(parent: tk.Misc, app: Any) -> MixController:
    """نقطة دخول التبويب."""
    return MixController(parent, app)