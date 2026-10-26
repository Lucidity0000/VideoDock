"""Real checkpoint/pause/resume through the source controller and chosen worker; no downloads or power actions."""

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

    output = ROOT / ".test-artifacts/releases" / __version__ / ("controls-packaged-worker" if args.packaged else "controls-source")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(QT_QPA_PLATFORM="offscreen", VIDEODOCK_DATA_DIR=str(output / "data"), HF_HUB_OFFLINE="1")
    from PySide6.QtWidgets import QApplication

    from videodock import controller
    from videodock.caption_models import is_ready, model_spec
    from videodock.dependencies import find_binary, subprocess_flags
    from videodock.models import DownloadSettings
    from videodock.store import Store

    models = ROOT / ".test-artifacts/local-captions/models"
    assert is_ready(models, model_spec("base")), "The isolated cached Base model is required; this smoke never downloads models."
    fixture = ROOT / ".test-artifacts/local-captions/speech.flac"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == "63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"
    if args.packaged:
        resources = ROOT / "dist" / f"VideoDock-{__version__}" / "_internal"
        os.environ["VIDEODOCK_RESOURCE_DIR"] = str(resources)
        controller.worker_command = lambda: [str(resources / "vendor/VideoDockWorker.exe")]
    source = output / "checkpoint-65s.wav"
    subprocess.run([find_binary("ffmpeg"), "-nostdin", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(fixture),
                    "-t", "65", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(source)],
                   check=True, timeout=30, **subprocess_flags())
    app = QApplication([])
    store = Store(output / "data/videodock.sqlite3")
    store.set_preference("model_folder", str(models))
    settings = DownloadSettings(caption_source="local", caption_mode="sidecar", caption_model="base", spoken_language="en")
    store.queue_captions([str(source)], settings, str(output / "subtitles"))
    identifier = store.jobs()[-1]["id"]
    c = controller.QueueController(store)
    events, pauses = [], []
    original = c._event

    def event(job_id, value):
        events.append(value)
        original(job_id, value)
        if value["type"] == "segment_checkpoint" and not pauses:
            pauses.append(True)
            c.pause_jobs([job_id])

    c._event = event

    def wait(predicate, timeout=180):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert predicate(), store.get(identifier)

    try:
        c.start("caption")
        wait(lambda: store.get(identifier)["status"] in {"paused", "failed"} and c.caption_id is None)
        paused = store.get(identifier)
        assert paused["status"] == "paused", paused
        checkpoint = output / "subtitles/.videodock-captions" / identifier / "transcription.json"
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        before = saved["segments"]
        assert 1 <= len(before) < 3
        c.pause("caption")
        c.resume_jobs([identifier])
        assert c.caption_id is None and store.get(identifier)["status"] == "caption_queued"
        c.start("caption")
        wait(lambda: store.get(identifier)["status"] in {"completed", "failed"} and c.caption_id is None)
        finished = store.get(identifier)
        assert finished["status"] == "completed", finished
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        assert len(saved["segments"]) == 3 and saved["segments"][:len(before)] == before
        assert any(value["type"] == "checkpoint_resume" for value in events)
        cues = json.loads(Path(finished["cues_path"]).read_text(encoding="utf-8"))
        assert cues and max(cue["end"] for cue in cues) > 60
        timeline = store.timeline(identifier)
        assert {"pause", "resume", "segment_checkpoint", "checkpoint_resume"} <= {value["kind"] for value in timeline}
        report = {"version": __version__, "packaged_worker": args.packaged, "controller": "source",
                  "duration": 65, "segments_before_pause": len(before), "segments_after_resume": len(saved["segments"]),
                  "completed_segments_preserved": True, "cues": len(cues), "last_cue_end": max(cue["end"] for cue in cues),
                  "timeline": timeline, "job": finished, "new_model_download": False, "power_action_executed": False}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Real 65-second Base transcription: individual pause/resume, durable segment reuse, sidecars and timeline passed.")
    finally:
        c.shutdown()
        wait(lambda: not c.busy, 30)
        store.close()


if __name__ == "__main__":
    main()
