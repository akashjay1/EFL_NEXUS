# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('version.txt', '.'), ('build.txt', '.'), ('icon_2.ico', '.'), ('icon.ico', '.'), ('aurora_bg.png', '.'), ('credentials.json', '.'), ('efl_users.json', '.'), ('templates.xlsx', '.'), ('variance_templates.xlsx', '.'), ('assets', 'assets')]
binaries = []
grn_ocr_runtime = __import__('pathlib').Path('assets/grn_ocr')
if not (grn_ocr_runtime / 'tesseract.exe').is_file() or not (grn_ocr_runtime / 'tessdata/eng.traineddata').is_file():
    raise RuntimeError('Run python prepare_grn_ocr.py before packaging NEXUS.')
hiddenimports = ['pandas', 'openpyxl', 'openpyxl.styles', 'requests', 'dotenv', 'korber_tool', 'whatsapp_gdn', 'whatsapp_monitor', 'whatsapp_controller', 'whatsapp_page', 'whatsapp_inbox', 'reconciliation_tool', 'korber_login_bot', 'outlook_email_gui', 'KPI', 'kpi_profile', 'reconciliation_queue', 'website_data_grabber', 'patch_auditship_credentials', 'gspread', 'oauth2client', 'oauth2client.service_account', 'updater', 'win32com', 'win32com.client', 'pythoncom', 'win32api', 'win32cred', 'winreg', 'customtkinter', 'queue', 'hashlib', 'calendar']
tmp_ret = collect_all('selenium')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webdriver_manager')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('zxingcpp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# OpenCV and NumPy use their supplied PyInstaller hooks; collecting their test
# suites as hidden imports unnecessarily pulls development modules into releases.
hiddenimports += ['grn_ocr', 'grn_cloud_ocr', 'grn_ocr_settings', 'whatsapp_media', 'whatsapp_grn', 'whatsapp_grn_inbox', 'cv2', 'numpy']
tmp_ret = collect_all('openpyxl')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('gspread')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('oauth2client')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EFL_NEXUS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon_2.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EFL_NEXUS',
)
