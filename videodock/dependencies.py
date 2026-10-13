from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def data_directory() -> Path:
    if os.environ.get("VIDEODOCK_DATA_DIR"):
        return Path(os.environ["VIDEODOCK_DATA_DIR"]).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "VideoDock"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VideoDock"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "videodock"


def resource_directory() -> Path:
    if os.environ.get("VIDEODOCK_RESOURCE_DIR"):
        return Path(os.environ["VIDEODOCK_RESOURCE_DIR"]).resolve()
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def find_binary(name: str) -> str | None:
    suffix = ".exe" if sys.platform == "win32" else ""
    for root in [data_directory() / "bin", resource_directory() / "vendor", Path(sys.executable).parent]:
        candidate = root / (name + suffix)
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def subprocess_flags() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def runtime() -> tuple[str, str] | None:
    for name, minimum in [("deno", (2, 3)), ("node", (22, 0))]:
        path = find_binary(name)
        if not path:
            continue
        try:
            import re

            result = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=5, **subprocess_flags()
            )
            match = re.search(r"(\d+)\.(\d+)", result.stdout)
            if match and tuple(map(int, match.groups())) >= minimum:
                return name, path
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def engine_command() -> list[str]:
    updated = find_binary("yt-dlp")
    if updated:
        return [updated]
    if getattr(sys, "frozen", False):
        raise RuntimeError("Bundled yt-dlp is missing. Reinstall VideoDock or use Check engine update.")
    return [sys.executable, "-m", "yt_dlp"]


def worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        suffix = ".exe" if sys.platform == "win32" else ""
        return [str(resource_directory() / "vendor" / ("VideoDockWorker" + suffix))]
    return [sys.executable, "-m", "videodock.worker"]


def dependency_report() -> dict[str, str]:
    result = {}
    # A packaged GUI keeps ML libraries in its console worker to avoid Qt DLL conflicts.
    if getattr(sys, "frozen", False):
        result["Local captions"] = (
            "Bundled faster-whisper / CTranslate2 / Silero VAD (CPU INT8; optional NVIDIA CUDA 12 + cuDNN 9)"
        )
    else:
        try:
            result["Local captions"] = (
                f"faster-whisper {version('faster-whisper')} / CTranslate2 {version('ctranslate2')}"
            )
        except PackageNotFoundError:
            result["Local captions"] = "Missing — install requirements.txt."
    for name in ["ffmpeg", "ffprobe"]:
        path = find_binary(name)
        result[name] = path or "Missing — place executable in vendor/ or install on PATH."
    js = runtime()
    result["JavaScript"] = f"{js[0]}: {js[1]}" if js else "Missing — install Deno 2.3+ or Node 22+."
    external = find_binary("yt-dlp")
    if external:
        result["yt-dlp"] = external
    else:
        try:
            result["yt-dlp"] = f"Python package {version('yt-dlp')}"
            result["EJS"] = version("yt-dlp-ejs")
        except PackageNotFoundError:
            result["yt-dlp / EJS"] = 'Missing — run pip install "yt-dlp[default]".'
    return result
