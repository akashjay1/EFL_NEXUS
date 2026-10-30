@echo off
rem Shared setup, called inside each build script's SETLOCAL scope.
rem Python 3.12 supports the pinned ZXing wheel and stays separate from AuditShip.
if defined NEXUS_BUILD_PYTHON (
    if not exist "%NEXUS_BUILD_PYTHON%" (
        echo [ERROR] NEXUS_BUILD_PYTHON does not point to an existing python.exe.
        exit /b 1
    )
) else (
    set "NEXUS_BUILD_PYTHON=%~dp0build\nexus-build-python312\Scripts\python.exe"
)
if not exist "%NEXUS_BUILD_PYTHON%" (
    py -3.12 -m venv "%~dp0build\nexus-build-python312"
    if errorlevel 1 (
        echo [ERROR] Cannot create the Python 3.12 build environment.
        echo Install 64-bit Python 3.12 or set NEXUS_BUILD_PYTHON to its environment's python.exe.
        exit /b 1
    )
)
set "PYTHONPATH="
set "PYTHONHOME="
set "TCL_LIBRARY="
set "TK_LIBRARY="
set PY_CMD="%NEXUS_BUILD_PYTHON%"
set PYI_CMD="%NEXUS_BUILD_PYTHON%" -m PyInstaller
%PY_CMD% -c "import struct,sys; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo [ERROR] NEXUS_BUILD_PYTHON must be a working 64-bit Python 3.12 interpreter.
    exit /b 1
)
%PY_CMD% -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt
if errorlevel 1 exit /b 1
%PY_CMD% build_release.py preflight
if errorlevel 1 exit /b 1
%PY_CMD% build_release.py patch-auditship
if errorlevel 1 exit /b 1
%PY_CMD% prepare_grn_ocr.py
if errorlevel 1 exit /b 1
exit /b 0
