"""Real caption → translation handoff using isolated cached Base/M2M100 packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packaged", action="store_true")
    parser.add_argument("--auto-download", action="store_true", help="Run download → captions → translation with one start")
    parser.add_argument("--pause-download", action="store_true", help="Pause downloads after starting its active job")
    args = parser.parse_args()
    if args.pause_download and not args.auto_download:
        parser.error("--pause-download requires --auto-download")
    from videodock import __version__

    output = ROOT / ".test-artifacts/releases" / __version__ / ("stages-packaged" if args.packaged else "stages-source")
    if args.auto_download:
        output = output.with_name(output.name + "-auto")
    if args.pause_download:
        output = output.with_name(output.name + "-paused-download")
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
    server = None
    if args.auto_download:
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(output), **kwargs)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # ASCII URL avoids relying on implicit URL encoding in upstream download tools.
        (output / "speech.mp4").write_bytes(media.read_bytes())
        store.enqueue([{"url": f"http://127.0.0.1:{server.server_port}/speech.mp4", "title": "Automatic pipeline"}],
                      settings, str(output / "輸出"))
    else:
        store.queue_captions([str(media)], settings, str(output / "輸出"))
    identifier = store.jobs()[-1]["id"]
    c = controller.QueueController(store)
    events = []
    original = c._event
    source_hash = ""

    def event(job_id, value):
        nonlocal source_hash
        events.append(value)
        original(job_id, value)
        if value["type"] == "translation_ready":
            source_hash = hashlib.sha256(Path(value["cues_path"]).read_bytes()).hexdigest()

    c._event = event

    def wait(predicate, timeout=180):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        assert predicate(), store.get(identifier)

    try:
        paused = None
        if args.auto_download:
            c.set_auto_start("caption", True)
            c.set_auto_start("translation", True)
            c.start("download")
            if args.pause_download:
                c.pause("download")
        else:
            c.start("caption")
            wait(lambda: store.get(identifier)["status"] == "translation_queued" and c.caption_id is None)
            paused = store.get(identifier)
            assert paused["download_status"] == "skipped" and paused["caption_status"] == "complete"
            assert paused["translation_status"] == "queued"
            assert any(Path(p).is_file() for p in paused["caption_paths"])
            assert not any(e.get("status") == "translating" for e in events)
            c.start("translation")
        wait(lambda: store.get(identifier)["status"] in {"completed", "partial", "failed"} and c.caption_id is None)
        finished = store.get(identifier)
        assert finished["status"] == "completed", finished
        assert finished["download_status"] == ("complete" if args.auto_download else "skipped")
        assert finished["caption_status"] == "complete"
        assert finished["translation_status"] == "complete"
        assert sum(e.get("status") == "transcribing" for e in events) == 1
        assert source_hash and hashlib.sha256(Path(finished["cues_path"]).read_bytes()).hexdigest() == source_hash
        if args.auto_download:
            assert sum(e["type"] == "media_ready" for e in events) == 1
        if args.pause_download:
            assert not c.stage_running("download") and c.stage_running("translation")
        streams = [s for s in probe(Path(finished["output"]))["streams"] if s["codec_type"] == "subtitle"]
        assert len(streams) == 3 and [s["disposition"]["default"] for s in streams] == [0, 1, 0]
        (output / "report.json").write_text(json.dumps({"paused": paused, "finished": finished,
                                                       "auto_download": args.auto_download,
                                                       "download_paused": args.pause_download,
                                                       "transcriptions": 1, "subtitle_streams": len(streams)},
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
        print("Real automatic download pipeline passed." if args.auto_download else
              "Real stage handoff, translation pause/resume, source reuse and three embedded tracks passed.")
    finally:
        c.shutdown()
        wait(lambda: not c.busy, 30)
        store.close()
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    main()
