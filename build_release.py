"""
build_release.py -- EFL_NEXUS (.NET 9 C#) Release Packaging & Verification
===========================================================================

Orchestrates clean Release builds, distribution staging, sanitization,
verification, and full-release ZIP packaging for EFL_NEXUS and updater.

Usage examples:
---------------
# Full build + package (default):
    python build_release.py build

# Verify an existing distribution staging directory:
    python build_release.py verify --directory dist/EFL_NEXUS

# Create full release ZIP from existing distribution:
    python build_release.py full-zip --directory dist/EFL_NEXUS --output dist/EFL_NEXUS_v1.0.8.zip

# Preflight check (.NET 9 SDK, workspace files, tools):
    python build_release.py preflight
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent

# Runtime files and directories that must NEVER be packaged into a public release
IGNORED_FILES = {
    "config.json",
    ".efl_records_cache.json",
    "sent_log.xlsx",
    "updater.log",
    "reconciliation_queue.json",
    ".load_reconciliation_tool_settings.json",
    ".env",
    "inbox.sqlite3",
    "inbox.sqlite3-wal",
    "inbox.sqlite3-shm",
    "outbox.sqlite3",
    "outbox.sqlite3-wal",
    "outbox.sqlite3-shm",
    "kpi_outbox.sqlite3",
    "kpi_outbox.sqlite3-wal",
    "kpi_outbox.sqlite3-shm",
    "provisioning.json",
    "credential.enc",
    "machine_credential.enc",
    "monitoring_active.token",
    "installation.json",
    "connection.json",
    "packing_list_config.json",
    "app_config.json",
    "release_notes_state.json",
    "website_grabber_results.json",
    "website_grabber_browser.log",
    "website_grabber_command.json",
    "website_grabber_downloads.json",
    "website_grabber_loading_history.json",
    "loading_history_command.json",
    "website_grabber_job_map.json",
}

DEFAULT_DEPLOY_FILES = (
    "templates.xlsx",
    "variance_templates.xlsx",
    "credentials.json",
    "efl_users.json",
    "aurora_bg.png",
    "icon.ico",
    "icon_2.ico",
    "release_notes.txt",
)


def _sha256(path: Path) -> str:
    """Calculate hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _should_ignore_file(rel_posix: str, include_pdbs: bool = False) -> bool:
    """Return True if rel_posix should be excluded from release packages."""
    rel_lower = rel_posix.lower()
    base_lower = os.path.basename(rel_lower)
    parts = rel_lower.split("/")[:-1]

    # Directories that contain temporary, user, or build cache state
    ignore_dirs = {
        "grn_images", "whatsapp_gdn", "webview_profile", "webview_internal_profile",
        "webview_loading_history_profile", "diagnostics",
        "scratch", "node_modules", "obj", "bin", ".vs", ".vscode", ".git"
    }
    if any(
        p in ignore_dirs
        or p.startswith("chrome_automation_profile_")
        or p.startswith("webview_profile")
        or "whatsapp" in p
        for p in parts
    ):
        return True

    # Ignored extensions & patterns
    if not include_pdbs and base_lower.endswith(".pdb"):
        return True
    if base_lower.endswith(".xml") and ("webview2" in base_lower or "microsoft" in base_lower):
        return True
    if base_lower.startswith(".env.") or base_lower.endswith((".sqlite", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm")):
        return True
    if base_lower.startswith("deploy-") and base_lower.endswith(".zip"):
        return True
    if base_lower.endswith((".lock", ".token", ".log")):
        return True
    if rel_lower in IGNORED_FILES or base_lower in IGNORED_FILES:
        return True
    if base_lower.startswith("~$"):
        return True
    if base_lower.startswith(("chrome_automation_profile_", "webview_profile", "website_grabber_")):
        if not base_lower.endswith(".dll"):
            return True
    if rel_lower.endswith((".old", ".tmp", ".pyc")):
        return True
    if "__pycache__" in rel_lower:
        return True
    return False


def clean_version(val: str) -> str:
    """Normalize version string by stripping prefixes."""
    return re.sub(r"^(EFL_NEXUS_)?v?", "", val.strip(), flags=re.IGNORECASE)


def read_version(root: Path = ROOT) -> str:
    """Read version string from version.txt."""
    path = root / "version.txt"
    if path.is_file():
        v = path.read_text(encoding="utf-8-sig").strip()
        if v:
            return clean_version(v)
    return "1.0.8"


def read_build_number(root: Path = ROOT) -> int:
    """Read build number from build.txt."""
    path = root / "build.txt"
    if path.is_file():
        try:
            return int(path.read_text(encoding="utf-8-sig").strip())
        except (ValueError, OSError):
            pass
    return 0


def preflight():
    """Verify prerequisites before attempting to build."""
    print("Running release preflight checks...")

    # Check dotnet SDK
    try:
        res = subprocess.run(["dotnet", "--version"], capture_output=True, text=True, check=True)
        dotnet_ver = res.stdout.strip()
        print(f"  [OK] .NET SDK installed: {dotnet_ver}")
        if not dotnet_ver.startswith("9."):
            print(f"  [WARNING] Expected .NET 9.x SDK, found {dotnet_ver}")
    except (FileNotFoundError, subprocess.SubprocessError) as ex:
        raise RuntimeError("dotnet SDK was not found in PATH. Install .NET 9 SDK.") from ex

    # Check required project files
    for proj in (
        "EFL_NEXUS/EFL_NEXUS.csproj",
        "EFL_NEXUS.Updater/EFL_NEXUS.Updater.csproj",
        "EFL_NEXUS.Core/EFL_NEXUS.Core.csproj",
        "KorberAuditShip/src/KorberAuditShip/KorberAuditShip.csproj"
    ):
        p = ROOT / proj
        if not p.is_file():
            raise RuntimeError(f"Required project file missing: {p}")
        print(f"  [OK] Found project: {proj}")

    # Check required deployment assets
    for asset in DEFAULT_DEPLOY_FILES:
        p = ROOT / asset
        if not p.is_file():
            print(f"  [WARNING] Root asset not found: {asset}")
        else:
            print(f"  [OK] Root asset found: {asset}")

    # Check OCR assets
    ocr_dir = ROOT / "assets" / "grn_ocr"
    if (ocr_dir / "manifest.json").is_file() and (ocr_dir / "tesseract.exe").is_file():
        print("  [OK] Native GRN OCR assets present.")
    else:
        print("  [WARNING] assets/grn_ocr is missing or incomplete.")

    # Check Inno Setup compiler
    iscc = find_iscc()
    if iscc:
        print(f"  [OK] Inno Setup compiler available: {iscc}")
    else:
        print("  [INFO] Inno Setup not found. Setup installer (.exe) will be skipped if building without it.")

    print("Preflight checks passed successfully!\n")


def sanitize_distribution(directory: Path, include_pdbs: bool = False):
    """Remove runtime state, temporary files, and debug files from distribution directory."""
    directory = directory.resolve()
    if not directory.is_dir():
        raise RuntimeError(f"Distribution directory does not exist: {directory}")

    removed_count = 0

    # 1. Explicitly remove config.json if present (developer settings must never be distributed)
    for cfg in list(directory.rglob("config.json")):
        try:
            cfg.unlink()
            removed_count += 1
            print("  [OK] Removed config.json from distribution staging (developer settings excluded).")
        except OSError as ex:
            print(f"  [WARNING] Could not delete config.json: {ex}")

    # 2. Sanitize efl_users.json (clear remembered_user for release)
    users_file = directory / "efl_users.json"
    if users_file.is_file():
        try:
            udata = json.loads(users_file.read_text(encoding="utf-8-sig"))
            if udata.get("remembered_user"):
                udata["remembered_user"] = ""
                users_file.write_text(json.dumps(udata, indent=2), encoding="utf-8")
                print("  [OK] Sanitized efl_users.json: cleared remembered_user for release.")
        except Exception as ex:
            print(f"  [WARNING] Could not sanitize efl_users.json: {ex}")

    # 3. Explicitly remove WhatsApp / WebView session directories and automation profiles
    for sub in list(directory.rglob("*")):
        if sub.is_dir():
            sname = sub.name.lower()
            if (
                sname == "whatsapp_gdn"
                or sname.startswith("webview_profile")
                or sname.startswith("webview_internal_profile")
                or sname.startswith("webview_loading_history_profile")
                or sname.startswith("chrome_automation_profile_")
                or sname in ("diagnostics", "grn_images", "scratch")
            ):
                try:
                    shutil.rmtree(sub, ignore_errors=True)
                    removed_count += 1
                    print(f"  [OK] Removed session/automation profile: {sub.name}")
                except Exception as ex:
                    print(f"  [WARNING] Could not delete directory {sub.name}: {ex}")

    # 4. Remove all files matching _should_ignore_file
    for path in list(directory.rglob("*")):
        if path.is_file():
            if not path.resolve().is_relative_to(directory):
                continue
            relative = path.relative_to(directory).as_posix()
            if relative in ("build.txt", "version.txt"):
                continue
            if _should_ignore_file(relative, include_pdbs=include_pdbs):
                try:
                    path.unlink()
                    removed_count += 1
                except OSError as ex:
                    print(f"  [WARNING] Could not delete {path.name}: {ex}")

    # Clean empty directories
    for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            try:
                path.rmdir()
            except OSError:
                pass

    if removed_count > 0:
        print(f"  Sanitized distribution: removed {removed_count} development/runtime files.")


def verify_ocr_runtime(runtime: Path):
    """Verify native Tesseract OCR bundle against its manifest."""
    runtime = runtime.resolve()
    manifest_file = runtime / "manifest.json"
    if not manifest_file.is_file():
        print("  [INFO] No OCR manifest.json found; skipping OCR checksum verification.")
        return

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    files_map = manifest.get("files", {})
    for name, expected in files_map.items():
        if name == "manifest.json":
            continue
        path = (runtime / name).resolve()
        if not path.is_file() or _sha256(path) != expected:
            raise RuntimeError(f"Packaged OCR checksum mismatch: {name}")

    model_path = runtime / "tessdata" / "eng.traineddata"
    if model_path.is_file() and "model_sha256" in manifest:
        if _sha256(model_path) != manifest["model_sha256"]:
            raise RuntimeError("Packaged English OCR model checksum mismatch.")

    tess_exe = runtime / "tesseract.exe"
    if tess_exe.is_file():
        try:
            subprocess.run(
                [str(tess_exe), "--version"],
                check=True,
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            print("  [OK] Native Tesseract OCR runtime verified.")
        except Exception as ex:
            print(f"  [WARNING] Tesseract self-test encountered an issue: {ex}")


def verify_distribution(directory: Path, expected_version: str = None, expected_build: int = None):
    """Verify that all required binaries and assets exist in the distribution directory."""
    directory = directory.resolve()
    print(f"Verifying distribution at {directory} ...")

    required_files = [
        "EFL_NEXUS.exe",
        "EFL_NEXUS.dll",
        "EFL_NEXUS.runtimeconfig.json",
        "EFL_NEXUS.deps.json",
        "EFL_NEXUS.Core.dll",
        "updater.exe",
        "updater.dll",
        "updater.runtimeconfig.json",
        "updater.deps.json",
        "version.txt",
        "build.txt",
        "aurora_bg.png",
        "templates.xlsx",
        "variance_templates.xlsx",
        "credentials.json",
        "efl_users.json",
    ]

    missing = []
    for rel in required_files:
        if not (directory / rel).is_file():
            missing.append(rel)

    has_korber = (directory / "KorberAuditShip.dll").is_file()
    if not has_korber:
        missing.append("KorberAuditShip.dll")

    if missing:
        raise RuntimeError(f"Distribution is missing critical files:\n  - " + "\n  - ".join(missing))

    # Verify version.txt content
    ver_path = directory / "version.txt"
    dist_ver = clean_version(ver_path.read_text(encoding="utf-8-sig").strip())
    if expected_version and dist_ver != expected_version:
        raise RuntimeError(f"Distribution version.txt ({dist_ver}) does not match expected version ({expected_version})")

    # Verify build.txt content
    build_path = directory / "build.txt"
    try:
        dist_build = int(build_path.read_text(encoding="utf-8-sig").strip())
        if expected_build is not None and dist_build != expected_build:
            raise RuntimeError(f"Distribution build.txt ({dist_build}) does not match expected build ({expected_build})")
    except ValueError:
        raise RuntimeError(f"Invalid build.txt content in distribution: {build_path.read_text()}")

    # Verify native runtimes
    native_dlls = ["OpenCvSharpExtern.dll", "WebView2Loader.dll", "e_sqlite3.dll"]
    for dll in native_dlls:
        # Check root or runtimes/win-x64/native
        if not (directory / dll).is_file() and not (directory / "runtimes" / "win-x64" / "native" / dll).is_file():
            print(f"  [WARNING] Native binary {dll} not found at root or in runtimes/win-x64/native")

    # Verify OCR if present
    ocr_dir = directory / "assets" / "grn_ocr"
    if ocr_dir.is_dir():
        verify_ocr_runtime(ocr_dir)

    # Verify no credentials or session state exist in distribution
    if (directory / "config.json").is_file():
        raise RuntimeError("Security violation: config.json (containing developer settings/credentials) is present in distribution staging!")

    for bad_name in ("whatsapp_gdn", "webview_profile", "webview_internal_profile", "webview_loading_history_profile"):
        if (directory / bad_name).exists():
            raise RuntimeError(f"Security violation: WhatsApp/WebView profile directory '{bad_name}' is present in distribution staging!")

    # Verify templates are present
    if not (directory / "templates.xlsx").is_file():
        raise RuntimeError("Missing required template: templates.xlsx is not present in distribution staging!")
    if not (directory / "variance_templates.xlsx").is_file():
        raise RuntimeError("Missing required template: variance_templates.xlsx is not present in distribution staging!")

    # Verify efl_users.json has empty remembered_user
    users_file = directory / "efl_users.json"
    if users_file.is_file():
        try:
            udata = json.loads(users_file.read_text(encoding="utf-8-sig"))
            if udata.get("remembered_user"):
                raise RuntimeError(f"Distribution efl_users.json contains remembered_user '{udata.get('remembered_user')}'. Must be empty for public release.")
        except json.JSONDecodeError:
            raise RuntimeError("Distribution efl_users.json is invalid JSON.")

    print(f"  [OK] Distribution verified: version v{dist_ver} (Build {dist_build}), all core assemblies, updater and assets present.")
    print("  [OK] Security verified: no config.json credentials, remembered_user is cleared, and WhatsApp session profiles are stripped.")


def release_files(directory: Path, include_pdbs: bool = False):
    """Yield (relative_posix_path, absolute_path) for all files to be packaged into the release ZIP."""
    directory = directory.resolve()
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(directory):
            continue
        rel = path.relative_to(directory).as_posix()
        if rel in ("version.txt", "build.txt") or not _should_ignore_file(rel, include_pdbs=include_pdbs):
            yield rel, path


def full_release_zip(directory: Path, output_zip: Path, include_pdbs: bool = False):
    """Package the distribution directory into a full release ZIP with max compression."""
    directory = directory.resolve()
    output_zip = output_zip.resolve()

    if output_zip.is_relative_to(directory):
        raise RuntimeError("Output ZIP cannot be located inside the distribution directory.")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    files = list(release_files(directory, include_pdbs=include_pdbs))
    if not files:
        raise RuntimeError("No files to package into release archive.")

    print(f"Packaging {len(files)} files into {output_zip} ...")
    total_uncompressed = 0

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel, path in files:
            archive.write(path, rel)
            total_uncompressed += path.stat().st_size

    zip_size = output_zip.stat().st_size
    ratio = (1.0 - (zip_size / max(1, total_uncompressed))) * 100

    print("\n" + "=" * 65)
    print("  FULL RELEASE PACKAGE COMPLETED")
    print("=" * 65)
    print(f"  Archive       : {output_zip.name}")
    print(f"  Path          : {output_zip}")
    print(f"  Files         : {len(files)}")
    print(f"  Uncompressed  : {total_uncompressed / (1024 * 1024):.2f} MB")
    print(f"  Compressed    : {zip_size / (1024 * 1024):.2f} MB ({ratio:.1f}% space saved)")
    print("=" * 65 + "\n")


def find_iscc() -> Path | None:
    """Find Inno Setup compiler (ISCC.exe) on the system."""
    candidates = [
        Path(r"C:\Program Files\Inno Setup 7\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    which = shutil.which("iscc")
    if which:
        return Path(which)
    return None


def build_installer(dist_dir: Path, output_dir: Path, version: str, build: int) -> Path | None:
    """Build Windows Setup installer (.exe) using Inno Setup."""
    iscc = find_iscc()
    if not iscc:
        print("  [WARNING] Inno Setup compiler (ISCC.exe) not found. Skipping installer creation.")
        print("            To build setup executables, install Inno Setup 7 from https://jrsoftware.org/isdl.php")
        return None

    iss_script = ROOT / "installer.iss"
    if not iss_script.is_file():
        print(f"  [WARNING] Inno Setup script {iss_script} not found. Skipping installer creation.")
        return None

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_base = f"EFL_NEXUS_Setup_v{version}"
    expected_exe = output_dir / f"{setup_base}.exe"

    print(f"Building Windows Setup installer ({setup_base}.exe) using Inno Setup...")
    cmd = [
        str(iscc),
        f"/dMyAppVersion={version}",
        f"/dMyAppBuild={build}",
        f"/dSourceDir={dist_dir.resolve()}",
        f"/dOutputDir={output_dir}",
        f"/dOutputBaseFilename={setup_base}",
        str(iss_script),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr or res.stdout)
        raise RuntimeError("Inno Setup compilation failed.")

    if not expected_exe.is_file():
        raise RuntimeError(f"Expected installer executable was not created: {expected_exe}")

    size_mb = expected_exe.stat().st_size / (1024 * 1024)
    print("\n" + "=" * 65)
    print("  WINDOWS SETUP INSTALLER COMPLETED")
    print("=" * 65)
    print(f"  Installer     : {expected_exe.name}")
    print(f"  Path          : {expected_exe}")
    print(f"  Size          : {size_mb:.2f} MB")
    print("=" * 65 + "\n")
    return expected_exe


def terminate_running_instances():
    """Terminate any running EFL_NEXUS.exe or updater.exe processes to avoid file lock errors during build."""
    if sys.platform != "win32":
        return
    for proc_name in ("EFL_NEXUS.exe", "updater.exe"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", proc_name],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
        except Exception:
            pass


def build_release_pipeline(
    dist_dir: Path,
    output_zip: Path,
    version: str,
    build: int,
    clean: bool = True,
    include_pdbs: bool = False,
    self_contained: bool = False,
    build_setup: bool = True,
):
    """Execute complete compilation, staging, sanitization, verification, packaging, and installer creation."""
    terminate_running_instances()
    mode_label = "Self-Contained (.NET 9 bundled)" if self_contained else "Framework-Dependent (Requires .NET 9)"
    print("==========================================================")
    print(f"  EFL_NEXUS Release Builder -- v{version} (Build {build})")
    print(f"  Mode: {mode_label}")
    print("==========================================================\n")

    dist_dir = dist_dir.resolve()
    if clean and dist_dir.exists():
        print(f"Cleaning previous staging directory: {dist_dir} ...")
        shutil.rmtree(dist_dir, ignore_errors=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    sc_flag = "--self-contained" if self_contained else "--no-self-contained"

    # 1. Publish companion updater
    print("[1/5] Publishing companion updater (EFL_NEXUS.Updater)...")
    updater_proj = ROOT / "EFL_NEXUS.Updater" / "EFL_NEXUS.Updater.csproj"
    updater_pub_tmp = ROOT / "EFL_NEXUS.Updater" / "bin" / "Release" / "net9.0-windows" / "win-x64" / "publish"
    
    cmd_updater = [
        "dotnet", "publish", str(updater_proj),
        "-c", "Release",
        "-r", "win-x64",
        sc_flag,
        "-o", str(updater_pub_tmp)
    ]
    res = subprocess.run(cmd_updater, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr or res.stdout)
        raise RuntimeError("Failed to publish EFL_NEXUS.Updater.")
    print("  [OK] EFL_NEXUS.Updater published successfully.")

    # 2. Publish EFL_NEXUS (main application with KorberAuditShip natively integrated)
    print("\n[2/5] Publishing main application (EFL_NEXUS)...")
    main_proj = ROOT / "EFL_NEXUS" / "EFL_NEXUS.csproj"
    cmd_main = [
        "dotnet", "publish", str(main_proj),
        "-c", "Release",
        "-r", "win-x64",
        sc_flag,
        "-o", str(dist_dir)
    ]
    res = subprocess.run(cmd_main, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr or res.stdout)
        raise RuntimeError("Failed to publish EFL_NEXUS.")
    print("  [OK] EFL_NEXUS published successfully.")

    # 3. Ensure updater artifacts and default assets are staged into dist_dir root
    print("\n[3/5] Staging companion binaries and default assets...")
    updater_artifacts = ["updater.exe", "updater.dll", "updater.deps.json", "updater.runtimeconfig.json"]
    for art in updater_artifacts:
        src = updater_pub_tmp / art
        if not src.is_file():
            # Fallback to direct bin directory if not in publish
            src = ROOT / "EFL_NEXUS.Updater" / "bin" / "Release" / "net9.0-windows" / art
        if src.is_file():
            shutil.copy2(src, dist_dir / art)
        else:
            print(f"  [WARNING] Updater artifact not found: {art}")

    # Clean up any legacy external KorberAuditShip subfolder from older builds if present
    legacy_subfolder = dist_dir / "KorberAuditShip"
    if legacy_subfolder.is_dir():
        shutil.rmtree(legacy_subfolder, ignore_errors=True)

    # Copy root assets
    for asset in DEFAULT_DEPLOY_FILES:
        src = ROOT / asset
        if src.is_file():
            shutil.copy2(src, dist_dir / asset)

    # Clean up developer settings file if copied or generated during publish
    cfg_file = dist_dir / "config.json"
    if cfg_file.is_file():
        try:
            cfg_file.unlink()
        except OSError:
            pass

    # Sanitize staged efl_users.json: clear remembered_user so release is clean
    staged_users = dist_dir / "efl_users.json"
    if staged_users.is_file():
        try:
            udata = json.loads(staged_users.read_text(encoding="utf-8-sig"))
            if udata.get("remembered_user"):
                udata["remembered_user"] = ""
                staged_users.write_text(json.dumps(udata, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Copy assets folder if present
    assets_dir = ROOT / "assets"
    if assets_dir.is_dir():
        dst_assets = dist_dir / "assets"
        if not dst_assets.exists():
            shutil.copytree(assets_dir, dst_assets, dirs_exist_ok=True)

    # Write authoritative version.txt and build.txt into distribution
    (dist_dir / "version.txt").write_text(version, encoding="utf-8")
    (dist_dir / "build.txt").write_text(str(build), encoding="utf-8")
    print(f"  [OK] Deployed version.txt (v{version}) and build.txt ({build}).")

    # Sanitize
    sanitize_distribution(dist_dir, include_pdbs=include_pdbs)

    # Verify
    verify_distribution(dist_dir, expected_version=version, expected_build=build)

    # 4. Create ZIP
    print("\n[4/5] Creating full-release distribution archive...")
    full_release_zip(dist_dir, output_zip, include_pdbs=include_pdbs)

    # 5. Build Windows Setup Installer
    if build_setup:
        print("\n[5/5] Building Windows Setup Installer executable...")
        build_installer(dist_dir=dist_dir, output_dir=output_zip.parent, version=version, build=build)


def clean_local_user_data(root: Path = ROOT, clean_whatsapp: bool = True, clean_settings: bool = True):
    """
    Cleans local user credentials from config.json, resets remembered_user in efl_users.json,
    removes WhatsApp and Chrome automation profiles (logging out WhatsApp completely),
    and clears runtime caches/logs while strictly preserving default templates (templates.xlsx
    and variance_templates.xlsx).
    """
    print("\n" + "=" * 65)
    print("  CLEANING USER DATA, CREDENTIALS & AUTOMATION PROFILES")
    print("=" * 65)

    root = root.resolve()
    local_app_data = Path(os.environ.get("LOCALAPPDATA", "")) / "EFL_NEXUS"

    cleaned_items = []

    # 1. Sanitize config.json (strip developer credentials, keep default URLs/structure)
    if clean_settings:
        config_paths = [
            root / "config.json",
            root / "EFL_NEXUS" / "bin" / "Debug" / "net9.0-windows" / "config.json",
            root / "EFL_NEXUS" / "bin" / "Release" / "net9.0-windows" / "win-x64" / "config.json",
            local_app_data / "config.json",
        ]
        credential_keys = [
            "korber_user", "korber_pass",
            "auditship_user", "auditship_pass", "auditship_fork_id",
            "kpi_user_id", "kpi_user_code", "data_grabber_user"
        ]
        for cfg_path in config_paths:
            if cfg_path.is_file():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
                    modified = False
                    for k in credential_keys:
                        if data.get(k):
                            data[k] = ""
                            modified = True
                    if modified:
                        cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        cleaned_items.append(f"Sanitized credentials in {cfg_path.name} ({cfg_path.parent.name})")
                except Exception as ex:
                    print(f"  [WARNING] Could not sanitize {cfg_path}: {ex}")

    # 2. Reset remembered_user in efl_users.json
    users_paths = [
        root / "efl_users.json",
        root / "EFL_NEXUS" / "bin" / "Debug" / "net9.0-windows" / "efl_users.json",
        root / "EFL_NEXUS" / "bin" / "Release" / "net9.0-windows" / "win-x64" / "efl_users.json",
        local_app_data / "efl_users.json",
    ]
    for u_path in users_paths:
        if u_path.is_file():
            try:
                udata = json.loads(u_path.read_text(encoding="utf-8-sig"))
                if udata.get("remembered_user"):
                    udata["remembered_user"] = ""
                    u_path.write_text(json.dumps(udata, indent=2), encoding="utf-8")
                    cleaned_items.append(f"Reset remembered_user in {u_path.name} ({u_path.parent.name})")
            except Exception as ex:
                print(f"  [WARNING] Could not reset {u_path}: {ex}")

    # 3. Clean user runtime state files
    runtime_files = [
        "sent_log.xlsx",
        "reconciliation_queue.json",
        "packing_list_config.json",
        "app_config.json",
        ".load_reconciliation_tool_settings.json",
        ".efl_records_cache.json",
        "release_notes_state.json",
        "website_grabber_results.json",
        "website_grabber_browser.log",
        "website_grabber_command.json",
        "website_grabber_downloads.json",
        "website_grabber_loading_history.json",
        "loading_history_command.json",
        "website_grabber_job_map.json",
        "inbox.sqlite3", "inbox.sqlite3-wal", "inbox.sqlite3-shm",
        "outbox.sqlite3", "outbox.sqlite3-wal", "outbox.sqlite3-shm",
        "kpi_outbox.sqlite3", "kpi_outbox.sqlite3-wal", "kpi_outbox.sqlite3-shm",
        "updater.log",
    ]
    search_dirs = [
        root,
        root / "EFL_NEXUS" / "bin" / "Debug" / "net9.0-windows",
        root / "EFL_NEXUS" / "bin" / "Release" / "net9.0-windows" / "win-x64",
        local_app_data,
        Path(os.environ.get("USERPROFILE", ""))
    ]
    for s_dir in search_dirs:
        if not s_dir.is_dir():
            continue
        for rf in runtime_files:
            target = s_dir / rf
            if target.is_file():
                try:
                    target.unlink()
                    cleaned_items.append(f"Removed runtime file: {target.name} from {s_dir.name}")
                except OSError as ex:
                    print(f"  [WARNING] Could not delete {target}: {ex}")

    # 4. Clean WhatsApp & Chrome automation profiles (Log out WhatsApp)
    if clean_whatsapp:
        profile_patterns = [
            "webview_profile*",
            "webview_internal_profile*",
            "webview_loading_history_profile*",
            "whatsapp_gdn",
            "chrome_automation_profile_*",
            "diagnostics",
            "grn_images",
        ]
        for p_dir in [root, root / "EFL_NEXUS" / "bin" / "Debug" / "net9.0-windows", local_app_data]:
            if not p_dir.is_dir():
                continue
            for pattern in profile_patterns:
                for match in p_dir.glob(pattern):
                    if match.is_dir():
                        try:
                            shutil.rmtree(match, ignore_errors=True)
                            cleaned_items.append(f"Deleted profile: {match.name} (WhatsApp logged out)")
                        except Exception as ex:
                            print(f"  [WARNING] Could not delete {match}: {ex}")

    # 5. Verify templates remain intact
    for t_name in ("templates.xlsx", "variance_templates.xlsx"):
        t_path = root / t_name
        if t_path.is_file():
            print(f"  [OK] Template kept safe: {t_name}")
        else:
            print(f"  [WARNING] Template missing from root: {t_name}")

    if cleaned_items:
        for item in cleaned_items:
            print(f"  - {item}")
    else:
        print("  No user credentials, sessions, or runtime state found to clean.")

    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="EFL_NEXUS Release Packaging Tool (.NET 9 C#)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="build",
        choices=("build", "preflight", "verify", "sanitize", "full-zip", "installer", "clean-user-data"),
        help="Action to execute (default: build)",
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=ROOT / "dist" / "EFL_NEXUS",
        help="Distribution staging directory. Default: dist/EFL_NEXUS",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path for output ZIP file (default: dist/EFL_NEXUS_v<version>.zip)",
    )
    parser.add_argument(
        "--version",
        help="Release version string (e.g. 1.0.8). Default: read from version.txt",
    )
    parser.add_argument(
        "--build",
        type=int,
        help="Release build number (e.g. 0). Default: read from build.txt",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean dist directory before build",
    )
    parser.add_argument(
        "--include-pdbs",
        action="store_true",
        help="Include .pdb symbol files in distribution",
    )
    parser.add_argument(
        "--self-contained",
        action="store_true",
        help="Bundle .NET 9 runtime inside the distribution (no .NET runtime installation required on client PCs)",
    )
    parser.add_argument(
        "--clean-user-data",
        action="store_true",
        help="Sanitize local user credentials, runtime logs, and log out WhatsApp before building",
    )
    parser.add_argument(
        "--no-installer",
        action="store_true",
        help="Skip building Windows Setup installer executable (.exe)",
    )

    args = parser.parse_args()

    # Resolve version & build
    ver = clean_version(args.version) if args.version else read_version(ROOT)
    bld = args.build if args.build is not None else read_build_number(ROOT)

    out_zip = args.output
    if not out_zip:
        out_zip = ROOT / "dist" / f"EFL_NEXUS_v{ver}.zip"

    try:
        if args.action == "clean-user-data":
            clean_local_user_data(ROOT)
        elif args.action == "preflight":
            preflight()
        elif args.action == "verify":
            verify_distribution(args.directory, expected_version=ver, expected_build=bld)
        elif args.action == "sanitize":
            sanitize_distribution(args.directory, include_pdbs=args.include_pdbs)
        elif args.action == "full-zip":
            full_release_zip(args.directory, out_zip, include_pdbs=args.include_pdbs)
        elif args.action == "installer":
            build_installer(dist_dir=args.directory, output_dir=out_zip.parent, version=ver, build=bld)
        elif args.action == "build":
            if args.clean_user_data:
                clean_local_user_data(ROOT)
            preflight()
            build_release_pipeline(
                dist_dir=args.directory,
                output_zip=out_zip,
                version=ver,
                build=bld,
                clean=not args.no_clean,
                include_pdbs=args.include_pdbs,
                self_contained=args.self_contained,
                build_setup=not args.no_installer,
            )
    except (RuntimeError, OSError, ValueError) as ex:
        sys.exit(f"\n[ERROR] {ex}")


if __name__ == "__main__":
    main()
