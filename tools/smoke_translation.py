"""Opt-in offline translation acceptance using the isolated cached model library."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--packaged", action="store_true")
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["HF_HUB_OFFLINE"] = "1"
    from PySide6.QtWidgets import QApplication

    from videodock.caption_models import is_ready, model_spec
    from videodock.captions import CaptionEngine
    from videodock.controller import QueueController
    from videodock.dependencies import find_binary, subprocess_flags
    from videodock.media import probe
    from videodock.models import DownloadSettings
    from videodock.store import Store

    output = ROOT / ".test-artifacts" / "translation"
    output.mkdir(parents=True, exist_ok=True)
    models = ROOT / ".test-artifacts" / "local-captions" / "models"
    app = QApplication.instance() or QApplication([])
    store = Store(output / "download-validation.sqlite3")
    store.set_preference("model_folder", str(models))
    controller = QueueController(store)
    controller.message.connect(lambda message: print(message, flush=True))

    def wait(condition, timeout=600):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert condition(), "Acceptance timed out"

    spec = model_spec("m2m100-418m")
    if args.download and not is_ready(models, spec):
        interrupted = False

        def interrupt():
            nonlocal interrupted
            state = controller.model_states.get(spec["id"], {})
            if not interrupted and state.get("bytes", 0) > 1024 * 1024:
                interrupted = True
                controller.cancel_model_download(spec["id"])

        controller.models_changed.connect(interrupt)
        print("Downloading translation model with cancellation/resume…", flush=True)
        controller.start_model_download(spec["id"])
        wait(lambda: not controller.model_workers)
        assert interrupted
        controller.models_changed.disconnect(interrupt)
        if not is_ready(models, spec):
            controller.start_model_download(spec["id"])
            wait(lambda: not controller.model_workers)
        assert is_ready(models, spec), controller.model_states
        print("Verified translation download, interruption and resume.", flush=True)
    if not is_ready(models, spec):
        raise ValueError("Run with --download to install the isolated test translation model.")
    controller.shutdown()
    wait(lambda: not controller.busy)
    store.close()
    source = ROOT / ".test-artifacts" / "local-captions" / "語音測試.mp4"
    assert source.is_file(), "Run tools/smoke_captions.py --download first."
    settings = DownloadSettings(
        caption_source="local",
        caption_mode="embed",
        caption_model="base",
        translate=True,
        target_languages=("zh-Hant", "ja"),
        default_language="zh-Hant",
        track_order=("en", "zh-Hant", "ja"),
        caption_device="cuda",
        cpu_fallback=True,
    )
    settings.validate()
    job = {
        "id": ("packaged-" if args.packaged else "source-") + uuid.uuid4().hex,
        "url": source.as_uri(),
        "media_path": str(source),
        "output": str(source),
        "destination": str(output / ("packaged" if args.packaged else "source")),
        "settings": settings.to_dict(),
    }
    summary = {}
    transcriptions = []
    if args.packaged:
        from videodock import __version__

        executable = (
            ROOT / "dist" / f"VideoDock-{__version__}" / "_internal" / "vendor" / "VideoDockWorker.exe"
        )
        proc = subprocess.Popen(
            [str(executable)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **subprocess_flags(),
        )

        def request(job):
            proc.stdin.write(
                (
                    json.dumps({"action": "caption_service", "job": job, "model_folder": str(models)}) + "\n"
                ).encode()
            )
            proc.stdin.flush()
            events = []
            # Keep stdin open across both inference requests (the Windows regression).
            for line in proc.stdout:
                event = json.loads(line)
                events.append(event)
                if event.get("status") == "transcribing":
                    transcriptions.append(job["id"])
                if event["type"] in {"warning", "error", "completed"}:
                    print(event, flush=True)
                if event["type"] == "caption_idle":
                    break
            assert not any(event["type"] in {"error", "caption_waiting"} for event in events), events
            return next(event for event in events if event["type"] == "completed")

        first = request(job)
        job["settings"] = replace(
            settings, caption_mode="burn", bilingual_language="zh-Hant", burn_language="bilingual"
        ).to_dict()
        second = request(job)
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0, proc.stderr.read().decode("utf-8", "replace")
        result = first
        summary["burned"] = second["output"]
    else:
        engine = CaptionEngine()
        connect = socket.socket.connect
        socket.socket.connect = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Offline socket blocked")
        )
        events = []
        started = time.monotonic()
        try:
            engine.generate(job, models, threading.Event(), events.append)
            first = events[-1]
            assert first["caption_status"] == "complete", first
            job["settings"] = replace(
                settings, caption_mode="burn", bilingual_language="zh-Hant", burn_language="bilingual"
            ).to_dict()
            engine.generate(job, models, threading.Event(), events.append)
            second = events[-1]
            assert second["caption_status"] == "complete", second
        finally:
            socket.socket.connect = connect
        result = first
        transcriptions.extend(event for event in events if event.get("status") == "transcribing")
        summary.update(
            seconds=round(time.monotonic() - started, 2),
            burned=second["output"],
            warnings=[event["message"] for event in events if event["type"] == "warning"],
        )
    streams = [
        stream for stream in probe(Path(result["output"]))["streams"] if stream["codec_type"] == "subtitle"
    ]
    assert len(streams) == 3
    assert len(transcriptions) == 1, "Bilingual export must reuse one source transcription."
    assert [stream["disposition"]["default"] for stream in streams] == [0, 1, 0]
    translations = {}
    for track in result["tracks"]:
        if track["role"] == "target":
            translations[track["language"]] = json.loads(Path(track["cues_path"]).read_text(encoding="utf-8"))
    assert set(translations) == {"zh-Hant", "ja"}
    original = json.loads(Path(result["cues_path"]).read_text(encoding="utf-8"))
    for cues in translations.values():
        assert [(cue["id"], cue["start"], cue["end"]) for cue in cues] == [
            (cue["id"], cue["start"], cue["end"]) for cue in original
        ]
        assert any(any(ord(char) > 127 for char in cue["text"]) for cue in cues)
    for index, cues in enumerate([original, translations["zh-Hant"], translations["ja"]]):
        extracted = subprocess.run(
            [
                find_binary("ffmpeg"),
                "-v",
                "error",
                "-i",
                result["output"],
                "-map",
                f"0:s:{index}",
                "-f",
                "srt",
                "-",
            ],
            capture_output=True,
            check=True,
            **subprocess_flags(),
        ).stdout.decode("utf-8")
        assert all(cue["text"] in extracted for cue in cues), f"Track {index} did not round-trip."
    summary.update(
        tracks=len(streams), transcriptions=1, captions=result["caption_paths"], translated=translations
    )
    frame = output / ("packaged-burn.png" if args.packaged else "source-burn.png")
    subprocess.run(
        [
            find_binary("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-ss",
            "2",
            "-i",
            summary["burned"],
            "-frames:v",
            "1",
            str(frame),
        ],
        check=True,
        **subprocess_flags(),
    )
    target = output / ("packaged-result.json" if args.packaged else "source-result.json")
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Translation acceptance passed:", target, flush=True)


if __name__ == "__main__":
    main()
