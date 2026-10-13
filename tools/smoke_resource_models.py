"""Validate pinned sources and opt in to one real, isolated download/resume check."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def validate_source(spec):
    repo, revision = spec["repository"], spec["revision"]
    with urlopen(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true", timeout=40) as response:
        info = json.load(response)
    assert info["sha"] == revision
    remote = {file["rfilename"]: file for file in info["siblings"]}
    weights = []
    for file in spec["files"]:
        item = remote[file["name"]]
        assert item["size"] == file["size"], file
        if item.get("lfs"):
            assert item["lfs"]["sha256"] == file["sha256"], file
        if file["name"].endswith((".gguf", ".safetensors")):
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{file['name']}"
            with urlopen(Request(url, method="HEAD"), timeout=40) as response:
                assert response.status == 200
                length = response.headers.get("Content-Length")
                assert not length or int(length) == file["size"], (file, length)
            weights.append(file["name"])
    return {"id": spec["id"], "revision": revision, "bytes": spec["bytes"], "reachable_weights": weights}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-sources", action="store_true", help="Check pinned public metadata and weight URLs.")
    parser.add_argument("--download", action="store_true", help="Explicitly download one isolated test package.")
    parser.add_argument("--packaged", action="store_true", help="Use the release's bundled download worker.")
    parser.add_argument("--seed-from-source", action="store_true",
                        help="Seed packaged partial files from verified source bytes, leaving 64 MiB per weight.")
    parser.add_argument("--model", default="index-translate-2b-q4-k-m")
    args = parser.parse_args()
    output = ROOT / ".test-artifacts" / "model-resources"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["VIDEODOCK_DATA_DIR"] = str(output / "appdata")
    from videodock import __version__
    from videodock import controller as controller_module
    from videodock.caption_models import catalog, is_ready, model_spec, verify_model

    if args.check_sources:
        with ThreadPoolExecutor(max_workers=4) as pool:
            report = list(pool.map(validate_source, [spec for spec in catalog() if spec.get("format")]))
        (output / "sources.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Verified all {len(report)} pinned packages and their weight download URLs.", flush=True)
    if not args.download:
        return
    if args.packaged:
        worker = ROOT / "dist" / f"VideoDock-{__version__}" / "_internal" / "vendor" / "VideoDockWorker.exe"
        assert worker.is_file(), worker
        controller_module.worker_command = lambda: [str(worker)]

    from PySide6.QtWidgets import QApplication

    from videodock.caption_ui import ModelManager
    from videodock.controller import QueueController
    from videodock.store import Store

    app = QApplication([])
    # Each mode gets its own installation so the packaged smoke exercises publication too.
    mode = "packaged" if args.packaged else "source"
    models = output / mode / "models"
    print(f"Starting {mode} smoke, PID {os.getpid()}", flush=True)
    store = Store(output / mode / "queue.sqlite3")
    store.set_preference("model_folder", str(models))
    controller = QueueController(store)
    manager = ModelManager(store, controller, lambda _: None)
    spec = model_spec(args.model)
    assert spec.get("format"), "Choose an additional model package."
    if args.seed_from_source and not is_ready(models, spec):
        assert args.packaged, "Seeding is only supported for the packaged resume smoke."
        source = verify_model(output / "source" / "models", spec, threading.Event())
        stage = models / ".staging" / spec["id"] / spec["revision"]
        stage.mkdir(parents=True, exist_ok=True)
        for file in spec["files"]:
            partial = file["name"].endswith((".gguf", ".safetensors"))
            target = stage / (file["name"] + ".part" if partial else file["name"])
            shutil.copyfile(source / file["name"], target)
            if partial:
                with target.open("r+b") as handle:
                    handle.truncate(max(0, file["size"] - 64 * 1024**2))
        print("Seeded verified source bytes; packaged worker must download and verify the remainder.", flush=True)
    interrupted = False
    events = []
    last_print = 0.0

    def wait(condition, timeout=600):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert condition(), "Resource model smoke timed out."

    def progress():
        nonlocal interrupted, last_print
        state = controller.model_states.get(spec["id"], {})
        if state.get("model_id") or state.get("message"):
            events.append(dict(state))
        if time.monotonic() - last_print > 10 or state.get("message"):
            last_print = time.monotonic()
            print(state, flush=True)
        if not interrupted and state.get("state") == "Downloading…" and state.get("bytes", 0) > 1024**2:
            interrupted = True
            controller.cancel_model_download(spec["id"])

    try:
        if not is_ready(models, spec):
            controller.models_changed.connect(progress)
            manager.controls[spec["id"]][2].click()
            wait(lambda: not controller.model_workers)
            controller.models_changed.disconnect(progress)
            assert interrupted, controller.model_states
            assert not is_ready(models, spec)
            partials = list((models / ".staging" / spec["id"]).glob("**/*.part"))
            assert partials and sum(file.stat().st_size for file in partials) > 0
            partial_bytes = sum(file.stat().st_size for file in partials)
            print(f"Cancelled with {partial_bytes:,} partial bytes; resuming {mode} download…", flush=True)
            # Keep logging on resume without issuing a second cancellation.
            controller.models_changed.connect(progress)
            manager.controls[spec["id"]][2].click()
            wait(lambda: not controller.model_workers)
            controller.models_changed.disconnect(progress)
            assert is_ready(models, spec), controller.model_states
        verified = verify_model(models, spec, threading.Event())
        manager.refresh()
        assert manager.controls[spec["id"]][5].isEnabled()
        assert manager.controls[spec["id"]][7].isEnabled()
        report = {"id": spec["id"], "mode": mode, "bytes": spec["bytes"],
                  "interrupted": interrupted, "seeded_from_source": args.seed_from_source,
                  "verified_path": str(verified), "usable": True, "events": events[-20:]}
        (output / f"{mode}-download.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Verified {mode} GUI download, cancellation/resume, full checksums and installed Use control.", flush=True)
    finally:
        manager.close()
        controller.shutdown()
        wait(lambda: not controller.model_workers)
        store.close()


if __name__ == "__main__":
    main()
