# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


project_root = Path(SPECPATH).parent
source_root = project_root / "src"

playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")

datas = [
    (
        str(source_root / "sf6viewer" / "interfaces" / "web"),
        "sf6viewer/interfaces/web",
    ),
    (
        str(source_root / "sf6viewer" / "infrastructure" / "db" / "migrations"),
        "sf6viewer/infrastructure/db/migrations",
    ),
    *playwright_datas,
]

hiddenimports = [
    *playwright_hidden,
    *collect_submodules("uvicorn"),
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]

analysis = Analysis(
    [str(source_root / "sf6viewer" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=playwright_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cefpython3",
        "gi",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "tkinter",
        "webview.platforms.cef",
        "webview.platforms.gtk",
        "webview.platforms.qt",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="SF6Viewer",
    debug=False,
    version=str(project_root / "packaging" / "version_info.txt"),
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
