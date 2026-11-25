@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ========================================================
echo   EFL NEXUS (C# .NET 9) - Differential Patch Generator
echo ========================================================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Check for dotnet SDK
dotnet --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .NET SDK is not installed or not in PATH.
    pause
    exit /b 1
)

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

python -c "import os,sys; value=os.environ['TARGET_BUILD']; previous=os.environ['BUILD']; sys.exit(0 if value.isascii() and value.isdigit() and int(value)>int(previous) else 1)"
if errorlevel 1 (
    echo [ERROR] Patch build number must be a whole number greater than !BUILD!.
    pause
    exit /b 1
)
> "build.txt" echo(!TARGET_BUILD!

echo.
echo ========================================================
echo   Building Patch for EFL_NEXUS v%VER% (Build !TARGET_BUILD!)
echo ========================================================
echo.

:: Step 1: Re-stage the compiled release directory with new build number
echo [1/2] Compiling and staging distribution directory...
python "%~dp0build_release.py" build --version %VER% --build !TARGET_BUILD! --output "dist\EFL_NEXUS_v%VER%.zip"
if errorlevel 1 (
    echo [ERROR] Build and staging failed!
    pause
    exit /b %errorlevel%
)

:: Step 2: Generate differential patch against baseline
echo.
echo [2/2] Generating differential patch ZIP...
python "%~dp0create_patch.py" --new-dir dist\EFL_NEXUS --auto-find-prev dist\ --version %VER% --build !TARGET_BUILD! --output-dir dist

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
