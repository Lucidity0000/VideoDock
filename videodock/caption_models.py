from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

from filelock import FileLock, Timeout

from . import __version__
from .dependencies import data_directory
from .media import MIN_FREE, check_destination
from .processes import Cancelled


def catalog() -> list[dict]:
    return json.loads(Path(__file__).with_name("model_catalog.json").read_text(encoding="utf-8"))


def model_spec(model_id: str, revision: str = "") -> dict:
    spec = next((row for row in catalog() if row["id"] == model_id), None)
    if not spec or (revision and revision != spec["revision"]):
        raise ValueError("This model revision is not in the built-in catalog. Requeue with current settings.")
    return spec


def task_models(task: str, *, usable_only: bool = False) -> list[dict]:
    return [
        spec
        for spec in catalog()
        if spec.get("task", "speech") == task and (not usable_only or not spec.get("download_only", False))
    ]


def storage_folder(store) -> Path:
    return Path(store.preference("model_folder", str(data_directory() / "models"))).expanduser().resolve()


def model_path(root: Path, spec: dict) -> Path:
    return root / spec["id"] / spec["revision"]


def is_ready(root: Path, spec: dict) -> bool:
    path = model_path(root, spec)
    try:
        marker = json.loads((path / "ready.json").read_text(encoding="utf-8"))
        return marker == {"revision": spec["revision"], "files": spec["files"]} and all(
            (path / f["name"]).stat().st_size == f["size"] for f in spec["files"]
        )
    except (OSError, ValueError):
        return False


def check_cancel(cancel: threading.Event):
    if cancel.is_set():
        raise Cancelled()


def verify_file(path: Path, expected: dict, cancel: threading.Event) -> bool:
    if not path.is_file() or path.stat().st_size != expected["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest() == expected["sha256"]


@contextmanager
def model_lock(root: Path, spec: dict):
    folder = root / ".locks"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(folder / (spec["id"] + ".lock")), timeout=0):
            yield
    except Timeout as exc:
        raise ValueError("This model is in use or downloading. Wait for that operation to finish.") from exc


def verify_model(root: Path, spec: dict, cancel: threading.Event) -> Path:
    path = model_path(root, spec)
    if not is_ready(root, spec) or not all(verify_file(path / f["name"], f, cancel) for f in spec["files"]):
        raise ValueError("Model integrity check failed. Open Models and click Repair / retry.")
    return path


def download_model(root: Path, model_id: str, cancel: threading.Event, emit):
    spec = model_spec(model_id)
    with model_lock(root, spec):
        stage = root / ".staging" / spec["id"] / spec["revision"]
        stage.mkdir(parents=True, exist_ok=True)
        ready = model_path(root, spec)
        backup = ready.with_name(ready.name + ".old")
        if not ready.exists() and backup.exists():
            os.replace(backup, ready)
        completed = 0
        last_update = 0.0
        for entry in spec["files"]:
            check_cancel(cancel)
            target = stage / entry["name"]
            # Repair can reuse any intact installed files without downloading them again.
            installed = ready / entry["name"]
            if not target.exists() and verify_file(installed, entry, cancel):
                check_destination(root, entry["size"] + MIN_FREE)
                shutil.copyfile(installed, target)
            if verify_file(target, entry, cancel):
                completed += entry["size"]
                continue
            target.unlink(missing_ok=True)
            partial = target.with_name(target.name + ".part")
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > entry["size"]:
                partial.unlink()
                offset = 0
            if offset < entry["size"]:
                remaining = spec["bytes"] - completed - offset
                check_destination(root, remaining + MIN_FREE)
                url = (
                    f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}/{entry['name']}"
                )
                headers = {"User-Agent": f"VideoDock/{__version__}", "Accept-Encoding": "identity"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                with urlopen(Request(url, headers=headers), timeout=20) as response:
                    ranged = response.status == 206
                    if ranged and not response.headers.get("Content-Range", "").startswith(
                        f"bytes {offset}-"
                    ):
                        raise ValueError(
                            "The server returned an invalid resume range. Retry the model download."
                        )
                    if not ranged:
                        offset = 0
                    with partial.open("ab" if ranged else "wb") as output:
                        while True:
                            check_cancel(cancel)
                            block = response.read(256 * 1024)
                            if not block:
                                break
                            offset += len(block)
                            if offset > entry["size"]:
                                raise ValueError("Model download exceeded its pinned size.")
                            output.write(block)
                            if time.monotonic() - last_update > 0.2:
                                last_update = time.monotonic()
                                emit(
                                    {
                                        "type": "model_progress",
                                        "state": "Downloading…",
                                        "bytes": completed + offset,
                                        "total": spec["bytes"],
                                        "model_id": model_id,
                                    }
                                )
                                if shutil.disk_usage(root).free < MIN_FREE:
                                    raise ValueError(
                                        "Model storage is running out of disk space. Free space and retry."
                                    )
            emit(
                {
                    "type": "model_progress",
                    "state": "Verify",
                    "bytes": completed,
                    "total": spec["bytes"],
                    "model_id": model_id,
                }
            )
            if not verify_file(partial, entry, cancel):
                partial.unlink(missing_ok=True)
                raise ValueError(f"Integrity check failed for {entry['name']}. Retry to repair this file.")
            os.replace(partial, target)
            completed += entry["size"]
        check_cancel(cancel)
        (stage / "ready.json").write_text(
            json.dumps({"revision": spec["revision"], "files": spec["files"]}), encoding="utf-8"
        )
        ready.parent.mkdir(parents=True, exist_ok=True)
        # The marker becomes visible only after the complete verified directory is published.
        backup = ready.with_name(ready.name + ".old")
        if backup.exists():
            shutil.rmtree(backup)
        if ready.exists():
            os.replace(ready, backup)
        try:
            os.replace(stage, ready)
        except OSError:
            if backup.exists():
                os.replace(backup, ready)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        emit({"type": "model_ready", "model_id": model_id, "revision": spec["revision"], "path": str(ready)})


def remove_model(root: Path, model_id: str):
    spec = model_spec(model_id)
    with model_lock(root, spec):
        for candidate in [root / model_id, root / ".staging" / model_id]:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
                raise ValueError("Invalid model storage location.")
            if resolved.exists():
                shutil.rmtree(resolved)
