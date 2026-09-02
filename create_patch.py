"""
create_patch.py -- EFL_Nexus Differential Patch Generator
=========================================================

Run this script after `pyinstaller --onedir` produces a fresh `dist/EFL_NEXUS/`
directory to create a minimal patch ZIP containing only new or changed files.

Build numbers allow hotfixes to be deployed to the SAME version without
bumping the version string. Each patch ZIP embeds a `build.txt` so the
updater can track which hotfix is installed.

Usage examples
--------------
# Automatic hotfix / upgrade patch generation (auto-finds local baseline or fetches from GitHub):
    python create_patch.py --new-dir dist/EFL_NEXUS --auto-find-prev dist/ --build 2

# Version upgrade patch (v1.0.4 -> v1.0.5):
    python create_patch.py --new-dir dist/EFL_NEXUS --prev-zip dist/EFL_NEXUS_v1.0.4.zip --version 1.0.5 --build 0

# Compare against an already-extracted previous directory:
    python create_patch.py --new-dir dist/EFL_NEXUS --prev-dir C:/old_builds/EFL_NEXUS_v1.0.4

Output
------
    dist/EFL_Nexus_Patch_v<version>_b<build>.zip

Upload this ZIP to the GitHub Release.
For hotfixes, add the patch ZIP to the EXISTING release -- no new tag needed.
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None


GITHUB_USER = "akashjay1"
GITHUB_REPO = "EFL_NEXUS"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _index_dir(root: Path) -> dict:
    """Return {relative_posix_path: sha256} for every file under *root*."""
    index = {}
    root = root.resolve()
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            index[rel] = _sha256(p)
    return index


def _extract_zip_to_temp(zip_path: Path):
    """
    Extract *zip_path* into a temporary directory.
    If the ZIP has a single top-level folder (e.g. EFL_NEXUS/) the function
    descends into it automatically, matching what the updater does.

    Returns (tmp_root_dir, actual_content_dir) -- caller must clean up tmp_root_dir.
    """
    tmp = Path(tempfile.mkdtemp(prefix="efl_patch_prev_"))
    print(f"  Extracting baseline ZIP to {tmp} ...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(tmp)

    entries = list(tmp.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        # Single top-level folder -- treat its contents as the root
        content_dir = entries[0]
    else:
        content_dir = tmp

    return tmp, content_dir


def _download_github_baseline(version: str, target_dir: Path, repo_user: str = GITHUB_USER, repo_name: str = GITHUB_REPO):
    """
    Query GitHub Releases for the repo and download the full release ZIP for *version*
    (or the latest full release if same-version is not found).
    """
    if not requests:
        print("  [INFO] 'requests' library not available; skipping GitHub baseline download.")
        return None

    clean_ver = version.lstrip("v")
    api_url = f"https://api.github.com/repos/{repo_user}/{repo_name}/releases"
    headers = {"User-Agent": "EFL-Nexus-Patch-Generator"}

    print(f"  Querying GitHub releases for baseline ({repo_user}/{repo_name}) ...")
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        releases = resp.json()
    except Exception as exc:
        print(f"  [WARNING] Could not query GitHub releases: {exc}")
        return None

    target_asset = None
    target_tag = ""

    # Priority 1: Full release ZIP matching clean_ver
    for rel in releases:
        tag = rel.get("tag_name", "").strip().lstrip("v")
        assets = rel.get("assets", [])
        for asset in assets:
            name = asset.get("name", "")
            if name.lower().endswith(".zip") and "patch" not in name.lower():
                if tag == clean_ver or name == f"EFL_NEXUS_v{clean_ver}.zip":
                    target_asset = asset
                    target_tag = tag
                    break
        if target_asset:
            break

    # Priority 2: Latest full release ZIP of any version
    if not target_asset and releases:
        for rel in releases:
            tag = rel.get("tag_name", "").strip().lstrip("v")
            assets = rel.get("assets", [])
            for asset in assets:
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

    print(f"  Found remote baseline: {asset_name} (Release v{target_tag}, {asset_size / (1024*1024):.2f} MB)")
    print(f"  Downloading baseline to {out_path} ...")

    try:
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
                            print(f"\r  Progress: {pct:5.1f}% ({downloaded / (1024*1024):.1f} MB)", end="", flush=True)
            print()
        print(f"  [OK] Baseline downloaded successfully: {out_path.name}")
        return out_path
    except Exception as exc:
        print(f"\n  [ERROR] Failed to download baseline from GitHub: {exc}")
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        return None


def _find_prev_zip(search_dir: Path, new_version: str):
    """
    Scan *search_dir* for the best baseline full-release ZIP for *new_version*.

    Priority:
      1. Full-release ZIP for *new_version* itself (EFL_NEXUS_v<ver>.zip)
      2. Most recent full-release ZIP for any other version (EFL_NEXUS_v<other>.zip)
      3. If none found, automatically download from GitHub releases into *search_dir*.
    """
    clean_ver = new_version.lstrip("v")

    # -- collect full-release ZIPs in search_dir -----------------------------
    full_pattern = re.compile(r"EFL_NEXUS_v([\d.]+)\.zip$", re.IGNORECASE)
    same_ver_full = None
    other_ver_candidates = []

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

    # -- fallback to GitHub release download --------------------------------
    print(f"  No baseline ZIP found in {search_dir}. Attempting download from GitHub...")
    downloaded = _download_github_baseline(clean_ver, search_dir)
    if downloaded and downloaded.exists():
        return downloaded

    return None


def _read_build_from_dir(dist_dir: Path) -> int:
    """Read build number from build.txt in *dist_dir* or repo root. Returns 0 if missing."""
    build_file = dist_dir / "build.txt"
    if not build_file.exists():
        build_file = Path("build.txt")
    if build_file.exists():
        try:
            return int(build_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pass
    return 0


def _read_version_from_dir(dist_dir: Path):
    """Try to read version.txt from the dist directory or repo root."""
    for loc in [dist_dir / "version.txt", Path("version.txt")]:
        if loc.exists():
            v = loc.read_text(encoding="utf-8").strip()
            if v:
                return v
    return None


def _write_build_txt(tmp_dir: Path, build: int) -> Path:
    """Write a temporary build.txt file and return its path."""
    build_file = tmp_dir / "build.txt"
    build_file.write_text(str(build), encoding="utf-8")
    return build_file


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def compute_changed_files(new_dir: Path, prev_dir: Path) -> list:
    """
    Compare *new_dir* against *prev_dir* using SHA-256 hashes.

    Returns a list of (relative_posix_path, absolute_new_path) for every file
    that is *new* or *modified* in new_dir. Files only in prev_dir (deletions)
    are intentionally ignored -- the updater merges without deleting.
    """
    print("  Indexing new build ...")
    new_index = _index_dir(new_dir)
    print(f"    -> {len(new_index):,} files in new build")

    print("  Indexing baseline ...")
    prev_index = _index_dir(prev_dir)
    print(f"    -> {len(prev_index):,} files in baseline")

    changed = []
    for rel, new_hash in new_index.items():
        if rel == "build.txt":
            continue  # handled separately
        prev_hash = prev_index.get(rel)
        if prev_hash is None:
            changed.append((rel, new_dir / rel.replace("/", os.sep)))
        elif new_hash != prev_hash:
            changed.append((rel, new_dir / rel.replace("/", os.sep)))

    # Always ensure version.txt is present even if unhashed the same
    ver_rel = "version.txt"
    if not any(r == ver_rel for r, _ in changed):
        ver_abs = new_dir / "version.txt"
        if ver_abs.exists():
            changed.append((ver_rel, ver_abs))

    return changed


def build_patch_zip(
    new_dir: Path,
    prev_dir: Path,
    output_zip: Path,
    version: str,
    build: int,
    is_hotfix: bool = False,
) -> None:
    """Build the patch ZIP and write a summary to stdout."""
    changed = compute_changed_files(new_dir, prev_dir)

    if not changed and not is_hotfix:
        print("\nWARNING: No changed files detected -- patch would be empty.")
        print("Are you diffing the same build twice?")
        sys.exit(1)

    if not changed and is_hotfix:
        print("\nWARNING: No changed files detected between builds.")
        print("The patch will only contain version.txt and build.txt.")

    # Sort for deterministic output
    changed.sort(key=lambda t: t[0])

    print(f"\n  Build number   : {build}")
    print(f"  Building patch ZIP -> {output_zip}")

    # Write build.txt into a temp file so we can inject it into the ZIP
    tmp_build_dir = Path(tempfile.mkdtemp(prefix="efl_build_txt_"))
    try:
        build_txt_path = _write_build_txt(tmp_build_dir, build)

        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel, abs_path in changed:
                zf.write(abs_path, arcname=rel)
            # Always inject the authoritative build.txt last
            zf.write(build_txt_path, arcname="build.txt")
    finally:
        shutil.rmtree(tmp_build_dir, ignore_errors=True)

    # Summary
    patch_size_mb = output_zip.stat().st_size / (1024 * 1024)
    new_total_mb = sum(
        p.stat().st_size for p in new_dir.rglob("*") if p.is_file()
    ) / (1024 * 1024)

    label = f"v{version} build {build}" + (" [HOTFIX]" if is_hotfix else "")
    print("\n" + "=" * 60)
    print(f"  EFL_Nexus Patch  {label}")
    print("=" * 60)
    print(f"  Changed files  : {len(changed)} + build.txt")
    print(f"  Patch ZIP size : {patch_size_mb:.2f} MB")
    print(f"  Full build size: {new_total_mb:.2f} MB  "
          f"(patch is {patch_size_mb / new_total_mb * 100:.1f}% of full)")
    print()

    # Per-file breakdown (top 20 by compressed size)
    with zipfile.ZipFile(output_zip, "r") as zf:
        infos = sorted(zf.infolist(), key=lambda i: i.compress_size, reverse=True)
        print(f"  {'File':<60}  {'Compressed':>10}  {'Original':>10}")
        print(f"  {'-'*60}  {'-'*10}  {'-'*10}")
        for info in infos[:20]:
            c = info.compress_size / 1024
            u = info.file_size / 1024
            print(f"  {info.filename:<60}  {c:>8.1f}KB  {u:>8.1f}KB")
        if len(infos) > 20:
            print(f"  ... and {len(infos) - 20} more files")

    print("=" * 60)
    print(f"\nPatch created: {output_zip.resolve()}")
    if is_hotfix:
        print(
            f"\n  Add this file to the EXISTING v{version} GitHub Release:\n"
            f"    * {output_zip.name}\n"
            "  No new release tag or version bump required."
        )
    else:
        print(
            "\n  Upload BOTH files to your GitHub Release:\n"
            f"    * {output_zip.name}  <- patch (preferred by updater)\n"
            f"    * EFL_NEXUS_v{version}.zip  <- full fallback"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a differential patch ZIP for EFL_Nexus.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--new-dir", default=r"dist\EFL_NEXUS",
        help="Path to the newly compiled dist/EFL_NEXUS directory. "
             r"Default: dist\EFL_NEXUS",
    )
    parser.add_argument(
        "--version",
        help="New version string (e.g. 1.0.5). "
             "If omitted, read from --new-dir/version.txt or version.txt.",
    )
    parser.add_argument(
        "--build", type=int, default=None,
        help="Build number to embed in the patch (written to build.txt inside "
             "the ZIP). If omitted, auto-detected from build.txt.",
    )

    # Baseline source -- mutually exclusive
    baseline = parser.add_mutually_exclusive_group(required=True)
    baseline.add_argument(
        "--prev-dir",
        help="Path to the extracted previous release directory to diff against.",
    )
    baseline.add_argument(
        "--prev-zip",
        help="Path to a previous full-release ZIP to unpack and diff against.",
    )
    baseline.add_argument(
        "--auto-find-prev",
        metavar="SEARCH_DIR",
        help="Scan SEARCH_DIR for the best baseline ZIP and use it automatically. "
             "Falls back to downloading from GitHub Releases if not found locally.",
    )

    parser.add_argument(
        "--output-dir", default="dist",
        help="Directory to write the patch ZIP into. Default: dist",
    )

    args = parser.parse_args()

    new_dir = Path(args.new_dir).resolve()
    if not new_dir.is_dir():
        parser.error(f"--new-dir does not exist or is not a directory: {new_dir}")

    # Resolve version
    version = args.version
    if not version:
        version = _read_version_from_dir(new_dir)
    if not version:
        parser.error(
            "Could not determine version. Pass --version or ensure "
            "version.txt is present."
        )
    version = version.lstrip("v").strip()

    # Resolve build number
    if args.build is not None:
        build = args.build
    else:
        build = _read_build_from_dir(new_dir)

    print(f"\nBuilding patch for v{version} build {build}")
    print(f"  New build dir : {new_dir}")

    # Resolve baseline
    tmp_to_clean = None

    if args.prev_dir:
        prev_dir = Path(args.prev_dir).resolve()
        if not prev_dir.is_dir():
            parser.error(f"--prev-dir does not exist: {prev_dir}")
        print(f"  Baseline dir  : {prev_dir}")
        prev_zip_name = ""

    elif args.prev_zip:
        prev_zip = Path(args.prev_zip).resolve()
        if not prev_zip.is_file():
            parser.error(f"--prev-zip does not exist: {prev_zip}")
        print(f"  Baseline ZIP  : {prev_zip}")
        tmp_to_clean, prev_dir = _extract_zip_to_temp(prev_zip)
        prev_zip_name = prev_zip.name

    else:  # --auto-find-prev
        search_dir = Path(args.auto_find_prev).resolve()
        if not search_dir.is_dir():
            parser.error(f"--auto-find-prev directory does not exist: {search_dir}")
        prev_zip = _find_prev_zip(search_dir, version)
        if prev_zip is None:
            print(
                f"\nWARNING: No baseline ZIP found in {search_dir} or on GitHub.\n"
                "   Run the full build at least once first, or use\n"
                "   --prev-dir / --prev-zip to specify the baseline manually."
            )
            sys.exit(1)
        print(f"  Baseline ZIP  : {prev_zip}")
        tmp_to_clean, prev_dir = _extract_zip_to_temp(prev_zip)
        prev_zip_name = prev_zip.name

    # Detect hotfix: same version
    is_hotfix = version in prev_zip_name or build > 0

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_zip = output_dir / f"EFL_Nexus_Patch_v{version}_b{build}.zip"

    try:
        build_patch_zip(new_dir, prev_dir, output_zip, version, build, is_hotfix)
    finally:
        if tmp_to_clean and tmp_to_clean.exists():
            shutil.rmtree(tmp_to_clean, ignore_errors=True)


if __name__ == "__main__":
    main()
