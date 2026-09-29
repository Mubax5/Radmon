# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("selenium")

datas = [
    ("radmon/admin/icons", "radmon/admin/icons"),
    ("web/dist", "web"),
]
datas += collect_data_files("tzdata")


a = Analysis(
    ["packaging/radmon_entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

admin_a = Analysis(
    ["packaging/radmon_admin_entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
admin_pyz = PYZ(admin_a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RadMon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',
)

admin_exe = EXE(
    admin_pyz,
    admin_a.scripts,
    [],
    exclude_binaries=True,
    name='RadMon Admin',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',
)

coll = COLLECT(
    exe,
    admin_exe,
    a.binaries,
    a.datas,
    admin_a.binaries,
    admin_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RadMon',
)
