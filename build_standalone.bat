@echo off
echo ========================================================
echo   EFL NEXUS - Directory Mode Application & Installer
echo ========================================================
echo.

:: Read current version and build number
for /f "usebackq tokens=* delims=" %%V in ("version.txt") do set VER=%%V
for /f "usebackq tokens=* delims=" %%B in ("build.txt") do set BUILD=%%B
if not defined BUILD set BUILD=0
echo   Version: %VER%  Build: %BUILD%
echo.

echo [1/4] Building high-speed directory-mode EFL_NEXUS...
pyinstaller main_app.py --name=EFL_NEXUS --noconsole --noconfirm --onedir --icon=icon_2.ico --collect-all=selenium --collect-all=webdriver_manager --collect-all=PIL --collect-all=openpyxl --collect-all=customtkinter --collect-all=gspread --collect-all=oauth2client --collect-all=google_genai --hidden-import=pandas --hidden-import=openpyxl --hidden-import=openpyxl.styles --hidden-import=requests --hidden-import=dotenv --hidden-import=korber_tool --hidden-import=reconciliation_tool --hidden-import=korber_login_bot --hidden-import=outlook_email_gui --hidden-import=efldatamanager --hidden-import=gspread --hidden-import=oauth2client --hidden-import=oauth2client.service_account --hidden-import=updater --hidden-import=win32com --hidden-import=win32com.client --hidden-import=pythoncom --hidden-import=win32api --hidden-import=winreg --hidden-import=customtkinter --hidden-import=queue --hidden-import=hashlib --hidden-import=calendar --hidden-import=google --hidden-import=google.genai --add-data "version.txt;." --add-data "icon_2.ico;." --add-data "icon.ico;." --add-data "aurora_bg.png;." --add-data "credentials.json;." --add-data "efl_users.json;." --add-data "sent_log.xlsx;." --add-data "assets;assets"
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
for %%F in (templates.xlsx variance_templates.xlsx sent_log.xlsx version.txt build.txt icon_2.ico icon.ico aurora_bg.png credentials.json efl_users.json) do (
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
echo [5/5] Generating initial patch ZIP (build %BUILD%)...
python create_patch.py --new-dir dist\EFL_NEXUS --auto-find-prev dist\ --version %VER% --build %BUILD% --output-dir dist
if %errorlevel% equ 0 (
    echo   [OK] Patch ZIP: dist\EFL_Nexus_Patch_v%VER%_b%BUILD%.zip
) else (
    echo   [INFO] No patch generated (first release or no previous ZIP in dist\).
    echo         For a hotfix, run: python create_patch.py --new-dir dist\EFL_NEXUS --auto-find-prev dist\ --build ^<N^>
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
echo   1. Make your changes, increment build.txt
echo   2. python create_patch.py --new-dir dist\EFL_NEXUS --auto-find-prev dist\ --build ^<N^>
echo   3. Upload EFL_Nexus_Patch_v%VER%_b^<N^>.zip to the EXISTING GitHub Release
echo ========================================================
pause
