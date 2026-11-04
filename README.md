# 🌾 FeedMixer ERP v3.1.0

نظام ERP كامل لإدارة **خلاطة الأعلاف** بلغة Python 3.10+ مع واجهة **Tkinter/ttk عربية (RTL)** وقاعدة بيانات **SQLite3**.

---

## ✨ الميزات

| # | الوحدة | الوصف |
|---|--------|-------|
| 1 | 🔐 المستخدمون | ثلاثة أدوار (admin / operator / viewer)، كلمات مرور sha256 + salt عشوائي، نافذة دخول |
| 2 | 🚜 المزارع | إضافة/تعديل/أرشفة/حذف، أجرة نقل افتراضية، هاتف وملاحظات |
| 3 | 🧱 المواد | سعر أساسي + عتالة + هدر، وحدات (ton/kg/fixed)، منع حذف مادة مستخدمة |
| 4 | 🚚 التوريدات | رسوم (تنزيل/عتالة/نقل/أخرى)، حساب السعر الحقيقي/طن تلقائياً، استيراد CSV، طباعة إيصال |
| 5 | 🧪 الخلطات/Fواتير | رقم تلقائي، جدول مكونات، حساب (علف+كهرباء+عمال+نقل)، فحص عجز المخزون، سلة محذوفات، تعديل يدوي للصافي، طباعة HTML |
| 6 | 📦 المخزون | المورد − المستهلك = المتبقي، تنبيه الأصناف < 5 طن |
| 7 | 💰 المدفوعات | نقدي/تحويل/شيك، مرجع وملاحظات، مرتبطة بكشوف الحساب |
| 8 | 📊 حسابات المزارع | الفواتير − المدفوعات = المستحق، كشف حساب HTML قابل للطباعة |
| 9 | 📝 الوصفات | حفظ مجموعة مكونات، تطبيقها بضغطة، نسخ وصفة |
| 10 | 📈 التقارير | تقرير شهري (توريدات vs خلطات)، تصدير CSV/Excel، رسوم matplotlib |
| 11 | 👥 إدارة المستخدمين | CRUD كامل (admin فقط)، تغيير كلمة مرور، حماية آخر admin |
| 12 | 🔍 سجل التدقيق | كل INSERT/UPDATE/DELETE مع القيم القديمة/الجديدة والمستخدم |
| 13 | ⚙️ الإعدادات | أجرة كهرباء وعمال/طن، وضع ليلي/نهاري، نسخ احتياطي واستعادة، فحص سلامة DB |
| 14 | 🎛️ ميزات عامة | بحث فوري في كل جدول، اختصارات، Toast، شريط حالة، حفظ هندسة النافذة |

### الاختصارات
`Ctrl+S` حفظ • `Ctrl+N` جديد • `Ctrl+P` طباعة • `Ctrl+F` بحث • `Ctrl+C` تصدير • `F5` تحديث

---

## 🔧 الإصلاحات الجوهرية في v3.1.0

نفّذ المشروع ست مراحل إصلاح شاملة (التفاصيل الكاملة في `CHANGELOG.md`):

1. **توحيد القواعد المحاسبية (SSOT):** أصبحت `electricity_fee` و`transport_fee` قيمتين ثابتتين في `services/mix_service.calculate_mix` مطابقة تماماً لـ `data/invoices_repo._compute_invoice_totals` — المعاينة في الواجهة تساوي ما يُحفظ في قاعدة البيانات حرفياً.
2. **إصلاحات الواجهة الحرجة:** دالة `_safe` صارت دالة عضو تعرض Toast عند أي خطأ زر؛ `add_payment` ينتظر إغلاق `PaymentDialog` (`wait_window`) قبل التحديث؛ نافذة الدخول تتوسط الشاشة بشكل صحيح.
3. **إصلاحات المخزون والبحث:** أعمدة جدول المخزون تقرأ المفاتيح الصحيحة (`supplied_ton` / `consumed_ton` / `remaining_ton`)؛ `TreeSearch` يحدّث snapshot تلقائياً بعد كل refresh (البحث يعمل بعد F5)؛ حُذف الكود الميت (`adjust_quantity`, `set_manual_remaining`).
4. **تحصين طبقة البيانات:** التحقق من `payment_status` عبر `validate_choice`؛ رفض الحذف الناعم إذا كان سيجعل رصيد المزرعة سالباً؛ `update_invoice` تستخدم diff بدل DELETE+INSERT (يحافظ على IDs وطابع السعر)؛ `delete_farm` يفحص الوصفات المرتبطة ويسجّلها في audit.
5. **تحسينات التشغيل:** `try/except/finally` حول `mainloop()` في `app.py` (لا إغلاق صامت)؛ backfill محدود بـ 5000 صف لكل إقلاع مع تسجيل audit؛ `refresh_all()` تلقائي بعد حفظ الخلطة.
6. **اختبارات شاملة:** ارتفاع التغطية من 31 إلى **97 اختبار وحدة** ناجحاً تغطي الحساب، المخزون، الحسابات، المستودعات، التحقق، والصلاحيات.

