from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .dependencies import data_directory, engine_command, subprocess_flags

API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
ASSETS = {"win32": "yt-dlp.exe", "darwin": "yt-dlp_macos", "linux": "yt-dlp_linux"}


def request(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(
            url, headers={"User-Agent": "VideoDock/0.1", "Accept": "application/vnd.github+json"}
        ),
        timeout=30,
    )


def check_update() -> dict:
    import platform

    if platform.machine().lower() not in {"amd64", "x86_64"} and sys.platform != "darwin":
        raise ValueError("Automatic engine updates currently support x64 Windows/Linux and universal macOS.")
    with request(API) as response:
        release = json.load(response)
    asset_name = ASSETS.get(sys.platform)
    asset = next((item for item in release.get("assets", []) if item["name"] == asset_name), None)
    if not asset:
        raise ValueError("No supported engine asset is available for this platform.")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError(
            "The release has no SHA-256 digest. Update was stopped because it cannot be verified."
        )
    result = subprocess.run(
        engine_command() + ["--version"], capture_output=True, text=True, timeout=15, **subprocess_flags()
    )
    return {
        "version": release["tag_name"],
        "current": result.stdout.strip(),
        "url": asset["browser_download_url"],
        "sha256": digest.removeprefix("sha256:"),
        "size": asset["size"],
        "name": asset_name,
    }


def install_update(release: dict) -> Path:
    parsed = urlparse(release["url"])
    expected_name = ASSETS.get(sys.platform)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or not parsed.path.startswith("/yt-dlp/yt-dlp/releases/download/")
        or release["name"] != expected_name
    ):
        raise ValueError("Only official yt-dlp release downloads are accepted.")
    if not re.fullmatch(r"[a-f0-9]{64}", release["sha256"]):
        raise ValueError("Invalid engine checksum.")
    root = data_directory() / "bin"
    root.mkdir(parents=True, exist_ok=True)
    target = root / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    temporary = root / (target.name + ".new")
    hasher = hashlib.sha256()
    size = 0
    try:
        with request(release["url"]) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > release["size"]:
                    raise ValueError("The engine download is larger than the official release asset.")
                output.write(chunk)
                hasher.update(chunk)
        if size != release["size"] or hasher.hexdigest() != release["sha256"]:
            raise ValueError("Engine checksum mismatch. The existing engine was kept.")
        if sys.platform != "win32":
            temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR)
        result = subprocess.run(
            [str(temporary), "--version"], capture_output=True, text=True, timeout=20, **subprocess_flags()
        )
        if result.returncode or result.stdout.strip() != release["version"]:
            raise ValueError("The downloaded engine did not pass its version check.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
