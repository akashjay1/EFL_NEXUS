"""
create_patch.py -- EFL_NEXUS (.NET 9 C#) Differential Patch Generator
=====================================================================

Compares a newly built distribution directory against a baseline release
(either an existing folder, a local full-release ZIP, or automatically
downloaded from GitHub Releases) and produces a minimal differential patch ZIP
containing only new and modified files.

User configuration and template files (such as templates.xlsx and
variance_templates.xlsx) are excluded from patches so user modifications are
never overwritten.

Usage examples:
---------------
# Auto-detect baseline from dist/ or GitHub, using next build number:
    python create_patch.py --new-dir dist/EFL_NEXUS --auto-find-prev dist/ --build 1

# Specify baseline ZIP manually:
    python create_patch.py --new-dir dist/EFL_NEXUS --prev-zip dist/EFL_NEXUS_v1.0.8.zip --build 1

# Diff against an extracted previous release directory:
    python create_patch.py --new-dir dist/EFL_NEXUS --prev-dir C:/old_releases/EFL_NEXUS_v1.0.8 --build 1

Output:
-------
    dist/EFL_Nexus_Patch_v<version>_b<build>.zip
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

# Try importing requests if available; fallback to urllib
try:
    import requests
except ImportError:
    requests = None

ROOT = Path(__file__).resolve().parent

GITHUB_USER = "akashjay1"
GITHUB_REPO = "EFL_NEXUS"

IGNORED_FILES = {
    "config.json",
    ".efl_records_cache.json",
    "build.txt",
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
    "templates.xlsx",
    "variance_templates.xlsx",
    "efl_users.json",
}


def _sha256(path: Path) -> str:
    """Return hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _should_ignore_file(rel_posix: str) -> bool:
    """Return True if the file should be excluded from patches."""
    rel_lower = rel_posix.lower()
    base_lower = os.path.basename(rel_lower)
    parts = rel_lower.split("/")[:-1]

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

    if base_lower.endswith(".pdb"):
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


def _index_dir(root: Path) -> dict:
    """Return {relative_posix_path: sha256} for all valid files under root."""
    index = {}
    root = root.resolve()
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if _should_ignore_file(rel):
                continue
            index[rel] = _sha256(p)
    return index


