# -*- mode: python ; coding: utf-8 -*-
# OneMail PyInstaller 打包配置（单文件、无控制台窗口）
# 构建：venv 中执行  pyinstaller build.spec --noconfirm

a = Analysis(
    ['src/main.py'],
    pathex=['src'],                      # 让分析器找到 core/storage/ui 顶层包
    binaries=[],
    datas=[],
    hiddenimports=[
        'pystray._win32',                # pystray 运行时动态选择后端，需显式声明
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter.test', 'unittest', 'pydoc_data', 'pygments',
        'numpy', 'pandas', 'matplotlib', 'PyQt5', 'PyQt6',  # 防误收压体积
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OneMail',
    debug=False,
    strip=False,
    upx=False,                           # UPX 易触发杀软误报，不用
    console=False,                       # 无控制台窗口
    icon='assets/onemail.ico',
    version=None,
)
