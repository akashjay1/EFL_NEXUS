@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo ========================================================
echo   EFL NEXUS - Directory Mode Application & Installer
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

echo [1/4] Building high-speed directory-mode EFL_NEXUS...
%PYI_CMD% EFL_NEXUS.spec --noconfirm --clean
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
%PYI_CMD% --specpath build\generated-specs updater.py --name=updater --noconsole --noconfirm --onefile --distpath=dist\EFL_NEXUS --icon=icon_2.ico --hidden-import=requests --add-data "icon_2.ico;." --add-data "icon.ico;."
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build the required updater.exe
    pause
    exit /b 1
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
%PY_CMD% build_release.py verify --directory dist\EFL_NEXUS
if errorlevel 1 (
    echo [ERROR] Distribution verification failed. Packaging stopped.
    pause
    exit /b 1
)

echo [3/4] Building EFL_NEXUS_Setup.exe (Install Wizard)...
%PYI_CMD% --specpath build\generated-specs installer_wizard.py --name=EFL_NEXUS_Setup --noconsole --noconfirm --onefile --icon=icon_2.ico --collect-all=PIL --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageTk --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --add-data "dist/EFL_NEXUS;payload"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to build EFL_NEXUS_Setup.exe
    pause
    exit /b %errorlevel%
)

echo.
echo [4/4] Creating GitHub Release ZIP package from directory build...
%PY_CMD% build_release.py full-zip --directory dist\EFL_NEXUS --output "dist\EFL_NEXUS_v%VER%.zip"
if errorlevel 1 (
    echo [ERROR] Full release ZIP generation failed.
    pause
    exit /b 1
)

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
