"""Extract and inspect the application module embedded in this PyInstaller bundle.

Run this script with the same Python minor version used to build the executable.
For the current bundle that is CPython 3.14.
"""

from __future__ import annotations

import argparse
import contextlib
import dis
import hashlib
import importlib.util
import io
import json
import marshal
import os
import re
import shutil
import struct
import subprocess
import sys
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter


ENTRY_MODULE = "FINAL_CODE2_DEFAULT_KAWSHI"


def bundle_python_version(reader: CArchiveReader) -> tuple[int, int]:
    """Read the Python version integer from the PyInstaller cookie."""
    with open(reader._filename, "rb") as stream:
        cookie_offset = reader._find_magic_pattern(stream, reader._COOKIE_MAGIC_PATTERN)
        if cookie_offset < 0:
            raise RuntimeError("Could not locate the PyInstaller cookie")
        stream.seek(cookie_offset)
        cookie = stream.read(reader._COOKIE_LENGTH)

    _, _, _, _, packed_version, _ = struct.unpack(reader._COOKIE_FORMAT, cookie)
    return packed_version // 100, packed_version % 100


def interpreter_version(executable: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [
                executable,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        major, minor = result.stdout.strip().split(".", 1)
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def find_matching_interpreter(required: tuple[int, int]) -> str | None:
    """Find a compatible interpreter, including uv installs listed by py.exe."""
    major, minor = required
    env_name = f"PYTHON_{major}_{minor}"
    candidates: list[str] = []

    if os.environ.get(env_name):
        candidates.append(os.environ[env_name])

    for command in (f"python{major}.{minor}", f"python{major}{minor}"):
        found = shutil.which(command)
        if found:
            candidates.append(found)

    launcher = shutil.which("py")
    if launcher:
        try:
            listing = subprocess.run(
                [launcher, "-0p"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            for line in listing.splitlines():
                if f"{major}.{minor}" not in line:
                    continue
                match = re.search(r"([A-Za-z]:\\.*?python(?:\.exe)?)\s*$", line)
                if match:
                    candidates.append(match.group(1))
        except (OSError, subprocess.SubprocessError):
            pass

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if interpreter_version(candidate) == required:
            return candidate
    return None


def ensure_compatible_interpreter(reader: CArchiveReader) -> None:
    """Relaunch under the bytecode version; dis cannot cross Python minors."""
    required = bundle_python_version(reader)
    running = sys.version_info[:2]
    if running == required:
        return

    replacement = find_matching_interpreter(required)
    required_text = f"{required[0]}.{required[1]}"
    running_text = f"{running[0]}.{running[1]}"
    if replacement is None:
        env_name = f"PYTHON_{required[0]}_{required[1]}"
        raise SystemExit(
            f"This bundle contains Python {required_text} bytecode, but the extractor "
            f"is running on Python {running_text}. Install Python {required_text}, or set "
            f"{env_name} to the full path of a compatible python.exe, then run again."
        )

    print(
        f"Bundle uses Python {required_text}; relaunching with {replacement}",
        flush=True,
    )
    completed = subprocess.run([replacement, str(Path(__file__).resolve()), *sys.argv[1:]])
    raise SystemExit(completed.returncode)


def launch_application_gui(executable: Path) -> None:
    """Start the GUI through the original PyInstaller execution environment."""
    internal = executable.parent / "_internal"
    if not internal.is_dir():
        raise FileNotFoundError(
            f"Required PyInstaller dependency directory was not found: {internal}"
        )

    print(f"Launching application GUI: {executable.resolve()}", flush=True)
    if sys.platform == "win32":
        # ShellExecute matches an Explorer double-click and avoids attaching the
        # GUI bootloader to the extractor's console process.
        os.startfile(str(executable.resolve()))
    else:
        subprocess.Popen([str(executable.resolve())], cwd=str(executable.resolve().parent))


def walk_code(root: types.CodeType):
    queue = [("<module>", root)]
    while queue:
        parent, code = queue.pop(0)
        path = code.co_name if parent == "<module>" else f"{parent}.{code.co_name}"
        yield path, code
        for value in code.co_consts:
            if isinstance(value, types.CodeType):
                queue.append((path, value))


def remove_embedded_header_image(code: types.CodeType) -> tuple[types.CodeType, int]:
    """Replace the embedded PNG banner constant while preserving all bytecode."""
    replacements = 0
    constants = []
    for value in code.co_consts:
        if (
            isinstance(value, str)
            and len(value) > 10_000
            and value.lstrip().startswith("iVBORw0KGgo")
        ):
            constants.append("")
            replacements += 1
        else:
            constants.append(value)
    if not replacements:
        return code, 0
    return code.replace(co_consts=tuple(constants)), replacements


def modernize_ui_constants(
    code: types.CodeType, *, module_root: bool = True
) -> tuple[types.CodeType, int]:
    """Refresh the legacy CustomTkinter theme without changing application logic."""
    text_and_color_map = {
        "Gate Pass Summary System": "KORBER AuditShip",
        "Körber Operations Console": "KORBER AuditShip",
        "Summary System": "KÖRBER",
        "Gate Pass Viewer": "Operations Console",
        "Korber Load Audit & Shipping BOT": "KORBER AuditShip",
        "Gate Pass Operations": "KORBER AuditShip",
        "Upload Excel -> Open Browser -> BOT STOP can stop the running browser/process": (
            "Upload data, connect to Körber, then run your workflow."
        ),
        "✔ Click to Copy\n✔ Open Browser\n✔ No Duplicates\n✔ Stable Zoom View": (
            "QUICK TIP\nDouble-click any table cell to copy its value."
        ),
        "BOT STOP": "Stop Automation",
        "Aligned Data Table": "Gate Pass Data",
        "No file loaded": "No spreadsheet loaded",
        "Excel / View": "DATA",
        "Browser": "BROWSER",
        "Process": "WORKFLOWS",
        "Upload Excel": "Upload Spreadsheet",
        "Clear View": "Clear Workspace",
        "Open Browser": "Open Körber",
        "Close Browser": "Close Browser",
        "Load Audit": "Run Load Audit",
        "Shipped": "Process Shipping",
        "Designed with CustomTkinter": "Secure operations workspace",
        "Summary Overview": "Operational Summary",
        "Prev": "Previous",
        "Row no": "Go to row",
        "#f4f7fb": "#F3F6FA",
        "#1e293b": "#101828",
        "#334155": "#1D2939",
        "#cbd5e1": "#98A2B3",
        "#e2e8f0": "#D0D5DD",
        "#0f172a": "#101828",
        "#475569": "#667085",
        "#f8fafc": "#F9FAFB",
        "#eef4ff": "#EFF4FF",
        "#e0ecff": "#EFF4FF",
        "#7c3aed": "#7F56D9",
        "#dbeafe": "#EAF2FF",
        "#64748b": "#475467",
        "#3b82f6": "#2563EB",
        "#0ea5e9": "#2563EB",
        "#0284c7": "#1D4ED8",
        "#22c55e": "#039855",
        "#16a34a": "#039855",
        "#15803d": "#027A48",
        "#ef4444": "#D92D20",
        "#dc2626": "#D92D20",
        "#b91c1c": "#B42318",
        "#991b1b": "#B42318",
        "#7f1d1d": "#912018",
        "#f59e0b": "#DC6803",
        "#d97706": "#B54708",
        "#8b5cf6": "#475467",
        "#94a3b8": "#667085",
        "#111827": "#101828",
    }

    ui_builders = {
        "create_stats_card",
        "create_clickable_cell",
        "create_sidebar_section",
        "create_sidebar_button",
        "build_ui",
    }
    eligible = module_root or code.co_name in ui_builders
    replacements = 0
    updated_constants = []
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            updated, count = modernize_ui_constants(value, module_root=False)
            updated_constants.append(updated)
            replacements += count
        elif eligible and isinstance(value, str) and value in text_and_color_map:
            updated_constants.append(text_and_color_map[value])
            replacements += 1
        elif (
            eligible
            and isinstance(value, tuple)
            and value
            and value[0] == "Arial"
            and len(value) in {2, 3}
        ):
            updated_constants.append(("Segoe UI", *value[1:]))
            replacements += 1
        else:
            updated_constants.append(value)

    return code.replace(co_consts=tuple(updated_constants)), replacements


def remove_table_row_limit(code: types.CodeType) -> tuple[types.CodeType, int]:
    """Use a 10-row viewport and enable virtual scrolling for additional rows."""
    replacements = 0
    bytecode = bytearray(code.co_code)
    instructions = list(dis.get_instructions(code, show_caches=True, adaptive=False))

    if code.co_name == "<module>":
        for position, instruction in enumerate(instructions[:-1]):
            following = instructions[position + 1]
            if (
                instruction.opname == "LOAD_SMALL_INT"
                and following.opname == "STORE_NAME"
                and following.argval == "VISIBLE_TABLE_ROWS"
            ):
                bytecode[instruction.offset + 1] = 10
                replacements += 1
                break

    if code.co_qualname == "FastTreeAlignedTable.__init__":
        for instruction in instructions:
            if instruction.opname == "LOAD_SMALL_INT" and instruction.argval == 80:
                bytecode[instruction.offset + 1] = 10
                replacements += 1
                break

    updated_constants = []
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            updated, count = remove_table_row_limit(value)
            updated_constants.append(updated)
            replacements += count
        else:
            updated_constants.append(value)

    if replacements:
        code = code.replace(
            co_code=bytes(bytecode), co_consts=tuple(updated_constants)
        )
    return code, replacements


def repack_executable(
    executable: Path,
    reader: CArchiveReader,
    entry_code: types.CodeType,
) -> Path:
    """Rebuild the appended CArchive with a replacement entry-point module."""
    executable = executable.resolve()
    backup = executable.with_name(f"{executable.stem}.with-header-image{executable.suffix}")
    package_tmp = executable.with_name(f".{executable.name}.pkg.tmp")
    executable_tmp = executable.with_name(f".{executable.name}.tmp")

    if not backup.exists():
        shutil.copy2(executable, backup)

    with executable.open("rb") as stream:
        stream.seek(reader._end_offset - reader._COOKIE_LENGTH)
        cookie = stream.read(reader._COOKIE_LENGTH)
        magic, _, _, _, pyvers, pylib_name = struct.unpack(
            reader._COOKIE_FORMAT, cookie
        )
        if magic != reader._COOKIE_MAGIC_PATTERN:
            raise RuntimeError("PyInstaller CArchive cookie could not be verified")

    archive_writer = object.__new__(CArchiveWriter)
    archive_writer._collected_names = set()
    toc = []
    try:
        with package_tmp.open("wb") as package:
            for name, (_, _, _, compressed, typecode) in reader.toc.items():
                data = (
                    marshal.dumps(entry_code)
                    if name == ENTRY_MODULE
                    else reader.extract(name)
                )
                toc.append(
                    archive_writer._write_blob(
                        package,
                        data,
                        name,
                        typecode,
                        compress=bool(compressed),
                    )
                )
            for option in reader.options:
                toc.append(archive_writer._write_blob(package, b"", option, "o"))

            toc_offset = package.tell()
            toc_data = CArchiveWriter._serialize_toc(toc)
            package.write(toc_data)
            archive_length = toc_offset + len(toc_data) + reader._COOKIE_LENGTH
            package.write(
                struct.pack(
                    reader._COOKIE_FORMAT,
                    reader._COOKIE_MAGIC_PATTERN,
                    archive_length,
                    toc_offset,
                    len(toc_data),
                    pyvers,
                    pylib_name,
                )
            )

        with executable.open("rb") as source, executable_tmp.open("wb") as target:
            target.write(source.read(reader._start_offset))
            with package_tmp.open("rb") as package:
                shutil.copyfileobj(package, target)
        os.replace(executable_tmp, executable)
    finally:
        package_tmp.unlink(missing_ok=True)
        executable_tmp.unlink(missing_ok=True)
    return backup


def safe_constant(value):
    if isinstance(value, types.CodeType):
        return {"code_object": value.co_name, "first_line": value.co_firstlineno}
    rendered = repr(value)
    if len(rendered) > 500:
        return {"preview": rendered[:500], "rendered_length": len(rendered)}
    return rendered


def build_manifest(executable: Path, reader: CArchiveReader, code: types.CodeType):
    functions = []
    for path, item in walk_code(code):
        functions.append(
            {
                "path": path,
                "name": item.co_name,
                "qualified_name": item.co_qualname,
                "source_file": item.co_filename,
                "first_line": item.co_firstlineno,
                "positional_args": list(item.co_varnames[: item.co_argcount]),
                "keyword_only_args": list(
                    item.co_varnames[
                        item.co_argcount : item.co_argcount + item.co_kwonlyargcount
                    ]
                ),
                "locals": list(item.co_varnames),
                "globals_and_attributes": list(item.co_names),
                "bytecode_bytes": len(item.co_code),
                "constants": [safe_constant(value) for value in item.co_consts],
            }
        )

    archive_entries = []
    for name, entry in reader.toc.items():
        offset, stored_size, original_size, compressed, typecode = entry
        archive_entries.append(
            {
                "name": name,
                "offset": offset,
                "stored_size": stored_size,
                "original_size": original_size,
                "compressed": bool(compressed),
                "typecode": typecode,
            }
        )

    return {
        "input": str(executable.resolve()),
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "python_running_extractor": sys.version,
        "entry_module": ENTRY_MODULE,
        "embedded_source_filename": code.co_filename,
        "archive_entries": archive_entries,
        "code_objects": functions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", nargs="?", default="KORBER AuditShip.exe")
    parser.add_argument("--output", default="reverse_engineered")
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="recover the artifacts without opening the application GUI",
    )
    parser.add_argument(
        "--remove-header-image",
        action="store_true",
        help="remove the embedded header banner and keep a backup of the executable",
    )
    parser.add_argument(
        "--modernize-ui",
        action="store_true",
        help="apply the modern operations-console theme to the bundled GUI",
    )
    parser.add_argument(
        "--show-all-rows",
        action="store_true",
        help="show 10 rows at a time and scroll through the complete spreadsheet",
    )
    args = parser.parse_args()

    executable = Path(args.executable)
    output = Path(args.output)

    reader = CArchiveReader(str(executable))
    ensure_compatible_interpreter(reader)
    output.mkdir(parents=True, exist_ok=True)
    marshalled = reader.extract(ENTRY_MODULE)
    code = marshal.loads(marshalled)
    if not isinstance(code, types.CodeType):
        raise TypeError("Embedded entry is not a Python code object")

    # A timestamp-based .pyc header is 16 bytes: magic, flags, mtime, source size.
    pyc_header = importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, 0, 0)
    (output / f"{ENTRY_MODULE}.pyc").write_bytes(pyc_header + marshalled)
    (output / f"{ENTRY_MODULE}.marshal").write_bytes(marshalled)

    disassembly = io.StringIO()
    with contextlib.redirect_stdout(disassembly):
        print(f"Python: {sys.version}")
        print(f"Embedded source name: {code.co_filename}")
        print(f"Entry module: {ENTRY_MODULE}\n")
        for path, item in walk_code(code):
            print("=" * 100)
            print(
                f"CODE OBJECT: {path} | source line {item.co_firstlineno} | "
                f"args={item.co_varnames[:item.co_argcount]}"
            )
            print("=" * 100)
            dis.dis(item, depth=0, show_caches=False, adaptive=False)
            print()
    (output / f"{ENTRY_MODULE}.dis.txt").write_text(
        disassembly.getvalue(), encoding="utf-8"
    )

    manifest = build_manifest(executable, reader, code)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Recovered {len(manifest['code_objects'])} code objects into {output.resolve()}")
    if args.remove_header_image:
        patched_code, replacements = remove_embedded_header_image(code)
        if not replacements:
            print("The embedded header image is already absent.")
        else:
            backup = repack_executable(executable, reader, patched_code)
            print(
                f"Removed {replacements} embedded header image; original saved as "
                f"{backup.name}"
            )
    if args.modernize_ui:
        modern_code, replacements = modernize_ui_constants(code)
        backup = executable.with_name(
            f"{executable.stem}.before-modern-ui{executable.suffix}"
        )
        if not backup.exists():
            shutil.copy2(executable, backup)
        repack_executable(executable, reader, modern_code)
        print(
            f"Applied {replacements} UI theme replacements; previous executable "
            f"saved as {backup.name}"
        )
    if args.show_all_rows:
        unlimited_code, replacements = remove_table_row_limit(code)
        if replacements != 2:
            raise RuntimeError("Could not locate both embedded table viewport limits")
        backup = executable.with_name(
            f"{executable.stem}.before-all-rows{executable.suffix}"
        )
        if not backup.exists():
            shutil.copy2(executable, backup)
        repack_executable(executable, reader, unlimited_code)
        print(
            "Enabled the 10-row virtual viewport and scrolling for all additional "
            f"rows. Previous executable saved as {backup.name}"
        )
    if not args.extract_only:
        launch_application_gui(executable.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