def _extract_zip_to_temp(zip_path: Path):
    """
    Extract zip_path into a temp directory.
    If the zip has a single root folder (e.g. EFL_NEXUS/), unwrap it automatically.
    Returns (tmp_root, content_root). Caller must cleanup tmp_root.
    """
    tmp = Path(tempfile.mkdtemp(prefix="efl_patch_prev_"))
    print(f"  Extracting baseline archive {zip_path.name} to {tmp} ...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(tmp)

    entries = list(tmp.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        content_dir = entries[0]
    else:
        content_dir = tmp

    return tmp, content_dir


def _download_github_baseline(
    version: str,
    target_dir: Path,
    repo_user: str = GITHUB_USER,
    repo_name: str = GITHUB_REPO
) -> Path | None:
    """Download baseline full-release ZIP from GitHub Releases."""
    clean_ver = re.sub(r"^(EFL_NEXUS_)?v?", "", version.strip(), flags=re.IGNORECASE)
    api_url = f"https://api.github.com/repos/{repo_user}/{repo_name}/releases"
    headers = {"User-Agent": "EFL-Nexus-Patch-Generator", "Accept": "application/vnd.github.v3+json"}

    print(f"  Querying GitHub releases for baseline ({repo_user}/{repo_name}) ...")

    releases = []
    try:
        if requests:
            resp = requests.get(api_url, headers=headers, timeout=15)
            resp.raise_for_status()
            releases = resp.json()
        else:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                releases = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        print(f"  [WARNING] Could not query GitHub releases: {ex}")
        return None

    target_asset = None
    target_tag = ""

    # 1. Look for full-release ZIP matching clean_ver
    for rel in releases:
        tag = re.sub(r"^(EFL_NEXUS_)?v?", "", rel.get("tag_name", "").strip(), flags=re.IGNORECASE)
        for asset in rel.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".zip") and "patch" not in name.lower():
                if tag == clean_ver or name == f"EFL_NEXUS_v{clean_ver}.zip":
                    target_asset = asset
                    target_tag = tag
                    break
        if target_asset:
            break

    # 2. Look for latest full-release ZIP of any version
    if not target_asset and releases:
        for rel in releases:
            tag = re.sub(r"^(EFL_NEXUS_)?v?", "", rel.get("tag_name", "").strip(), flags=re.IGNORECASE)
            for asset in rel.get("assets", []):
                name = asset.get("name", "")
                if name.lower().endswith(".zip") and "patch" not in name.lower():
                    target_asset = asset
                    target_tag = tag
                    break
            if target_asset:
                break

    if not target_asset:
        print("  [WARNING] No full release ZIP asset found on GitHub.")
        return None

    download_url = target_asset.get("browser_download_url")
    asset_name = target_asset.get("name")
    asset_size = target_asset.get("size", 0)
    out_path = target_dir / asset_name

    print(f"  Found remote baseline: {asset_name} (Release v{target_tag}, {asset_size / (1024 * 1024):.2f} MB)")
    print(f"  Downloading baseline to {out_path} ...")

    try:
        if requests:
            with requests.get(download_url, headers=headers, stream=True, timeout=60) as r:
                r.raise_for_status()
                downloaded = 0
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if asset_size > 0:
                                pct = (downloaded / asset_size) * 100
                                print(f"\r  Progress: {pct:5.1f}% ({downloaded / (1024 * 1024):.1f} MB)", end="", flush=True)
                print()
        else:
            req = urllib.request.Request(download_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r, open(out_path, "wb") as f:
                downloaded = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if asset_size > 0:
                        pct = (downloaded / asset_size) * 100
                        print(f"\r  Progress: {pct:5.1f}% ({downloaded / (1024 * 1024):.1f} MB)", end="", flush=True)
                print()

        print(f"  [OK] Baseline downloaded successfully: {out_path.name}")
        return out_path
    except Exception as ex:
        print(f"\n  [ERROR] Failed to download baseline from GitHub: {ex}")
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        return None


def _find_prev_zip(search_dir: Path, new_version: str) -> Path | None:
    """
    Find best baseline ZIP:
      1. EFL_NEXUS_v<new_version>.zip in search_dir (for hotfix on same version).
      2. Most recent EFL_NEXUS_v*.zip in search_dir.
      3. Fallback: Download from GitHub Releases.
    """
    clean_ver = re.sub(r"^(EFL_NEXUS_)?v?", "", new_version.strip(), flags=re.IGNORECASE)
    full_pattern = re.compile(r"EFL_NEXUS_v([\d.]+)\.zip$", re.IGNORECASE)
    same_ver_full = None
    other_ver_candidates = []

    if search_dir.is_dir():
        for p in search_dir.glob("EFL_NEXUS_v*.zip"):
            if "patch" in p.name.lower():
                continue
            m = full_pattern.match(p.name)
            if not m:
                continue
            ver = m.group(1)
            if ver == clean_ver:
                same_ver_full = p
            else:
                other_ver_candidates.append((p.stat().st_mtime, p))

    if same_ver_full is not None:
        return same_ver_full

    if other_ver_candidates:
        other_ver_candidates.sort(key=lambda t: t[0], reverse=True)
        return other_ver_candidates[0][1]

    # Fallback to GitHub
    print(f"  No local baseline ZIP found in {search_dir}. Attempting GitHub download...")
    return _download_github_baseline(clean_ver, search_dir)


def _read_build_from_dir(dist_dir: Path) -> int:
    """Read build number from build.txt."""
    for loc in [dist_dir / "build.txt", ROOT / "build.txt"]:
        if loc.is_file():
            try:
                return int(loc.read_text(encoding="utf-8-sig").strip())
            except (ValueError, OSError):
                pass
    return 0


def _read_version_from_dir(dist_dir: Path) -> str | None:
    """Read version from version.txt."""
    for loc in [dist_dir / "version.txt", ROOT / "version.txt"]:
        if loc.is_file():
            v = loc.read_text(encoding="utf-8-sig").strip()
            if v:
                return re.sub(r"^(EFL_NEXUS_)?v?", "", v, flags=re.IGNORECASE)
    return None


def compute_changed_files(new_dir: Path, prev_dir: Path) -> list:
    """
    Compare new_dir against prev_dir using SHA-256.
    Returns [(relative_posix_path, absolute_new_path)] for new or modified files.
    """
    print("  Indexing new build directory ...")
    new_index = _index_dir(new_dir)
    print(f"    -> {len(new_index):,} files in new build")

    print("  Indexing baseline directory ...")
    prev_index = _index_dir(prev_dir)
    print(f"    -> {len(prev_index):,} files in baseline")

    changed = []
    for rel, new_hash in new_index.items():
        # User templates, credentials, user databases, and user configs must never be overwritten by patches
        if rel.lower() in (
            "templates.xlsx", "variance_templates.xlsx", "efl_users.json",
            "config.json", ".env", "packing_list_config.json", "app_config.json",
            "sent_log.xlsx", "reconciliation_queue.json"
        ):
            continue
        if rel == "build.txt":
            continue

        prev_hash = prev_index.get(rel)
        if prev_hash is None or new_hash != prev_hash:
            changed.append((rel, new_dir / rel.replace("/", os.sep)))

    # Always ensure version.txt is included
    ver_rel = "version.txt"
    if not any(r == ver_rel for r, _ in changed):
        ver_abs = new_dir / ver_rel
        if ver_abs.is_file():
            changed.append((ver_rel, ver_abs))

    # Always ensure release_notes.txt is included in patch if present
    rn_rel = "release_notes.txt"
    if not any(r == rn_rel for r, _ in changed):
        rn_abs = new_dir / rn_rel
        if rn_abs.is_file():
            changed.append((rn_rel, rn_abs))

    return changed


def build_patch_zip(
    new_dir: Path,
    prev_dir: Path,
    output_zip: Path,
    version: str,
    build: int,
    is_hotfix: bool = False
):
    """Package changed files into differential patch ZIP and display summary."""
    changed = compute_changed_files(new_dir, prev_dir)

    if not changed and not is_hotfix:
        print("\n[WARNING] No changed files detected -- patch would be empty.")
        sys.exit(1)

    changed.sort(key=lambda t: t[0])

    print(f"\n  Building patch ZIP -> {output_zip} ...")
    tmp_build_dir = Path(tempfile.mkdtemp(prefix="efl_patch_bld_"))
    try:
        build_txt_path = tmp_build_dir / "build.txt"
        build_txt_path.write_text(str(build), encoding="utf-8")

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel, abs_path in changed:
                zf.write(abs_path, arcname=rel)
            # Inject authoritative build.txt
            zf.write(build_txt_path, arcname="build.txt")
    finally:
        shutil.rmtree(tmp_build_dir, ignore_errors=True)

    patch_size_mb = output_zip.stat().st_size / (1024 * 1024)
    new_total_mb = sum(p.stat().st_size for p in new_dir.rglob("*") if p.is_file()) / (1024 * 1024)
    ratio_pct = (patch_size_mb / max(0.001, new_total_mb)) * 100

    label = f"v{version} Build {build}" + (" [HOTFIX]" if is_hotfix else "")

    print("\n" + "=" * 65)
    print(f"  EFL_NEXUS PATCH CREATED: {label}")
    print("=" * 65)
    print(f"  Changed files   : {len(changed)} (+ build.txt)")
    print(f"  Patch ZIP size  : {patch_size_mb:.2f} MB")
    print(f"  Full build size : {new_total_mb:.2f} MB  (patch is {ratio_pct:.1f}% of full)")
    print()

    # Breakdown top 20 files
    with zipfile.ZipFile(output_zip, "r") as zf:
        infos = sorted(zf.infolist(), key=lambda i: i.compress_size, reverse=True)
        print(f"  {'File':<55}  {'Compressed':>10}  {'Original':>10}")
        print(f"  {'-' * 55}  {'-' * 10}  {'-' * 10}")
        for info in infos[:20]:
            c = info.compress_size / 1024
            u = info.file_size / 1024
            print(f"  {info.filename:<55}  {c:>8.1f} KB  {u:>8.1f} KB")
        if len(infos) > 20:
            print(f"  ... and {len(infos) - 20} more files")

    print("=" * 65)
    print(f"\nPatch ZIP: {output_zip.resolve()}\n")

    if is_hotfix:
        print("  Deploy instructions for HOTFIX:")
        print(f"  1. Go to existing GitHub Release for v{version}:")
        print(f"     https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/tag/v{version}")
        print("  2. Click 'Edit release' and upload:")
        print(f"     * {output_zip.name}")
        print("  3. Click 'Save release'. Users will automatically receive the hotfix!\n")
    else:
        print("  Deploy instructions for NEW RELEASE:")
        print(f"  1. Create new GitHub Release for v{version}:")
        print(f"     https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/new")
        print("  2. Attach both the patch and the full fallback package:")
        print(f"     * {output_zip.name}  (fast patch for existing users)")
        print(f"     * EFL_NEXUS_v{version}.zip  (full package for new installs)")
        print("  3. Publish release.\n")


def main():
    parser = argparse.ArgumentParser(
        description="EFL_NEXUS Differential Patch Generator (.NET 9 C#)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--new-dir",
        default=str(ROOT / "dist" / "EFL_NEXUS"),
        help="Path to newly compiled dist/EFL_NEXUS directory. Default: dist/EFL_NEXUS",
    )
    parser.add_argument(
        "--version",
        help="Target version string (e.g. 1.0.8). If omitted, read from version.txt",
    )
    parser.add_argument(
        "--build",
        type=int,
        default=None,
        help="Build number to embed in patch. Default: read from build.txt",
    )

    baseline = parser.add_mutually_exclusive_group(required=True)
    baseline.add_argument(
        "--prev-dir",
        help="Path to extracted previous release directory.",
    )
    baseline.add_argument(
        "--prev-zip",
        help="Path to previous full-release ZIP to compare against.",
    )
    baseline.add_argument(
        "--auto-find-prev",
        metavar="SEARCH_DIR",
        help="Search directory for baseline ZIP, falling back to GitHub Releases.",
    )

    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for patch ZIP. Default: dist",
    )
    parser.add_argument(
        "--repo-user",
        default=GITHUB_USER,
        help=f"GitHub repository owner (default: {GITHUB_USER})",
    )
    parser.add_argument(
        "--repo-name",
        default=GITHUB_REPO,
        help=f"GitHub repository name (default: {GITHUB_REPO})",
    )

    args = parser.parse_args()

    new_dir = Path(args.new_dir).resolve()
    if not new_dir.is_dir():
        sys.exit(f"[ERROR] --new-dir does not exist or is not a directory: {new_dir}")

    # Resolve version
    ver = args.version or _read_version_from_dir(new_dir)
    if not ver:
        sys.exit("[ERROR] Could not determine version. Pass --version or provide version.txt.")
    ver = re.sub(r"^(EFL_NEXUS_)?v?", "", ver.strip(), flags=re.IGNORECASE)

    # Resolve build
    if args.build is not None:
        build = args.build
    else:
        build = _read_build_from_dir(new_dir)

    print(f"\nBuilding patch for EFL_NEXUS v{ver} (Build {build})")
    print(f"  New build dir : {new_dir}")

    tmp_to_clean = None
    prev_zip_name = ""

    if args.prev_dir:
        prev_dir = Path(args.prev_dir).resolve()
        if not prev_dir.is_dir():
            sys.exit(f"[ERROR] --prev-dir does not exist: {prev_dir}")
        print(f"  Baseline dir  : {prev_dir}")

    elif args.prev_zip:
        prev_zip = Path(args.prev_zip).resolve()
        if not prev_zip.is_file():
            sys.exit(f"[ERROR] --prev-zip does not exist: {prev_zip}")
        tmp_to_clean, prev_dir = _extract_zip_to_temp(prev_zip)
        prev_zip_name = prev_zip.name

    else:  # --auto-find-prev
        search_dir = Path(args.auto_find_prev).resolve()
        prev_zip = _find_prev_zip(search_dir, ver)
        if prev_zip is None or not prev_zip.is_file():
            sys.exit(
                f"[ERROR] No baseline ZIP found in {search_dir} or on GitHub.\n"
                "  Run 'python build_release.py build' first to generate a full baseline,\n"
                "  or specify --prev-dir / --prev-zip manually."
            )
        print(f"  Baseline ZIP  : {prev_zip}")
        tmp_to_clean, prev_dir = _extract_zip_to_temp(prev_zip)
        prev_zip_name = prev_zip.name

    is_hotfix = (ver in prev_zip_name) or (build > 0)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_zip = output_dir / f"EFL_Nexus_Patch_v{ver}_b{build}.zip"

    try:
        build_patch_zip(new_dir, prev_dir, output_zip, ver, build, is_hotfix)
    finally:
        if tmp_to_clean and tmp_to_clean.exists():
            shutil.rmtree(tmp_to_clean, ignore_errors=True)


if __name__ == "__main__":
    main()
