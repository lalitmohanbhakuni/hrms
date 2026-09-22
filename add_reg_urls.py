from pathlib import Path

p = Path('core/urls.py')
src = p.read_text()

if 'reg_category_create' in src:
    print("Already added — nothing to do.")
else:
    old = "    path('setup/', views.setup, name='setup'),"
    new = (
        "    path('setup/', views.setup, name='setup'),\n"
        "    path('setup/reg-category/create/',          views.reg_category_create, name='reg_category_create'),\n"
        "    path('setup/reg-category/<int:pk>/edit/',    views.reg_category_edit,   name='reg_category_edit'),\n"
        "    path('setup/reg-category/<int:pk>/delete/',  views.reg_category_delete, name='reg_category_delete'),"
    )
    if old not in src:
        print("❌ Anchor line not found — abort.")
    else:
        p.write_text(src.replace(old, new, 1))
        print("✅ URLs added.")
