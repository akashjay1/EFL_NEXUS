"""Shared checks and release packaging for the standalone and patch scripts."""

import argparse
import importlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import zipfile

from create_patch import _should_ignore_file

ROOT = Path(__file__).resolve().parent
REQUIRED_MODULES = ('grn_ocr', 'grn_cloud_ocr', 'grn_ocr_settings', 'whatsapp_media',
                    'whatsapp_grn', 'whatsapp_grn_inbox', 'whatsapp_monitor', 'reconciliation_tool')


def preflight():
    if sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise RuntimeError('Build NEXUS with 64-bit Python 3.12; keep AuditShip in its separate environment.')
    for name in ('PyInstaller', 'webview', 'pythonnet', 'clr_loader', 'PIL.ImageTk', 'pandas',
                 'openpyxl', 'requests', 'win32cred', 'cv2', 'numpy', 'zxingcpp', 'pefile', 'zstandard', *REQUIRED_MODULES):
        importlib.import_module(name)
    import cv2
    import zxingcpp
    if not callable(getattr(cv2, 'Canny', None)) or not callable(getattr(zxingcpp, 'read_barcodes', None)):
        raise RuntimeError('OpenCV or ZXing is incomplete. Reinstall requirements in the build environment.')
    import tkinter
    tkinter.Tcl().eval('info patchlevel')
    print('Build preflight passed: Python 3.12, native OCR, WhatsApp modules and Tk are available.')


def auditship_version(executable):
    from PyInstaller.archive.readers import CArchiveReader
    from patch_auditship_credentials import _raw_toc_entries
    if not executable.is_file():
        raise RuntimeError(f'AuditShip executable not found: {executable}')
    _, _, version, _ = _raw_toc_entries(executable, CArchiveReader(str(executable)))
    return divmod(version, 100)


