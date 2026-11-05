# Changelog

جميع التغييرات المهمة في هذا المشروع موثقة في هذا الملف.

التنسيق مبني على [Keep a Changelog](https://keepachangelog.com/ar/1.1.0/)،
والمشروع يتبع [Semantic Versioning](https://semver.org/lang/ar/).

## [3.1.0] - 2026-11-04

### Added
- اختبارات وحدة (97 اختباراً إجمالاً): `test_mix_calc` (تطابق calculate_mix مع _compute_invoice_totals)، `test_inventory_service`، `test_account_service`، `test_invoices_repo`، `test_validators`، `test_permissions`.
- `CHANGELOG.md` (هذا الملف) — سجل التغييرات بتنسيق Keep a Changelog.
- `TreeSearch.refresh_snapshot()` + حدث `<<TreeRefreshed>>` لإصلاح البحث بعد التحديث (F5).
- `notify_refresh(tree)` في `ui/tabs/_common.py` تُبلّغ البحث بتغيّر محتوى الجدول بعد كل `fill_rows`.
- `_farms_repo()` / `_invoices_repo()` / `_settings_repo()` / `_recipes_repo()` (lazy imports) في `services/mix_service.py` لمنع دورات الاستيراد.
- فحص دفاعي في `data/invoices_repo.soft_delete_invoice`: حساب دفعات المزرعة مقابل صافي الفواتير الأخرى قبل الحذف.
- استعلام ثالث للوصفات في `data/farms_repo.farm_transaction_count` (يعيد الآن `{"financial": int, "recipes": int}`).
- معامل `batch_limit` (افتراضي 5000) لـ `_backfill_mix_item_prices` + تسجيل BACKFILL في `audit_log` مع العدادات (updated/processed/total_pending/remaining).
- رسالة «أعد تشغيل التطبيق بعد الاسترجاع» وتسجيل `requires_restart` في audit بعد `restore_backup`.
- توثيق عربي لقاعدة SSOT المحاسبية أعلى `calculate_mix` وفي `README.md`.

### Changed
- **`services/mix_service.calculate_mix`**: الكهرباء والنقل أصبحتا قيمتين ثابتتين (`elec_cost = electricity_fee` و `transport_cost = farm.transport_fee`) لتطابق `data/invoices_repo._compute_invoice_totals` — المعاينة تساوي المحفوظ في قاعدة البيانات حرفياً.
- **`app.py`**: إضافة `try/except/finally` حول `mainloop()` — أي خطأ فادح يُسجَّل كاملاً ويعرض رسالة للمستخدم، و«إنهاء التطبيق» يُسجَّل دائماً (لا مزيد من الإغلاق الصامت).
- **`ui/tabs/mix.py`**: استدعاء `self.app.refresh_all()` تلقائياً بعد حفظ الخلطة الناجح (مع حماية try/except) — التبويبات تعرض الأرقام الجديدة دون F5 يدوي.
- **`data/migrations.py`**: backfill محدود بـ 5000 صف لكل إقلاع (الباقي يكتمل تلقائياً في الإقلاع التالي — idempotent).
- **`data/invoices_repo.update_invoice`**: خوارزمية diff للبنود (SKIP/UPDATE/INSERT/DELETE انتقائي) بدل DELETE+INSERT الكامل — الحفاظ على `id` و`price_snapshot_at` للتدقيق.
- **`data/farms_repo.delete_farm`**: يمنع الحذف عند وجود حركات مالية فقط؛ الوصفات المعلّقة يُسمح بها مع تسجيل تحذير في `audit_log` (بدون إعاقة المستخدم).
- **`ui/main_window`**: بناء التبويبات كسولاً وحفظ حالة Notebook بشكل متوافق مع ttk.

### Fixed
- **`ui/main_window._safe`**: تحويلها من `staticmethod` (كانت تقرأ `wrapper.__self__` وهي دائماً None → لا Toast أبداً) إلى دالة عضو — أخطاء الأزرار تظهر للمستخدم الآن + تسجيل كامل.
- **`ui/tabs/accounts.add_payment`**: انتظار إغلاق `PaymentDialog` عبر `wait_window(dlg)` والتحقق من `dlg.saved` قبل التحديث — لم يعد refresh() يُنفَّذ قبل إدخال البيانات.
- **`ui/tabs/accounts._pick_farm_and_pay`**: نفس الإصلاح (الدالة الداخلية `go`) + تصحيح وسائط `PaymentDialog(parent, app, farm_name=...)`.
- **`ui/login._center_over_master`**: التوسيط في منتصف الشاشة عبر `winfo_screenwidth/height` مباشرة (كان يفشل لأن root المخفي عرضه 1 بكسل) مع fallback للتوسيط فوق master فقط إذا كان `winfo_viewable()`.
- **`ui/tabs/inventory`**: تصحيح مفاتيح الأعمدة لتقرأ `supplied_ton` / `consumed_ton` / `remaining_ton` (كانت تقرأ `in_ton` / `out_ton` / `remaining_kg` غير الموجودة → أعمدة فارغة دائماً)؛ عمود «المتبقي (كغ)» يُحسب محلياً `remaining_ton × 1000`.
- **`ui/tabs/inventory`**: إزالة دالة `adjust_quantity` المشوّهة بترميم فاسد (mojibake) وزرّها المعطل.
- **`ui/widgets.TreeSearch`**: تحديث snapshot تلقائياً بعد أي إعادة بناء للجدول — البحث يجد الصفوف الجديدة بعد F5.
- **`services/inventory_service`**: حذف `set_manual_remaining` (دالة وهمية ترجع False دائماً) وكل استدعاءاتها.
- **`data/invoices_repo.add_invoice` / `set_payment_status`**: التحقق من `payment_status` عبر `validate_choice` ضد `PAYMENT_STATUSES` — لا تتلوث البيانات بقيم عشوائية.
- **`data/invoices_repo.soft_delete_invoice`**: رفض الحذف برسالة عربية واضحة إذا كانت الدفعات تتجاوز صافي الفواتير الأخرى (حماية من رصيد سالب/دفعة يتيمة).
- **`ui/dialogs/base_form.FormDialog`**: معالجة زر X عبر `protocol("WM_DELETE_WINDOW", self.close)`.
- **`ui/tabs/settings_tab._echo_selected`**: إزالة السطر المتناقض (`state="readonly"` ثم `normal`).
- توحيد الحساب: أرقام معاينة الخلطة تساوي أرقام الفاتورة المحفوظة والمطبوعة (اختبار `test_mix_calc` يفرض ذلك).

### Removed
- كود ميت: `adjust_quantity` (واجهة) و`set_manual_remaining` (خدمة).
- ملفات `_*.txt` و`_edit_inventory.py` و`_inspect.py` و`_new_inventory.py` و`_mix_out.txt` وغيرها من مخلفات التطوير من `ui/tabs/`.
- جميع ملفات `*.bak` و`*.bak2` من المستودع.
- زر «تسوية المخزون» (كان يستدعي دالة معطلة ترجع False دائماً).

### Security
- **`.gitignore`**: قواعد لحجب `storage/*.db`، `logs/`، `prints/`، `exports/`، `backups/` — لا تُرفع بيانات حقيقية للمستودع.
- منع تلوث البيانات: `validate_choice` إلزامي لقيم `payment_status` في طبقة البيانات (Defense in Depth).
- تحصين الحذف: مزرعة لها حركات مالية لا تُحذف نهائياً؛ فاتورة يجعل حذفها الرصيد سالباً تُرفض مع توجيه للمستخدم.
- حذف بيانات قاعدة الاختبارات المؤقتة تلقائياً (`tempfile`) وعزل كل اختبار بقاعدة مستقلة.
- المستودع محمي (Private).

## [3.0.0] - 2026-11-04

الإصدار الأولي من FeedMixer ERP (قبل الإصلاحات):
- واجهة Tkinter/ttk عربية RTL مع 13 تبويباً وبناء كسول.
- قاعدة بيانات SQLite3 مع مخطط وترحيلات وبذور افتراضية.
- أدوار (admin/operator/viewer) مع مصفوفة صلاحيات وسجل تدقيق.
- خلطات/فواتير، مخزون، توريدات، مدفوعات، حسابات مزارع، وصفات، تقارير (CSV/Excel/matplotlib).
- نسخ احتياطي واستعادة وفحص سلامة قاعدة البيانات.
- 31 اختبار وحدة (utils + auth).
