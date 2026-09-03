@echo off
setlocal enabledelayedexpansion
echo ========================================================
echo   EFL NEXUS - Fast Differential Patch Generator
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
    echo [ERROR] version.txt not found in current directory!
    pause
    exit /b 1
)
for /f "usebackq tokens=* delims=" %%V in ("version.txt") do set VER=%%V
set BUILD=0
if exist "build.txt" (
    for /f "usebackq tokens=* delims=" %%B in ("build.txt") do set BUILD=%%B
)
echo Current Version : %VER%
echo Current Build   : %BUILD%
echo.

:: Determine target build number (from argument or prompt)
if not "%~1"=="" (
    set TARGET_BUILD=%~1
) else (
    set /a NEXT_BUILD=%BUILD%+1
    set /p TARGET_BUILD="Enter build number for this patch [default: !NEXT_BUILD!]: "
    if "!TARGET_BUILD!"=="" set TARGET_BUILD=!NEXT_BUILD!
)

echo !TARGET_BUILD!> "build.txt"
echo.
echo ========================================================
echo Building Patch for EFL_NEXUS v%VER% (Build !TARGET_BUILD!)
echo ========================================================
echo.

:: Step 1: Compile directory build
echo [1/3] Compiling directory-mode EFL_NEXUS with PyInstaller...
%PYI_CMD% main_app.py --name=EFL_NEXUS --noconsole --noconfirm --onedir --icon=icon_2.ico --collect-all=selenium --collect-all=webdriver_manager --collect-all=PIL --collect-all=openpyxl --collect-all=customtkinter --collect-all=gspread --collect-all=oauth2client --hidden-import=pandas --hidden-import=openpyxl --hidden-import=openpyxl.styles --hidden-import=requests --hidden-import=dotenv --hidden-import=korber_tool --hidden-import=reconciliation_tool --hidden-import=korber_login_bot --hidden-import=outlook_email_gui --hidden-import=efldatamanager --hidden-import=gspread --hidden-import=oauth2client --hidden-import=oauth2client.service_account --hidden-import=updater --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --hidden-import=win32api --hidden-import=winreg --hidden-import=customtkinter --hidden-import=queue --hidden-import=hashlib --hidden-import=calendar --add-data "version.txt;." --add-data "build.txt;." --add-data "icon_2.ico;." --add-data "icon.ico;." --add-data "aurora_bg.png;." --add-data "credentials.json;." --add-data "efl_users.json;." --add-data "sent_log.xlsx;." --add-data "templates.xlsx;." --add-data "variance_templates.xlsx;." --add-data "assets;assets"
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller compilation failed!
    pause
    exit /b %errorlevel%
)

:: Step 2: Sync latest assets, templates and data files
echo.
echo [2/3] Syncing latest assets and templates into dist\EFL_NEXUS...
for %%F in (templates.xlsx variance_templates.xlsx sent_log.xlsx version.txt build.txt icon_2.ico icon.ico aurora_bg.png credentials.json efl_users.json) do (
    if exist "%%F" copy /y "%%F" "dist\EFL_NEXUS\" >nul
)
if exist "dist\EFL_NEXUS\config.json" del /f /q "dist\EFL_NEXUS\config.json"

:: Step 3: Run differential patch generator
echo.
echo [3/3] Generating differential patch ZIP...
%PY_CMD% create_patch.py --new-dir dist\EFL_NEXUS --auto-find-prev dist\ --version %VER% --build !TARGET_BUILD! --output-dir dist

if %errorlevel% equ 0 (
    echo.
    echo ========================================================
    echo   Patch generated successfully!
    echo   Output: dist\EFL_Nexus_Patch_v%VER%_b!TARGET_BUILD!.zip
    echo.
    echo   Deploy to GitHub:
    echo   1. Open: https://github.com/akashjay1/EFL_NEXUS/releases/tag/v%VER%
    echo   2. Click "Edit release" and attach:
    echo      dist\EFL_Nexus_Patch_v%VER%_b!TARGET_BUILD!.zip
    echo   3. Save. Users will automatically receive the hotfix!
    echo ========================================================
) else (
    echo.
    echo [ERROR] Patch generation failed.
)

pause
