"""Add a credential bridge to the bundled, source-unavailable AuditShip app.

Run with the same Python minor version used to build AuditShip (currently 3.14).
The patch replaces only its entry-point script in the PyInstaller archive. Its
original script and all other archive entries remain unchanged.
"""

import argparse
import marshal
import os
import struct
import sys
import tempfile
import types
import zlib
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter


SCRIPT_NAME = "FINAL_CODE2_DEFAULT_KAWSHI"
BRIDGE_MARKER = "_AUDITSHIP_CREDENTIAL_BRIDGE_V2"
DEFAULT_EXE = Path(__file__).resolve().parent / "Korber_AuditShip" / "KORBER AuditShip.exe"
COOKIE_FORMAT = "!8sIIII64s"
TOC_FORMAT = "!IIIIBc"
TOC_HEADER_SIZE = struct.calcsize(TOC_FORMAT)


def _has_login_function(code):
    return any(
        isinstance(value, types.CodeType) and value.co_name == "fast_login_if_needed"
        and {"LOGIN_USERNAME", "LOGIN_PASSWORD"}.issubset(value.co_names)
        for value in code.co_consts
    )


def _extract_original_script(script_bytes):
    code = marshal.loads(script_bytes)
    if any(name.startswith("_AUDITSHIP_CREDENTIAL_BRIDGE") for name in code.co_names):
        for c in code.co_consts:
            if isinstance(c, bytes):
                try:
                    orig = marshal.loads(c)
                    if _has_login_function(orig):
                        return c
                except Exception:
                    pass
    return script_bytes


def _bridge_script(original_script):
    # The original entry point assigns static LOGIN_USERNAME/PASSWORD/FORK_ID values.
    # STORE_NAME writes through this mapping; replacing those assignments
    # also updates the real module globals used by fast_login_if_needed() and handle_fork_identifier_if_present().
    source = f'''
import json as _auditship_json
import marshal as _auditship_marshal
import os as _auditship_os
import sys as _auditship_sys
from pathlib import Path as _AuditShipPath

{BRIDGE_MARKER} = True
_auditship_config_path = _AuditShipPath(_auditship_sys.executable).resolve().parent.parent / "config.json"
try:
    with _auditship_config_path.open("r", encoding="utf-8") as _auditship_file:
        _auditship_settings = _auditship_json.load(_auditship_file)
except (OSError, ValueError):
    _auditship_settings = {{}}

_auditship_user = _auditship_os.environ.get("AUDITSHIP_USER") or _auditship_settings.get("auditship_user", "")
_auditship_password = _auditship_os.environ.get("AUDITSHIP_PASS") or _auditship_settings.get("auditship_pass", "")
_auditship_fork_id = _auditship_os.environ.get("AUDITSHIP_FORK_ID") or _auditship_settings.get("auditship_fork_id", "") or _auditship_user

if not _auditship_user or not _auditship_password or not _auditship_fork_id:
    from tkinter import messagebox as _auditship_messagebox
    _auditship_messagebox.showerror(
        "AuditShip credentials missing",
        "Enter the AuditShip username, password, and Fork ID in EFL NEXUS Settings before opening AuditShip."
    )
    raise SystemExit(1)

_auditship_globals = globals()
class _AuditShipNamespace(dict):
    def __setitem__(self, key, value):
        if key == "LOGIN_USERNAME":
            value = _auditship_user
        elif key == "LOGIN_PASSWORD":
            value = _auditship_password
        elif key == "FORK_ID":
            value = _auditship_fork_id
        super().__setitem__(key, value)
        _auditship_globals[key] = value

_auditship_original = _auditship_marshal.loads({original_script!r})
exec(_auditship_original, _auditship_globals, _AuditShipNamespace())
'''
    return marshal.dumps(compile(source, SCRIPT_NAME, "exec"))


