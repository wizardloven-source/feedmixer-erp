"""
ui/dialogs/__init__.py
----------------------
حزمة الحوارات (Farms, Materials, Purchases, Payments, Users, Recipes).

كل حوار كلاس يرث tk.Toplevel ويعمل modal، ويوفّر:
    .result : القاموس المُدخل أو None عند الإلغاء.

المستخدم:
    dlg = FarmDialog(parent, app, farm=<dict أو None>)
    parent.wait_window(dlg)
    if dlg.result is not None:
        farms_repo.upsert_farm(dlg.result)
"""

__all__: list[str] = []
