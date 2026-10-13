"""Fetch verified Windows x64 tools, retaining a manifest for reproducible release builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
MANIFEST = ROOT / "packaging" / "dependencies.lock.json"


def fetch(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "VideoDock-build/0.1"}), timeout=60
    )


def release_asset(repository: str, name: str) -> dict:
    with fetch(f"https://api.github.com/repos/{repository}/releases/latest") as response:
        release = json.load(response)
    asset = next(item for item in release["assets"] if item["name"] == name)
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError(f"{repository} has no SHA-256 release digest; refusing unverified binaries.")
    return {"url": asset["browser_download_url"], "sha256": digest[7:], "version": release["tag_name"]}


def resolve() -> dict:
    ffmpeg_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    with fetch(ffmpeg_url + ".sha256") as response:
        checksum = response.read().decode().split()[0]
    with fetch(ffmpeg_url + ".ver") as response:
        ffmpeg_version = response.read().decode().strip()
    if not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise ValueError("FFmpeg checksum is missing or invalid.")
    return {
        "yt-dlp.exe": release_asset("yt-dlp/yt-dlp", "yt-dlp.exe"),
        "deno.zip": release_asset("denoland/deno", "deno-x86_64-pc-windows-msvc.zip"),
        "ffmpeg.zip": {
            "url": f"https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-{ffmpeg_version}-essentials_build.zip",
            "sha256": checksum,
            "version": ffmpeg_version,
        },
    }


def download_verified(name: str, asset: dict) -> Path:
    target = VENDOR / name
    if target.is_file():
        with target.open("rb") as existing:
            if hashlib.file_digest(existing, "sha256").hexdigest() == asset["sha256"]:
                return target
    temporary = target.with_suffix(target.suffix + ".download")
    print(f"Downloading {name} ({asset['version']})", flush=True)
    hasher = hashlib.sha256()
    try:
        with fetch(asset["url"]) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                hasher.update(chunk)
        if hasher.hexdigest() != asset["sha256"]:
            raise ValueError(f"{name} checksum mismatch. Nothing from this download was installed.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true", help="Resolve current releases and replace the lock manifest"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This bootstrap downloads Windows x64 tools. Use platform packages on macOS/Linux.")
    VENDOR.mkdir(exist_ok=True)
    manifest = resolve() if args.refresh or not MANIFEST.is_file() else json.loads(MANIFEST.read_text())
    MANIFEST.parent.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for name, asset in manifest.items():
        archive = download_verified(name, asset)
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zipped:
                # Extract only named tools/license files; never trust archive paths.
                for member in zipped.namelist():
                    basename = Path(member).name
                    if basename in {
                        "deno.exe",
                        "ffmpeg.exe",
                        "ffprobe.exe",
                        "LICENSE",
                        "LICENSE.txt",
                        "README.txt",
                    }:
                        target_name = basename if basename.endswith(".exe") else name[:-4] + "-" + basename
                        with zipped.open(member) as source, (VENDOR / target_name).open("wb") as output:
                            shutil.copyfileobj(source, output)
    print("Verified dependencies are ready in vendor/.", flush=True)


if __name__ == "__main__":
    main()
