"""
ui/__init__.py
--------------
حزمة واجهة المستخدم (Presentation Layer) لـ FeedMixer ERP v3.0.

المحتوى:
    styles.py      : تهيئة ثيمات ttk ووضع RTL العام.
    widgets.py     : أدوات قابلة لإعادة الاستخدام (أزرار، بحث Treeview، تواريخ).
    login.py       : نافذة تسجيل الدخول (LoginDialog).
    main_window.py : النافذة الرئيسية FeedMixerERP(tk.Tk) و13 تبويباً.
    tabs/          : التبويبات (واحد لكل شاشة وظيفية).
    dialogs/       : الحوارات Modal لإدخال/تعديل السجلات.

القاعدة المعمارية:
    ui تستورد من services/ و data/ و core/ فقط — ولا يُستورد منها إلا في app.py.
"""

__all__: list[str] = []
