"""Parallel, hash-verified fixture downloads into the isolated test library only."""

import argparse
import os
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.download_pinned_asset import download  # noqa: E402
from videodock.caption_models import (  # noqa: E402
    download_model,
    is_ready,
    model_lock,
    model_spec,
    verify_file,
    verify_model,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    args = parser.parse_args()
    spec = model_spec(args.model)
    root = ROOT / ".test-artifacts/model-resources/source/models"
    if is_ready(root, spec):
        verify_model(root, spec, threading.Event())
        print("Verified cached model:", spec["id"], flush=True)
        return
    stage = root / ".staging" / spec["id"] / spec["revision"]
    stage.mkdir(parents=True, exist_ok=True)
    cancel = threading.Event()
    with model_lock(root, spec):
        for entry in spec["files"]:
            target = stage / entry["name"]
            if verify_file(target, entry, cancel):
                continue
            partial = target.with_name(target.name + ".part")
            if partial.is_file() and partial.stat().st_size < entry["size"]:
                parts = target.with_name(target.name + ".parts")
                parts.mkdir(exist_ok=True)
                with partial.open("rb") as source:
                    for index in range(partial.stat().st_size // (4 * 1024**2)):
                        seed = parts / str(index)
                        data = source.read(4 * 1024**2)
                        if not seed.is_file():
                            seed.write_bytes(data)
            elif verify_file(partial, entry, cancel):
                os.replace(partial, target)
                continue
            url = f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}/{entry['name']}"
            download(url, entry["size"], entry["sha256"], target, workers=16)
            partial.unlink(missing_ok=True)
            parts = target.with_name(target.name + ".parts").resolve()
            if not parts.is_relative_to(stage.resolve()):
                raise ValueError("Invalid test staging directory")
            if parts.is_dir():
                shutil.rmtree(parts)
    # The production downloader performs the final complete-package verification/publication.
    download_model(root, spec["id"], cancel, print)


if __name__ == "__main__":
    main()
