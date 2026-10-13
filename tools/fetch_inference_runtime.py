"""Fetch the SHA-256-pinned Windows llama.cpp CUDA runtime into the project."""

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.download_pinned_asset import download  # noqa: E402


def main():
    assets = json.loads((ROOT / "packaging/inference-runtime.lock.json").read_text(encoding="utf-8"))
    destination = ROOT / "vendor/llama"
    destination.mkdir(parents=True, exist_ok=True)
    cache = ROOT / ".cache/inference"
    cache.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        if asset.get("files") and all(
            (destination / f["name"]).is_file()
            and (destination / f["name"]).stat().st_size == f["size"]
            and hashlib.file_digest((destination / f["name"]).open("rb"), "sha256").hexdigest() == f["sha256"]
            for f in asset["files"]
        ):
            print("Verified local CUDA redistributables:", asset["id"], flush=True)
            continue
        archive = download(asset["url"], asset["size"], asset["sha256"], cache / asset["filename"])
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != asset["sha256"]:
            raise ValueError("Inference runtime checksum mismatch: " + asset["id"])
        if asset["id"] == "transcribe-cuda":
            continue  # Installed into the isolated environment by setup_inference.py.
        target = ROOT / "vendor/cuda12" if asset["id"].startswith("cuda12") else destination
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                name = Path(member.filename).name
                if not name or member.is_dir():
                    continue
                if name.endswith((".dll", ".exe", ".txt", ".md")):
                    with source.open(member) as data, (target / name).open("wb") as output:
                        shutil.copyfileobj(data, output)
        print("Verified runtime:", asset["id"], flush=True)


if __name__ == "__main__":
    main()
