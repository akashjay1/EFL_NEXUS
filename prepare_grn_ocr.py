"""Prepare the pinned, portable upstream Windows OCR runtime; installs no software.

Downloads are verified before 7-Zip extracts the upstream NSIS payload. The MSI
administrative extraction supplies the build tool only; it is not shipped.
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import importlib.metadata
import io
import tarfile
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "build" / "grn-validation"
TARGET = ROOT / "assets" / "grn_ocr"
TESSERACT_URL = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe"
TESSERACT_SHA = "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4"
SEVENZIP_URL = "https://github.com/ip7z/7zip/releases/download/26.04/7z2604-x64.msi"
SEVENZIP_SHA = "0b01334a418654293513449f61d6bfc99e5196ca371e3c3dc961eda57cd535c6"
MODEL_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
MODEL_SHA = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"


def runtime_dependency_notices():
    """Retain MSYS2 distributors' notices and provenance for the native DLLs.

    These are license/documentation files only. Runtime binaries always come
    from the checksum-pinned upstream Tesseract installer above.
    """
    import zstandard
    repo = "https://repo.msys2.org/mingw/mingw64/"
    database = TOOLS / "mingw64.db"
    download(repo + "mingw64.db", database)
    index = {}
    with zstandard.ZstdDecompressor().stream_reader(database.open("rb")) as stream:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                if member.name.endswith("/desc"):
                    text = archive.extractfile(member).read().decode("utf-8")
                    fields = {}
                    for block in text.strip().split("\n\n"):
                        lines = block.splitlines()
                        fields[lines[0].strip("%")] = "\n".join(lines[1:])
                    index[fields["NAME"]] = fields
    names = ("libarchive", "libb2", "brotli", "bzip2", "curl", "libdeflate", "expat", "gcc-libs", "libgcc", "libstdc++",
             "giflib", "libiconv", "libidn2", "gettext-runtime", "jbigkit", "libjpeg-turbo", "leptonica",
             "lerc", "lz4", "xz", "openjpeg2", "libpng", "libpsl", "libwebp", "libssh2", "libtiff",
             "libunistring", "zstd", "zlib", "winpthreads")

    def collect(name):
        key = "mingw-w64-x86_64-" + name
        if key not in index:
            raise RuntimeError(f"MSYS2 notice package not found: {key}")
        fields = index[key]
        path = TOOLS / "notice-packages" / fields["FILENAME"]
        download(repo + fields["FILENAME"], path, fields["SHA256SUM"])
        count = 0
        with zstandard.ZstdDecompressor().stream_reader(path.open("rb")) as stream:
            with tarfile.open(fileobj=stream, mode="r|") as archive:
                for member in archive:
                    if member.isfile() and "/share/licenses/" in member.name:
                        # Archive content cannot choose a destination outside notices.
                        relative = Path(member.name.split("/share/licenses/", 1)[1])
                        if relative.is_absolute() or ".." in relative.parts:
                            raise RuntimeError("Unsafe license archive path")
                        target = TARGET / "notices" / "native-dependencies" / name / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.extractfile(member).read())
                        count += 1
        return {"package": key, "filename": fields["FILENAME"], "sha256": fields["SHA256SUM"],
                "license": fields.get("LICENSE", ""), "upstream": fields.get("URL", ""),
                "source_recipe": "https://github.com/msys2/MINGW-packages/tree/master/" + fields["BASE"],
                "notice_files": count}

    with ThreadPoolExecutor(max_workers=4) as pool:
        inventory = list(pool.map(collect, names))
    (TARGET / "notices" / "native-dependency-provenance.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    # Some MSYS2 packages omit notice text; retain it from the upstream source.
    for component, url, digest in (
        ("giflib", "https://downloads.sourceforge.net/project/giflib/giflib-5.x/giflib-5.2.2.tar.gz", "be7ffbd057cadebe2aa144542fd90c6838c6a083b5e8a9048b8ee3b66b29d5fb"),
        ("libidn2", "https://ftp.gnu.org/gnu/libidn/libidn2-2.3.8.tar.gz", "f557911bf6171621e1f72ff35f5b1825bb35b52ed45325dcdee931e5d3c0787a"),
    ):
        source = TOOLS / "notice-packages" / (component + "-source.tar.gz")
        download(url, source, digest)
        with tarfile.open(source) as archive:
            for member in archive:
                name = Path(member.name).name
                if member.isfile() and (name.startswith("COPYING") or name in ("LICENSE", "AUTHORS")):
                    relative = Path(*Path(member.name).parts[1:])
                    if relative.is_absolute() or ".." in relative.parts:
                        raise RuntimeError("Unsafe source notice path")
                    target = TARGET / "notices" / "native-dependencies" / component / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
    download("https://raw.githubusercontent.com/lz4/lz4/v1.10.0/lib/LICENSE", TARGET / "notices" / "native-dependencies" / "lz4" / "LICENSE")
    print("Native dependency notices:", len(inventory), "packages", flush=True)


def download(url, path, digest=None):
    if path.exists() and (digest is None or hashlib.sha256(path.read_bytes()).hexdigest() == digest):
        return
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    if digest and hashlib.sha256(response.content).hexdigest() != digest:
        raise RuntimeError(f"Checksum mismatch: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)


def prepare():
    import pefile
    TOOLS.mkdir(parents=True, exist_ok=True)
    download(TESSERACT_URL, TOOLS / "tesseract-installer.exe", TESSERACT_SHA)
    extracted = TOOLS / "tesseract-extracted"
    if not (extracted / "tesseract.exe").exists():
        download(SEVENZIP_URL, TOOLS / "7zip.msi", SEVENZIP_SHA)
        tool = TOOLS / "7zip" / "Files" / "7-Zip" / "7z.exe"
        if not tool.exists():
            subprocess.run(["msiexec", "/a", str(TOOLS / "7zip.msi"), "/qn", "TARGETDIR=" + str(TOOLS / "7zip")], check=True, timeout=90)
        subprocess.run([str(tool), "x", str(TOOLS / "tesseract-installer.exe"), "-o" + str(extracted), "-y", "-bso0"], check=True, timeout=90)
    TARGET.mkdir(parents=True, exist_ok=True)
    pending, seen = ["tesseract.exe"], set()
    while pending:
        name = pending.pop()
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        source = extracted / name
        destination = TARGET / source.name
        if not destination.exists() or hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
            shutil.copy2(source, destination)
        with pefile.PE(str(source)) as executable:
            pending.extend(entry.dll.decode() for entry in getattr(executable, "DIRECTORY_ENTRY_IMPORT", [])
                           if (extracted / entry.dll.decode()).exists())
    shutil.copytree(extracted / "tessdata" / "configs", TARGET / "tessdata" / "configs", dirs_exist_ok=True)
    shutil.copytree(extracted / "doc", TARGET / "notices" / "tesseract", dirs_exist_ok=True)
    download(f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{MODEL_COMMIT}/eng.traineddata", TARGET / "tessdata" / "eng.traineddata", MODEL_SHA)
    download(f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{MODEL_COMMIT}/LICENSE", TARGET / "notices" / "tessdata-LICENSE")
    # Keep the distributors' license files with their corresponding binary packages.
    # The native runtime's component/source inventory is also retained for inspection.
    download("https://raw.githubusercontent.com/DanBloomberg/leptonica/1.87.0/leptonica-license.txt", TARGET / "notices" / "leptonica-LICENSE")
    for package in ("zxing-cpp", "opencv-python-headless", "numpy"):
        dist = importlib.metadata.distribution(package)
        for entry in dist.files or []:
            if ".dist-info/" in str(entry) and any(word in str(entry).lower() for word in ("license", "copying", "notice")):
                dest = TARGET / "notices" / package / str(entry).split(".dist-info/", 1)[1]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(entry), dest)
    runtime_dependency_notices()
    manifest = {"tesseract_url": TESSERACT_URL, "tesseract_sha256": TESSERACT_SHA,
                "model_commit": MODEL_COMMIT, "model_sha256": MODEL_SHA,
                "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in TARGET.iterdir() if p.is_file()}}
    (TARGET / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(subprocess.check_output([str(TARGET / "tesseract.exe"), "--version"], text=True).splitlines()[0])
    subprocess.run([str(TARGET / "tesseract.exe"), "--tessdata-dir", str(TARGET / "tessdata"), "--list-langs"], check=True)


if __name__ == "__main__":
    prepare()