def _raw_toc_entries(executable, reader):
    """Read entries in original order, including PyInstaller option entries."""
    with executable.open("rb") as source:
        source.seek(reader._start_offset)
        package = source.read(reader._end_offset - reader._start_offset)
    cookie_size = struct.calcsize(COOKIE_FORMAT)
    magic, archive_length, toc_offset, toc_length, pyvers, pylib = struct.unpack(
        COOKIE_FORMAT, package[-cookie_size:]
    )
    if archive_length != len(package) or magic != CArchiveReader._COOKIE_MAGIC_PATTERN:
        raise ValueError("Unexpected AuditShip archive format")
    toc_bytes = package[toc_offset:toc_offset + toc_length]
    position = 0
    entries = []
    while position < len(toc_bytes):
        length, offset, compressed_length, data_length, compressed, kind = struct.unpack_from(
            TOC_FORMAT, toc_bytes, position
        )
        name = toc_bytes[position + TOC_HEADER_SIZE:position + length].rstrip(b"\0").decode("utf-8")
        entries.append((name, offset, compressed_length, data_length, compressed, kind.decode("ascii")))
        position += length
    if position != len(toc_bytes):
        raise ValueError("Invalid AuditShip archive table")
    return package, entries, pyvers, pylib


def patch(executable):
    reader = CArchiveReader(str(executable))
    if SCRIPT_NAME not in reader.toc:
        raise ValueError("AuditShip entry point not found; this build is unsupported")
    script_bytes = reader.extract(SCRIPT_NAME)
    code = marshal.loads(script_bytes)
    if BRIDGE_MARKER in code.co_names:
        return False
    original_script = _extract_original_script(script_bytes)
    orig_code = marshal.loads(original_script)
    if not _has_login_function(orig_code):
        raise ValueError("AuditShip login structure changed; refusing to patch")

    package, entries, pyvers, pylib = _raw_toc_entries(executable, reader)
    if pyvers != sys.version_info.major * 100 + sys.version_info.minor:
        raise ValueError("Patch AuditShip with the Python version used to build it")
    replacement = _bridge_script(original_script)

    with tempfile.NamedTemporaryFile(dir=executable.parent, suffix=".exe", delete=False) as output:
        temporary = Path(output.name)
        try:
            with executable.open("rb") as source:
                output.write(source.read(reader._start_offset))
            archive_start = output.tell()
            new_toc = []
            for name, offset, compressed_length, data_length, compressed, kind in entries:
                payload = package[offset:offset + compressed_length]
                if name == SCRIPT_NAME:
                    data_length = len(replacement)
                    payload = zlib.compress(replacement, 9) if compressed else replacement
                new_offset = output.tell() - archive_start
                output.write(payload)
                new_toc.append((new_offset, len(payload), data_length, compressed, kind, name))

            new_toc_offset = output.tell() - archive_start
            new_toc_data = CArchiveWriter._serialize_toc(new_toc)
            output.write(new_toc_data)
            new_length = new_toc_offset + len(new_toc_data) + struct.calcsize(COOKIE_FORMAT)
            output.write(struct.pack(
                COOKIE_FORMAT, CArchiveReader._COOKIE_MAGIC_PATTERN,
                new_length, new_toc_offset, len(new_toc_data), pyvers, pylib,
            ))
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    try:
        check = CArchiveReader(str(temporary))
        if set(check.toc) != set(reader.toc) or check.options != reader.options:
            raise ValueError("Patched archive entries differ from the original")
        for name in reader.toc:
            if name != SCRIPT_NAME and check.extract(name) != reader.extract(name):
                raise ValueError(f"Archive entry changed unexpectedly: {name}")
        if BRIDGE_MARKER not in marshal.loads(check.extract(SCRIPT_NAME)).co_names:
            raise ValueError("Credential bridge missing from patched archive")
        os.replace(temporary, executable)
    finally:
        temporary.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", nargs="?", type=Path, default=DEFAULT_EXE)
    args = parser.parse_args()
    changed = patch(args.executable.resolve())
    print("AuditShip credential bridge installed" if changed else "AuditShip credential bridge already installed")
