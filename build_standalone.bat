@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ========================================================
echo   EFL NEXUS - Directory Mode Application ^& Installer
echo ========================================================
echo.

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
for /f "usebackq tokens=* delims=" %%V in ("version.txt") do set VER=%%V
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

echo [1/5] Building high-speed directory-mode EFL_NEXUS...
%PYI_CMD% main_app.py --name=EFL_NEXUS --noconsole --noconfirm --onedir --icon=icon_2.ico --collect-all=selenium --collect-all=webdriver_manager --collect-all=PIL --collect-all=openpyxl --collect-all=customtkinter --collect-all=gspread --collect-all=oauth2client --hidden-import=pandas --hidden-import=openpyxl --hidden-import=openpyxl.styles --hidden-import=requests --hidden-import=dotenv --hidden-import=korber_tool --hidden-import=reconciliation_tool --hidden-import=korber_login_bot --hidden-import=outlook_email_gui --hidden-import=KPI --hidden-import=kpi_profile --hidden-import=reconciliation_queue --hidden-import=patch_auditship_credentials --hidden-import=gspread --hidden-import=oauth2client --hidden-import=oauth2client.service_account --hidden-import=updater --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --hidden-import=win32api --hidden-import=winreg --hidden-import=customtkinter --hidden-import=queue --hidden-import=hashlib --hidden-import=calendar --add-data "version.txt;." --add-data "build.txt;." --add-data "icon_2.ico;." --add-data "icon.ico;." --add-data "aurora_bg.png;." --add-data "credentials.json;." --add-data "efl_users.json;." --add-data "sent_log.xlsx;." --add-data "templates.xlsx;." --add-data "variance_templates.xlsx;." --add-data "assets;assets"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build EFL_NEXUS
    pause
    exit /b %errorlevel%
)

echo.
echo [2/5] Building companion updater.exe into dist\EFL_NEXUS...
%PYI_CMD% updater.py --name=updater --noconsole --noconfirm --onefile --distpath=dist\EFL_NEXUS --icon=icon_2.ico --hidden-import=requests --add-data "icon_2.ico;." --add-data "icon.ico;."
if %errorlevel% neq 0 (
    echo [WARNING] Failed to build updater.exe (skipping)
)

echo.
echo Deploying default templates, credentials and assets to dist\EFL_NEXUS...
for %%F in (templates.xlsx variance_templates.xlsx sent_log.xlsx version.txt build.txt icon_2.ico icon.ico aurora_bg.png credentials.json efl_users.json) do (
    if exist "%%F" copy /y "%%F" "dist\EFL_NEXUS\" >nul
)
if exist "dist\EFL_NEXUS\config.json" del /f /q "dist\EFL_NEXUS\config.json"
if exist "dist\EFL_NEXUS\reconciliation_queue.json" del /f /q "dist\EFL_NEXUS\reconciliation_queue.json"
if exist "dist\EFL_NEXUS\updater.log" del /f /q "dist\EFL_NEXUS\updater.log"

:: Keep AuditShip's complete standalone distribution beside the main executable.
:: The installer payload and release ZIP both include this directory recursively.
echo.
echo Deploying Korber_AuditShip to dist\EFL_NEXUS\Korber_AuditShip...
robocopy "Korber_AuditShip" "dist\EFL_NEXUS\Korber_AuditShip" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS
if errorlevel 8 (
    echo [ERROR] Failed to copy the Korber_AuditShip folder. Packaging stopped.
    pause
    exit /b 1
)
if not exist "dist\EFL_NEXUS\Korber_AuditShip\KORBER AuditShip.exe" (
    echo [ERROR] The packaged AuditShip executable is missing.
    pause
    exit /b 1
)
if not exist "dist\EFL_NEXUS\Korber_AuditShip\_internal\python314.dll" (
    echo [ERROR] The packaged AuditShip runtime is incomplete.
    pause
    exit /b 1
)

echo.
echo [3/5] Building EFL_NEXUS_Setup.exe (Install Wizard)...
%PYI_CMD% installer_wizard.py --name=EFL_NEXUS_Setup --noconsole --noconfirm --onefile --icon=icon_2.ico --collect-all=PIL --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageTk --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --add-data "dist/EFL_NEXUS;payload"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build EFL_NEXUS_Setup.exe
    pause
    exit /b %errorlevel%
)

echo.
echo [4/5] Creating GitHub Release ZIP package from directory build...
%PY_CMD% -c "import zipfile, os, pathlib; ver = open('version.txt').read().strip(); zpath = f'dist/EFL_NEXUS_v{ver}.zip'; src_dir = pathlib.Path('dist/EFL_NEXUS'); z = zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED); [z.write(f, f.relative_to(src_dir)) for f in src_dir.rglob('*') if f.is_file() and not f.name.endswith('.old')]; z.close(); print('Created release zip:', zpath, f'{os.path.getsize(zpath)/1024/1024:.2f} MB')"

echo.
echo [5/5] Generating initial patch ZIP (build %BUILD%)...
%PY_CMD% create_patch.py --new-dir dist\EFL_NEXUS --auto-find-prev dist\ --version %VER% --build %BUILD% --output-dir dist
if %errorlevel% equ 0 (
    echo   [OK] Patch ZIP: dist\EFL_Nexus_Patch_v%VER%_b%BUILD%.zip
) else (
    echo   [INFO] No patch generated (first release or no previous ZIP in dist\).
    echo         For a hotfix, run: create_patch.bat
)

echo.
echo ========================================================
echo   Directory Build and Packages Completed Successfully!
echo.
echo   Outputs in %~dp0dist\:
echo     1. EFL_NEXUS\                               (Application directory)
echo     2. EFL_NEXUS_Setup.exe                      (Full Install Wizard)
echo     3. EFL_NEXUS_v%VER%.zip                     (Full Release ZIP - fallback)
echo     4. EFL_Nexus_Patch_v%VER%_b%BUILD%.zip      (Initial patch - preferred by updater)
echo.
echo   Upload ZIPs #3 and #4 to the GitHub Release tag v%VER%.
echo.
echo   --- To deploy a HOTFIX later (no rebuild needed) ---
echo   1. Run create_patch.bat
echo   2. Upload the generated patch ZIP to the EXISTING GitHub Release
echo ========================================================
pause
