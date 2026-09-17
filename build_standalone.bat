@echo off
echo ========================================================
echo   EFL NEXUS - Directory Mode Application & Installer
echo ========================================================
echo.

<<<<<<< Updated upstream
echo [1/4] Building high-speed directory-mode EFL_NEXUS...
pyinstaller main_app.py --name=EFL_NEXUS --noconsole --noconfirm --onedir --icon=icon_2.ico --collect-all=selenium --collect-all=webdriver_manager --collect-all=PIL --collect-all=openpyxl --collect-all=customtkinter --collect-all=gspread --collect-all=oauth2client --hidden-import=pandas --hidden-import=openpyxl --hidden-import=openpyxl.styles --hidden-import=requests --hidden-import=dotenv --hidden-import=korber_tool --hidden-import=reconciliation_tool --hidden-import=korber_login_bot --hidden-import=outlook_email_gui --hidden-import=efldatamanager --hidden-import=gspread --hidden-import=oauth2client --hidden-import=oauth2client.service_account --hidden-import=updater --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --hidden-import=win32api --hidden-import=winreg --hidden-import=customtkinter --hidden-import=queue --hidden-import=hashlib --hidden-import=calendar --add-data "version.txt;." --add-data "icon_2.ico;." --add-data "icon.ico;." --add-data "aurora_bg.png;." --add-data "credentials.json;." --add-data "efl_users.json;." --add-data "sent_log.xlsx;." --add-data "assets;assets"
=======
:: Detect Python/PyInstaller command (uv or system)
where uv >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_CMD=uv run python"
    set "PYI_CMD=uv run pyinstaller"
    echo   [Environment] Using uv runner
) else (
    set "PY_CMD=python"
    set "PYI_CMD=pyinstaller"
    echo   [Environment] Using system Python
)

:: Read current version and build number
if not exist "version.txt" (
    echo [ERROR] version.txt not found!
    pause
    exit /b 1
)
set "VER="
for /f "usebackq tokens=* delims=" %%V in ("version.txt") do set VER=%%V
if /i "!VER:~0,10!"=="EFL_NEXUS_" set "VER=!VER:~10!"
if /i "!VER:~0,1!"=="v" set "VER=!VER:~1!"
if not defined VER (
    echo [ERROR] version.txt has no version number!
    pause
    exit /b 1
)
set BUILD=0
if exist "build.txt" (
    for /f "usebackq tokens=* delims=" %%B in ("build.txt") do set BUILD=%%B
)
echo   Version: %VER%  Build: %BUILD%
echo.

if not exist "Korber_AuditShip\KORBER AuditShip.exe" (
    echo [ERROR] Korber_AuditShip\KORBER AuditShip.exe not found!
    pause
    exit /b 1
)
if not exist "Korber_AuditShip\_internal\python314.dll" (
    echo [ERROR] Korber_AuditShip runtime folder is incomplete!
    pause
    exit /b 1
)

%PY_CMD% patch_auditship_credentials.py
if %errorlevel% neq 0 (
    echo [ERROR] Could not install the AuditShip credential bridge.
    pause
    exit /b %errorlevel%
)

echo [1/5] Building high-speed directory-mode EFL_NEXUS...
%PYI_CMD% main_app.py --name=EFL_NEXUS --noconsole --noconfirm --onedir --icon=icon_2.ico --collect-all=selenium --collect-all=webdriver_manager --collect-all=webview --collect-all=pythonnet --collect-all=clr_loader --collect-all=PIL --collect-all=openpyxl --collect-all=customtkinter --collect-all=gspread --collect-all=oauth2client --hidden-import=pandas --hidden-import=openpyxl --hidden-import=openpyxl.styles --hidden-import=requests --hidden-import=dotenv --hidden-import=korber_tool --hidden-import=reconciliation_tool --hidden-import=korber_login_bot --hidden-import=outlook_email_gui --hidden-import=KPI --hidden-import=kpi_profile --hidden-import=reconciliation_queue --hidden-import=website_data_grabber --hidden-import=patch_auditship_credentials --hidden-import=gspread --hidden-import=oauth2client --hidden-import=oauth2client.service_account --hidden-import=updater --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --hidden-import=win32api --hidden-import=win32cred --hidden-import=winreg --hidden-import=customtkinter --hidden-import=queue --hidden-import=hashlib --hidden-import=calendar --add-data "version.txt;." --add-data "build.txt;." --add-data "icon_2.ico;." --add-data "icon.ico;." --add-data "aurora_bg.png;." --add-data "credentials.json;." --add-data "efl_users.json;." --add-data "sent_log.xlsx;." --add-data "templates.xlsx;." --add-data "variance_templates.xlsx;." --add-data "assets;assets"
>>>>>>> Stashed changes
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build EFL_NEXUS
    pause
    exit /b %errorlevel%
)

echo.
echo [2/4] Building companion updater.exe into dist\EFL_NEXUS...
pyinstaller updater.py --name=updater --noconsole --noconfirm --onefile --distpath=dist\EFL_NEXUS --icon=icon_2.ico --hidden-import=requests --add-data "icon_2.ico;." --add-data "icon.ico;."
if %errorlevel% neq 0 (
    echo [WARNING] Failed to build updater.exe (skipping)
)

echo.
echo Deploying default templates, credentials and assets to dist\EFL_NEXUS...
for %%F in (templates.xlsx variance_templates.xlsx sent_log.xlsx version.txt icon_2.ico icon.ico aurora_bg.png credentials.json efl_users.json) do (
    if exist "%%F" copy /y "%%F" "dist\EFL_NEXUS\" >nul
)
if exist "dist\EFL_NEXUS\config.json" del /f /q "dist\EFL_NEXUS\config.json"

echo.
echo [3/4] Building EFL_NEXUS_Setup.exe (Install Wizard)...
pyinstaller installer_wizard.py --name=EFL_NEXUS_Setup --noconsole --noconfirm --onefile --icon=icon_2.ico --collect-all=PIL --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageTk --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --add-data "dist/EFL_NEXUS;payload"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build EFL_NEXUS_Setup.exe
    pause
    exit /b %errorlevel%
)

echo.
echo [4/4] Creating GitHub Release ZIP package from directory build...
python -c "import zipfile, os, pathlib; ver = open('version.txt').read().strip(); zpath = f'dist/EFL_NEXUS_v{ver}.zip'; src_dir = pathlib.Path('dist/EFL_NEXUS'); z = zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED); [z.write(f, f.relative_to(src_dir)) for f in src_dir.rglob('*') if f.is_file() and not f.name.endswith('.old')]; z.close(); print('Created release zip:', zpath, f'{os.path.getsize(zpath)/1024/1024:.2f} MB')"

echo.
echo ========================================================
echo   Directory Build and Packages Completed Successfully!
echo.
echo   Outputs in %~dp0dist\:
echo     1. EFL_NEXUS\                (Fast Directory Application - Instant Launch)
echo     2. EFL_NEXUS_Setup.exe       (Full Install Wizard)
echo     3. EFL_NEXUS_v[version].zip  (REQUIRED for GitHub In-App Auto-Update)
echo ========================================================
pause