def interpreter_version(executable):
    try:
        result = subprocess.run([str(executable), '-c',
                                 'import sys; print(str(sys.version_info.major)+"."+str(sys.version_info.minor))'],
                                capture_output=True, text=True, check=True, timeout=15)
        return tuple(map(int, result.stdout.strip().split('.')))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def find_auditship_python(version):
    explicit = os.environ.get('AUDITSHIP_PYTHON')
    if explicit:
        if interpreter_version(explicit) != version:
            raise RuntimeError(f'AUDITSHIP_PYTHON must point to Python {version[0]}.{version[1]}.')
        return Path(explicit)
    # Include registered uv/Astral runtimes that the old py -3.x alias may miss.
    try:
        inventory = subprocess.run(['py', '-0p'], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('Set AUDITSHIP_PYTHON to the interpreter used to build AuditShip.') from exc
    for line in inventory.stdout.splitlines():
        match = re.search(r'([A-Za-z]:\\.*python(?:\.exe)?)\s*$', line, re.IGNORECASE)
        if match and interpreter_version(match[1]) == version:
            return Path(match[1])
    raise RuntimeError(f'Install Python {version[0]}.{version[1]} for AuditShip or set AUDITSHIP_PYTHON to its python.exe.')


def patch_auditship():
    executable = ROOT / 'Korber_AuditShip' / 'KORBER AuditShip.exe'
    version = auditship_version(executable)
    if not (executable.parent / '_internal' / f'python{version[0]}{version[1]}.dll').is_file():
        raise RuntimeError('AuditShip runtime folder is incomplete.')
    base_python = find_auditship_python(version)
    environment = ROOT / 'build' / f'auditship-build-python{version[0]}{version[1]}'
    python = environment / 'Scripts' / 'python.exe'
    if not python.exists():
        subprocess.run([str(base_python), '-m', 'venv', str(environment)], check=True)
    if interpreter_version(python) != version:
        raise RuntimeError(f'AuditShip environment uses the wrong interpreter: {environment}')
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', 'pyinstaller>=6.0.0'], check=True)
    subprocess.run([str(python), str(ROOT / 'patch_auditship_credentials.py'), str(executable)], check=True)


def release_files(directory):
    directory = directory.resolve()
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(directory):
            raise RuntimeError(f'Release file resolves outside the distribution: {path}')
        relative = path.relative_to(directory).as_posix()
        if relative == 'build.txt' or not _should_ignore_file(relative):
            yield relative, path


def sanitize_distribution(directory):
    """Remove runtime state from generated staging files before building installers."""
    directory = directory.resolve()
    if not directory.is_dir():
        raise RuntimeError(f'Distribution directory does not exist: {directory}')
    for path in directory.rglob('*'):
        if path.is_file():
            if not path.resolve().is_relative_to(directory):
                raise RuntimeError(f'Refusing to modify a file outside the distribution: {path}')
            relative = path.relative_to(directory).as_posix()
            if relative != 'build.txt' and _should_ignore_file(relative):
                path.unlink()


def verify_ocr_runtime(runtime):
    runtime = runtime.resolve()
    manifest = json.loads((runtime / 'manifest.json').read_text(encoding='utf-8'))
    from create_patch import _sha256
    for name, expected in manifest['files'].items():
        path = (runtime / name).resolve()
        if not path.is_relative_to(runtime) or not path.is_file() or _sha256(path) != expected:
            raise RuntimeError(f'Packaged OCR runtime checksum mismatch: {name}')
    if _sha256(runtime / 'tessdata' / 'eng.traineddata') != manifest['model_sha256']:
        raise RuntimeError('Packaged English OCR model checksum mismatch.')
    subprocess.run([str(runtime / 'tesseract.exe'), '--version'], check=True, capture_output=True, timeout=15,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)


def verify_distribution(directory):
    directory = directory.resolve()
    required = ('EFL_NEXUS.exe', 'updater.exe', 'version.txt', 'build.txt', '_internal/python312.dll',
                '_internal/assets/grn_ocr/tesseract.exe', '_internal/assets/grn_ocr/tessdata/eng.traineddata',
                '_internal/assets/grn_ocr/manifest.json', 'Korber_AuditShip/KORBER AuditShip.exe')
    for relative in required:
        if not (directory / relative).is_file():
            raise RuntimeError(f'Distribution is missing {relative}')
    internal = directory / '_internal'
    if not list(internal.rglob('*zxing*.pyd')) or not list(internal.rglob('cv2*.pyd')):
        raise RuntimeError('Distribution is missing the native ZXing or OpenCV extension.')
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(directory / 'EFL_NEXUS.exe'))
    pyz = archive.open_embedded_archive('PYZ.pyz')
    missing = [name for name in REQUIRED_MODULES if name not in pyz.toc]
    if missing:
        raise RuntimeError('Frozen application is missing modules: ' + ', '.join(missing))
    verify_ocr_runtime(internal / 'assets' / 'grn_ocr')
    sanitize_distribution(directory)
    print('Distribution verified: GRN/OCR modules, native runtime, updater and release metadata are present.')


def full_release_zip(directory, output):
    if output.resolve().is_relative_to(directory.resolve()):
        raise RuntimeError('Write the release ZIP outside the distribution directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    files = list(release_files(directory))
    if not files:
        raise RuntimeError('Refusing to create an empty release archive.')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, path in files:
            archive.write(path, relative)
    print(f'Created full release ZIP: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight', 'patch-auditship', 'verify', 'full-zip', 'inspect-auditship'))
    parser.add_argument('--directory', type=Path, default=ROOT / 'dist' / 'EFL_NEXUS')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'preflight':
            preflight()
        elif args.action == 'patch-auditship':
            patch_auditship()
        elif args.action == 'inspect-auditship':
            version = auditship_version(ROOT / 'Korber_AuditShip' / 'KORBER AuditShip.exe')
            print(f'AuditShip requires Python {version[0]}.{version[1]}: {find_auditship_python(version)}')
        elif args.action == 'verify':
            verify_distribution(args.directory)
        elif args.action == 'full-zip':
            if args.output is None:
                parser.error('--output is required for full-zip')
            full_release_zip(args.directory, args.output)
    except (RuntimeError, ImportError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'[ERROR] {exc}\n')


if __name__ == '__main__':
    main()