---

## 🗂️ هيكل المشروع

```
mixer_erp/
├── app.py                # نقطة الانطلاق (مع try/finally حول mainloop)
├── requirements.txt
├── README.md             # هذا الملف
├── CHANGELOG.md          # سجل التغييرات (Keep a Changelog)
├── config/               # الألوان، الخطوط، الثوابت، المكتبات الاختيارية
├── core/                 # logger, cache, utils, validators, auth, permissions
├── data/                 # connection, schema, migrations, seed + 8 repositories
├── services/             # mix, inventory, account, alert, backup
├── ui/                   # styles, widgets, login, main_window
│   ├── tabs/             # التبويبات (dashboard … settings_tab)
│   └── dialogs/          # نوافذ: توريد/مادة/دفعة/مستخدم/مزرعة/وصفة
├── reports/              # invoice_html, statement_html, receipt_html, exporter
└── tests/                # 97 اختبار وحدة (unittest)
    ├── test_utils.py
    ├── test_auth.py
    ├── test_mix_calc.py            # تطابق calculate_mix مع _compute_invoice_totals
    ├── test_inventory_service.py   # أرصدة المخزون والفواتير المحذوفة
    ├── test_account_service.py     # ملخصات وكشوف حساب المزارع
    ├── test_invoices_repo.py       # diff البنود + تحذير soft_delete
    ├── test_validators.py          # validate_date/username/password/choice
    └── test_permissions.py         # مصفوفة الصلاحيات للأدوار الثلاثة
```

---

## 🚀 التشغيل

```bash
# المتطلبات: Python 3.10+ (tkinter مدمج؛ على Linux: sudo apt install python3-tk)
cd mixer_erp
python app.py
```

- **الدخول الافتراضي:** `admin` / `admin123`
- تُنشأ قاعدة البيانات `storage/mixer_erp.db` والمجلدات (`logs/`, `exports/`, `prints/`, `backups/`) تلقائياً عند أول تشغيل مع زرع البيانات الافتراضية (9 مزارع + 12 مادة + الإعدادات).

### المكتبات الاختيارية
| المكتبة | الوظيفة | عند غيابها |
|---------|---------|------------|
| `tkcalendar` | منتقي تاريخ | إدخال نصي `YYYY-MM-DD` |
| `matplotlib` | رسوم التقارير | بدون رسم بياني |
| `openpyxl` | تصدير Excel | تصدير CSV بدلاً منه |

```bash
pip install -r requirements.txt   # تثبيت الثلاث اختيارياً
```

---

## 🧮 القواعد المحاسبية المعتمدة (Single Source of Truth)

> **القاعدة الذهبية:** `services/mix_service.calculate_mix` و `data/invoices_repo._compute_invoice_totals`
> يجب أن يتطابقا دائماً — المصدر الوحيد للحقيقة هو `invoices_repo`، والعاينة في الواجهة تعرض
> نفس الأرقام التي تُحفظ في قاعدة البيانات. يفرض هذا التطابقَ الاختبارُ `tests/test_mix_calc.py`.

1. **طنان الفوترة (billable_tons):** `int((kg + 249) / 500) * 0.5` (كل 500 كغ = نصف طن، تقريب لأعلى)
2. **سعر كيلو المادة:** `ton → (base+handling+loss)/1000` ، `kg → base+handling+loss` ، `fixed → base`
3. **تكلفة العلف:** `feed_cost = Σ (كمية_كغ × سعر_كغ)`
4. **أجرة الكهرباء:** `elec_cost = electricity_fee` — **قيمة ثابتة لكل خلطة**
   (وليست `billable_tons × rate` حسب الوصف المعتمد في `DEFAULT_SETTINGS`: «أجرة الكهرباء (لكل خلطة)»)
