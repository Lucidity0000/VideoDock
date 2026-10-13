"""Real caption → translation handoff using isolated cached Base/M2M100 packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packaged", action="store_true")
    args = parser.parse_args()
    from videodock import __version__

    output = ROOT / ".test-artifacts/releases" / __version__ / ("stages-packaged" if args.packaged else "stages-source")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(QT_QPA_PLATFORM="offscreen", VIDEODOCK_DATA_DIR=str(output / "data"))
    from PySide6.QtWidgets import QApplication

    from videodock import controller
    from videodock.media import probe
    from videodock.models import DownloadSettings
    from videodock.store import Store

    if args.packaged:
        resources = ROOT / "dist" / f"VideoDock-{__version__}" / "_internal"
        os.environ["VIDEODOCK_RESOURCE_DIR"] = str(resources)
        controller.worker_command = lambda: [str(resources / "vendor/VideoDockWorker.exe")]
    else:
        resources = ROOT
    media = output / "字幕測試.mp4"
    subprocess.run([str(resources / "vendor/ffmpeg.exe"), "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=size=320x180:rate=15", "-i", str(ROOT / ".test-artifacts/local-captions/speech.flac"),
                    "-t", "11", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(media)], check=True)
    app = QApplication([])
    store = Store(output / "data/videodock.sqlite3")
    store.set_preference("model_folder", str(ROOT / ".test-artifacts/local-captions/models"))
    settings = DownloadSettings(caption_source="local", caption_mode="embed", caption_model="base",
                                spoken_language="en", caption_device="cpu", translate=True,
                                target_languages=("zh-Hant", "ja"), default_language="zh-Hant")
    store.queue_captions([str(media)], settings, str(output / "輸出"))
    identifier = store.jobs()[-1]["id"]
    c = controller.QueueController(store)
    events = []
    original = c._caption_event

    def event(value):
        events.append(value)
        original(value)

    c._caption_event = event

    def wait(predicate, timeout=180):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        assert predicate(), store.get(identifier)

    try:
        c.start("caption")
        wait(lambda: store.get(identifier)["status"] == "translation_queued" and c.caption_id is None)
        paused = store.get(identifier)
        assert paused["download_status"] == "skipped" and paused["caption_status"] == "complete"
        assert paused["translation_status"] == "queued"
        assert any(Path(p).is_file() for p in paused["caption_paths"])
        source_hash = hashlib.sha256(Path(paused["cues_path"]).read_bytes()).hexdigest()
        assert not any(e.get("status") == "translating" for e in events)
        c.start("translation")
        wait(lambda: store.get(identifier)["status"] in {"completed", "partial", "failed"} and c.caption_id is None)
        finished = store.get(identifier)
        assert finished["status"] == "completed", finished
        assert finished["download_status"] == "skipped" and finished["caption_status"] == "complete"
        assert finished["translation_status"] == "complete"
        assert sum(e.get("status") == "transcribing" for e in events) == 1
        assert hashlib.sha256(Path(finished["cues_path"]).read_bytes()).hexdigest() == source_hash
        streams = [s for s in probe(Path(finished["output"]))["streams"] if s["codec_type"] == "subtitle"]
        assert len(streams) == 3 and [s["disposition"]["default"] for s in streams] == [0, 1, 0]
        (output / "report.json").write_text(json.dumps({"paused": paused, "finished": finished,
                                                       "transcriptions": 1, "subtitle_streams": len(streams)},
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
        print("Real stage handoff, translation pause/resume, source reuse and three embedded tracks passed.")
    finally:
        c.shutdown()
        wait(lambda: not c.busy, 30)
        store.close()


if __name__ == "__main__":
    main()
