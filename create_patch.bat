@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ========================================================
echo   EFL NEXUS - Fast Differential Patch Generator
echo ========================================================
echo.

:: Both release paths use the same isolated interpreter, dependencies and OCR preparation.
call "%~dp0prepare_build.bat"
if errorlevel 1 (
    echo [ERROR] Build preparation failed. No release package was created.
    pause
    exit /b 1
)
echo   [Environment] Using isolated Python 3.12: !PY_CMD!

:: Read current version and build number
if not exist "version.txt" (
    echo [ERROR] version.txt not found in current directory!
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
echo Current Version : %VER%
echo Current Build   : %BUILD%
echo.

:: Determine target build number (from argument or prompt)
set "TARGET_BUILD="
if not "%~1"=="" (
    set "TARGET_BUILD=%~1"
) else (
    set /a NEXT_BUILD=%BUILD%+1
    set /p TARGET_BUILD="Enter build number for this patch [default: !NEXT_BUILD!]: "
    if "!TARGET_BUILD!"=="" set TARGET_BUILD=!NEXT_BUILD!
)

%PY_CMD% -c "import os,sys; value=os.environ['TARGET_BUILD']; previous=os.environ['BUILD']; sys.exit(0 if value.isascii() and value.isdigit() and int(value)>int(previous) else 1)"
if errorlevel 1 (
    echo [ERROR] Patch build number must be a whole number greater than !BUILD!.
    pause
    exit /b 1
)
> "build.txt" echo(!TARGET_BUILD!
echo.
echo ========================================================
echo Building Patch for EFL_NEXUS v%VER% (Build !TARGET_BUILD!)
echo ========================================================
echo.

:: Step 1: Compile directory build
echo [1/4] Compiling directory-mode EFL_NEXUS with PyInstaller...
%PYI_CMD% EFL_NEXUS.spec --noconfirm --clean
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller compilation failed!
    pause
    exit /b %errorlevel%
)

:: Step 2: Build updater companion if needed
echo.
echo [2/4] Compiling companion updater.exe into dist\EFL_NEXUS...
%PYI_CMD% --specpath build\generated-specs updater.py --name=updater --noconsole --noconfirm --onefile --distpath=dist\EFL_NEXUS --icon=icon_2.ico --hidden-import=requests --add-data "icon_2.ico;." --add-data "icon.ico;."
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build the required updater.exe
    pause
    exit /b 1
)

:: Step 3: Sync latest assets, templates and AuditShip runtime
echo.
echo [3/4] Syncing latest assets and templates into dist\EFL_NEXUS...
for %%F in (templates.xlsx variance_templates.xlsx version.txt build.txt icon_2.ico icon.ico aurora_bg.png credentials.json efl_users.json) do (
    if exist "%%F" copy /y "%%F" "dist\EFL_NEXUS\" >nul
)
> "dist\EFL_NEXUS\version.txt" echo(!VER!
> "dist\EFL_NEXUS\build.txt" echo(!TARGET_BUILD!

:: Ensure user runtime files and developer state are never packaged into patches
if exist "dist\EFL_NEXUS\config.json" del /f /q "dist\EFL_NEXUS\config.json"
if exist "dist\EFL_NEXUS\sent_log.xlsx" del /f /q "dist\EFL_NEXUS\sent_log.xlsx"
if exist "dist\EFL_NEXUS\reconciliation_queue.json" del /f /q "dist\EFL_NEXUS\reconciliation_queue.json"
if exist "dist\EFL_NEXUS\updater.log" del /f /q "dist\EFL_NEXUS\updater.log"
if exist "dist\EFL_NEXUS\.efl_records_cache.json" del /f /q "dist\EFL_NEXUS\.efl_records_cache.json"
if exist "dist\EFL_NEXUS\.load_reconciliation_tool_settings.json" del /f /q "dist\EFL_NEXUS\.load_reconciliation_tool_settings.json"

robocopy "Korber_AuditShip" "dist\EFL_NEXUS\Korber_AuditShip" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS
if errorlevel 8 (
    echo [ERROR] Failed to include Korber AuditShip in the patch build.
    pause
    exit /b 1
)

%PY_CMD% build_release.py verify --directory dist\EFL_NEXUS
if errorlevel 1 (
    echo [ERROR] Distribution verification failed. Packaging stopped.
    pause
    exit /b 1
)

:: Step 4: Run differential patch generator
echo.
echo [4/4] Generating differential patch ZIP...
%PY_CMD% create_patch.py --new-dir dist\EFL_NEXUS --auto-find-prev dist\ --version %VER% --build !TARGET_BUILD! --output-dir dist

if %errorlevel% equ 0 (
    echo.
    echo ========================================================
    echo   Patch generated successfully!
    echo   Output: dist\EFL_Nexus_Patch_v%VER%_b!TARGET_BUILD!.zip
    echo.
    echo   Deploy to GitHub:
    echo   1. Open: https://github.com/akashjay1/EFL_NEXUS/releases/tag/v%VER%
    echo      (or: https://github.com/akashjay1/EFL_NEXUS/releases/tag/EFL_NEXUS_v%VER%)
    echo   2. Click "Edit release" and attach:
    echo      dist\EFL_Nexus_Patch_v%VER%_b!TARGET_BUILD!.zip
    echo   3. Save. Users will automatically receive the hotfix!
    echo ========================================================
) else (
    echo.
    echo [ERROR] Patch generation failed.
    pause
    exit /b 1
)

pause