5. **أجور العمال:** `labor_cost = billable_tons × labor_fee_per_ton` — **متغيرة مع الوزن**
6. **أجرة النقل:** `transport_cost = farm.transport_fee` — **قيمة ثابتة لكل فاتورة**
   (خاصة بالمزرعة، وليست `billable_tons × rate`)
7. **الإجمالي:** `total_cost = feed_cost + elec_cost + labor_cost + transport_cost`
8. **الصافي:** الإجمالي (إلا لو عُدّل يدوياً — `net_cost_override` / `manually_edited`)
9. **المستحق على مزرعة:** `Σ الفواتير غير المحذوفة − Σ المدفوعات`

---

## 🧪 الاختبارات

```bash
cd mixer_erp
python -m unittest discover -s tests -t . -v     # 97 اختباراً — جميعها ناجحة
# أو: python -m pytest tests/ -v
```

ملفات الاختبارات (8 ملفات، 97 اختباراً):

| الملف | التغطية |
|-------|---------|
| `test_utils.py` | أدوات الحساب والتحويل (round_money، tons_to_kg، material_kg_price…) |
| `test_auth.py` | تجزئة كلمات المرور، المصادقة، إدارة المستخدمين |
| `test_mix_calc.py` | **تطابق `calculate_mix` مع `_compute_invoice_totals`** على تركيبات متعددة + ثبات الكهرباء |
| `test_inventory_service.py` | أرصدة المخزون (مورد/مستهلك/سالب)، استبعاد الفواتير المحذوفة، low_stock |
| `test_account_service.py` | ملخصات المزارع (عليه/مسدد/له)، كشف الحساب التراكمي، المجاميع العامة |
| `test_invoices_repo.py` | إضافة/تحديث (diff يحفظ IDs وprice_snapshot_at)، حذف ناعم مع تحذير الرصيد السالب، استعادة |
| `test_validators.py` | `validate_date` / `validate_username` / `validate_password` / `validate_choice` |
| `test_permissions.py` | مصفوفة صلاحيات admin/operator/viewer + `require_permission` + تسميات الأدوار |

جميع الاختبارات تستخدم قاعدة بيانات SQLite مؤقتة معزولة (`tempfile`) ولا تلمس بيانات المستخدم الحقيقية.

---

## 🔐 الأمان

- كلمات المرور: `sha256(salt + password)` مع salt عشوائي لكل مستخدم ومقارنة ثابتة الزمن (`hmac.compare_digest`).
- مصفوفة صلاحيات حسب الدور في `core/permissions.py` تطبَّق على الواجهة والعمليات (Defense in Depth).
- سجل تدقيق كامل في جدول `audit_log` (يشمل عمليات BACKFILL وتحذيرات حذف المزارع ذات الوصفات).
- حماية: منع حذف آخر admin نشط، ومنع حذف مادة مستخدمة، ومنع حذف مزرعة لها حركات مالية.
- تحصين المرحلة 4: رفض `payment_status` غير النظامي، ورفض الحذف الناعم الذي يجعل رصيد المزرعة سالباً.
- `.gitignore` يحجب `storage/*.db` و`logs/` و`prints/` و`exports/` — لا تُرفع بيانات حقيقية للمستودع.

## 💾 النسخ الاحتياطي

من تبويب **إعدادات**: إنشاء نسخة احتياطية (timestamped) في `backups/`، استعادة نسخة، وفحص سلامة قاعدة البيانات (`PRAGMA integrity_check`). بعد الاستعادة يعرض التطبيق رسالة تطلب إعادة التشغيل لضمان سلامة الحالة.

---

## 🛣️ التطوير المستقبلي (توصيات للمراحل القادمة)

- **اختبارات UI آلية:** تغطية التفاعلات (أزرار، حوارات) باستخدام إطار مثل `pytest-tk` أو `robotframework`.
- **تصدير PDF:** توليد فواتير وكشوف PDF مباشرة بدلاً من فتح HTML في المتصفح.
- **تحسين رسوم matplotlib:** لوحات اتجاهات (trend lines) ومقارنات شهرية في تبويب التقارير.
- **API REST (FastAPI):** واجهة برمجية للتكامل مع أنظمة خارجية (محاسبة، ERP مركزي، تطبيقات جوال).
- **تعدد الفروع/المخازن:** دعم أكثر من خلاطة/مخزن بنفس القاعدة البيانية.
- **هجرة قاعدة البيانات المنهجية:** نظام ترقيم إصدارات للترحيلات (schema_version) مع backups تلقائية قبل كل ترحيل.
