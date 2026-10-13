"""Explicit GPU validation download; uses only the isolated test model library."""

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from videodock.caption_models import catalog, download_model, is_ready


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", required=True)
    parser.add_argument("--models", nargs="*")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / ".test-artifacts/model-resources/source/models"
    specs = [
        spec for spec in catalog() if spec.get("format") and (not args.models or spec["id"] in args.models)
    ]
    cancel = threading.Event()

    def fetch(spec):
        if is_ready(root, spec):
            print("Cached:", spec["id"], flush=True)
            return
        last = -1

        def emit(event):
            nonlocal last
            step = int(event.get("bytes", 0) / spec["bytes"] * 10)
            if step > last or event["type"] == "model_ready":
                last = step
                print(spec["id"], event.get("state", event["type"]), step * 10, "%", flush=True)

        download_model(root, spec["id"], cancel, emit)

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(fetch, specs))
    except KeyboardInterrupt:
        cancel.set()
        raise


if __name__ == "__main__":
    main()
