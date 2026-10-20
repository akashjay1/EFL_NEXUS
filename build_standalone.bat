@echo off
setlocal EnableDelayedExpansion
echo ========================================================
echo   EFL NEXUS - Directory Mode Application & Installer
echo ========================================================
echo.

:: Pin the EFL NEXUS bundle to Python 3.11.  AuditShip carries a separate
:: Python 3.14/Tcl runtime; using a floating uv environment can mix that
:: runtime into EFL NEXUS's PyInstaller payload and prevent EFL from starting.
set "PY_CMD=py -3.11"
set "PYI_CMD=py -3.11 -m PyInstaller"

:: Verify Python 3.11 is operational
%PY_CMD% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>nul
if %errorlevel% neq 0 (
    python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>nul
    if !errorlevel! equ 0 (
        set "PY_CMD=python"
        set "PYI_CMD=pyinstaller"
    ) else (
        echo [ERROR] Python 3.11 is required but was not found!
        echo         Please ensure Python 3.11 is installed.
        pause
        exit /b 1
    )
)
echo   [Environment] Using Python 3.11 (!PY_CMD!)

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

echo Preparing the portable GRN OCR runtime...
%PY_CMD% prepare_grn_ocr.py
if %errorlevel% neq 0 (
    echo [ERROR] Could not prepare the GRN OCR runtime.
    exit /b 1
)

echo [1/4] Building high-speed directory-mode EFL_NEXUS...
%PYI_CMD% EFL_NEXUS.spec --noconfirm
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build EFL_NEXUS
    pause
    exit /b %errorlevel%
)

echo.
echo Copying Korber AuditShip runtime into the application package...
robocopy "Korber_AuditShip" "dist\EFL_NEXUS\Korber_AuditShip" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS
if errorlevel 8 (
    echo [ERROR] Failed to package the Korber AuditShip runtime.
    pause
    exit /b 1
)

echo.
echo [2/4] Building companion updater.exe into dist\EFL_NEXUS...
%PYI_CMD% updater.py --name=updater --noconsole --noconfirm --onefile --distpath=dist\EFL_NEXUS --icon=icon_2.ico --hidden-import=requests --add-data "icon_2.ico;." --add-data "icon.ico;."
if %errorlevel% neq 0 (
    echo [WARNING] Failed to build updater.exe (skipping)
)

echo.
echo Deploying default templates, credentials and assets to dist\EFL_NEXUS...
for %%F in (templates.xlsx variance_templates.xlsx version.txt build.txt icon_2.ico icon.ico aurora_bg.png credentials.json efl_users.json) do (
    if exist "%%F" copy /y "%%F" "dist\EFL_NEXUS\" >nul
)
> "dist\EFL_NEXUS\version.txt" echo(!VER!
> "dist\EFL_NEXUS\build.txt" echo(!BUILD!

:: Ensure user runtime files and developer state are never packaged into releases
if exist "dist\EFL_NEXUS\config.json" del /f /q "dist\EFL_NEXUS\config.json"
if exist "dist\EFL_NEXUS\sent_log.xlsx" del /f /q "dist\EFL_NEXUS\sent_log.xlsx"
if exist "dist\EFL_NEXUS\reconciliation_queue.json" del /f /q "dist\EFL_NEXUS\reconciliation_queue.json"
if exist "dist\EFL_NEXUS\updater.log" del /f /q "dist\EFL_NEXUS\updater.log"
if exist "dist\EFL_NEXUS\.efl_records_cache.json" del /f /q "dist\EFL_NEXUS\.efl_records_cache.json"
if exist "dist\EFL_NEXUS\.load_reconciliation_tool_settings.json" del /f /q "dist\EFL_NEXUS\.load_reconciliation_tool_settings.json"

echo.
echo [3/4] Building EFL_NEXUS_Setup.exe (Install Wizard)...
%PYI_CMD% installer_wizard.py --name=EFL_NEXUS_Setup --noconsole --noconfirm --onefile --icon=icon_2.ico --collect-all=PIL --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageTk --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --add-data "dist/EFL_NEXUS;payload"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build EFL_NEXUS_Setup.exe
    pause
    exit /b %errorlevel%
)

echo.
echo [4/4] Creating GitHub Release ZIP package from directory build...
%PY_CMD% -c "import zipfile, os, pathlib; ver = open('dist/EFL_NEXUS/version.txt').read().strip(); zpath = f'dist/EFL_NEXUS_v{ver}.zip'; src_dir = pathlib.Path('dist/EFL_NEXUS'); z = zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9); [z.write(f, f.relative_to(src_dir)) for f in src_dir.rglob('*') if f.is_file() and not f.name.endswith('.old')]; z.close(); print('Created release zip:', zpath, f'{os.path.getsize(zpath)/1024/1024:.2f} MB')"

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
