@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ========================================================
echo   EFL NEXUS (C# .NET 9) - Release Build and Package
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
    echo [ERROR] version.txt not found!
    pause
    exit /b 1
)

set "VER="
for /f "usebackq tokens=* delims=" %%V in ("version.txt") do set VER=%%V
if /i "!VER:~0,10!"=="EFL_NEXUS_" set "VER=!VER:~10!"
if /i "!VER:~0,1!"=="v" set "VER=!VER:~1!"

set BUILD=0
if exist "build.txt" (
    for /f "usebackq tokens=* delims=" %%B in ("build.txt") do set BUILD=%%B
)

echo   Target Version: !VER!   Build: !BUILD!
echo.

:: Run Python build release tool
python "%~dp0build_release.py" build %*
if errorlevel 1 (
    echo.
    echo [ERROR] Release build failed.
    pause
    exit /b %errorlevel%
)

echo.
echo ========================================================
echo   Build and Packaging Completed Successfully!
echo.
echo   Outputs in %~dp0dist\:
echo     1. EFL_NEXUS\                 (Fast Application Directory)
echo     2. EFL_NEXUS_v!VER!.zip   (Full Release Archive for GitHub)
echo ========================================================
echo.
pause
