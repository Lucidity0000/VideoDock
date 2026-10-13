"""Opt-in real Base-model acceptance check; never touches the user's model directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--packaged", action="store_true")
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["HF_HUB_OFFLINE"] = "1"
    output = ROOT / ".test-artifacts" / "local-captions"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["VIDEODOCK_DATA_DIR"] = str(output / ("packaged-data" if args.packaged else "source-data"))
    from PySide6.QtWidgets import QApplication

    from videodock import __version__
    from videodock.caption_models import is_ready, model_spec
    from videodock.controller import QueueController
    from videodock.dependencies import find_binary, subprocess_flags
    from videodock.models import DownloadSettings
    from videodock.store import Store

    app = QApplication([])
    models = output / "models"
    store = Store(output / "acceptance.sqlite3")
    store.set_preference("model_folder", str(models))
    controller = QueueController(store)
    controller.message.connect(lambda text: print(text, flush=True))

    def wait(condition, timeout=180):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert condition(), "Acceptance check timed out"

    spec = model_spec("base")
    if args.download and not is_ready(models, spec):
        interrupted = False

        def progress():
            nonlocal interrupted
            state = controller.model_states.get("base", {})
            if not interrupted and state.get("bytes", 0) > 1024 * 1024:
                interrupted = True
                controller.cancel_model_download("base")

        controller.models_changed.connect(progress)
        print("Downloading Base with one cancellation/resume through the GUI controller…", flush=True)
        controller.start_model_download("base")
        wait(lambda: not controller.model_workers)
        assert interrupted
        assert list(models.glob(".staging/**/*.part")) or is_ready(models, spec)
        controller.models_changed.disconnect(progress)
        if not is_ready(models, spec):
            controller.start_model_download("base")
            wait(lambda: not controller.model_workers)
        assert is_ready(models, spec), controller.model_states
        print("Model download, cancellation, resume and checksum verification passed.", flush=True)
    if not is_ready(models, spec):
        raise ValueError("Run with --download to install the test model.")
    speech = output / "speech.flac"
    if not speech.exists():
        from urllib.request import urlopen

        with urlopen(
            "https://raw.githubusercontent.com/openai/whisper/v20250625/tests/jfk.flac", timeout=30
        ) as response:
            speech.write_bytes(response.read())
    assert speech.stat().st_size > 1000, "Speech fixture is empty"
    assert (
        hashlib.sha256(speech.read_bytes()).hexdigest()
        == "63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"
    )
    media = output / "語音測試.mp4"
    subprocess.run(
        [
            find_binary("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=320x180:r=15",
            "-i",
            str(speech),
            "-t",
            "11",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(media),
        ],
        check=True,
        timeout=30,
        **subprocess_flags(),
    )
    settings = DownloadSettings(
        caption_source="local",
        caption_mode="sidecar",
        caption_model="base",
        model_revision=spec["revision"],
        spoken_language="en",
    )
    audio_media = output / "語音測試.mp3"
    subprocess.run(
        [
            find_binary("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-i",
            str(speech),
            "-c:a",
            "libmp3lame",
            str(audio_media),
        ],
        check=True,
        timeout=30,
        **subprocess_flags(),
    )
    job = {
        "id": "real-offline",
        "url": media.as_uri(),
        "media_path": str(media),
        "output": str(media),
        "title": "語音測試",
        "destination": str(output / "字幕"),
        "settings": settings.to_dict(),
    }
    results = {}
    if args.packaged:
        resource = ROOT / "dist" / f"VideoDock-{__version__}" / "_internal"
        worker = resource / "vendor" / "VideoDockWorker.exe"
        env = os.environ.copy()
        env["VIDEODOCK_RESOURCE_DIR"] = str(resource)
        requests = [
            {
                "action": "caption_service",
                "job": {
                    **job,
                    "id": "packaged-" + device,
                    "settings": replace(settings, caption_device=device).to_dict(),
                },
                "model_folder": str(models),
            }
            for device in ["cpu", "cuda"]
        ]
        started = time.monotonic()
        result = subprocess.run(
            [str(worker)],
            input="".join(json.dumps(request) + "\n" for request in requests),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=180,
            **subprocess_flags(),
        )
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        completed = [event for event in events if event["type"] == "completed"]
        assert len(completed) == 2, (events, result.stderr)
        assert all(
            "country" in Path(event["caption_paths"][0]).read_text(encoding="utf-8").lower()
            for event in completed
        )
        results["packaged_seconds"] = round(time.monotonic() - started, 2)
        results["warnings"] = [event for event in events if event["type"] == "warning"]
        print("Packaged CPU/GPU-fallback caption worker and persistent session passed.", flush=True)
        import videodock.controller as controller_module

        controller_module.worker_command = lambda: [str(worker)]
        os.environ["VIDEODOCK_RESOURCE_DIR"] = str(resource)
        store.queue_captions([str(media), str(audio_media)], settings, str(output / "packaged-queue"))
        identifiers = [row["id"] for row in store.jobs()[-2:]]
        controller.start()
        wait(
            lambda: (
                all(store.get(identifier)["status"] in {"completed", "failed"} for identifier in identifiers)
                and not controller.caption_id
            )
        )
        jobs = [store.get(identifier) for identifier in identifiers]
        assert all(job["status"] == "completed" and job["caption_language_result"] == "en" for job in jobs), (
            jobs
        )
        assert all(Path(job["caption_paths"][0]).is_file() for job in jobs)
        cues = json.loads(Path(jobs[0]["cues_path"]).read_text(encoding="utf-8"))
        cues[0]["text"] = "Corrected caption text."
        old_caption = jobs[0]["caption_paths"][0]
        controller.reexport(jobs[0], cues)
        wait(
            lambda: (
                store.get(identifiers[0])["status"] in {"completed", "failed"} and not controller.caption_id
            )
        )
        corrected = store.get(identifiers[0])
        assert corrected["status"] == "completed", corrected
        assert corrected["caption_paths"][0] != old_caption and Path(old_caption).is_file()
        assert "Corrected caption text." in Path(corrected["caption_paths"][0]).read_text(encoding="utf-8")
        store.queue_captions([str(media)], settings, str(output / "packaged-cancel"))
        cancelled_id = store.jobs()[-1]["id"]
        wait(lambda: store.get(cancelled_id)["status"] == "transcribing")
        controller.remove([cancelled_id])
        wait(lambda: not controller.caption_id)
        assert store.get(cancelled_id)["removed"] and Path(store.get(cancelled_id)["media_path"]).is_file()
        results["packaged_queue_reexport_remove"] = "passed"
        print("Packaged caption queue, correction/re-export and active removal passed.", flush=True)
    else:
        from videodock.captions import CaptionEngine

        engine = CaptionEngine()

        def denied(*_, **__):
            raise AssertionError("Offline caption test attempted a network connection")

        original_connect = socket.socket.connect
        socket.socket.connect = denied
        try:
            for device, mode in [("cpu", "sidecar"), ("cuda", "embed"), ("cpu", "burn")]:
                events = []
                request = {
                    **job,
                    "id": f"real-{device}-{mode}",
                    "settings": replace(settings, caption_device=device, caption_mode=mode).to_dict(),
                }
                started = time.monotonic()
                engine.generate(request, models, threading.Event(), events.append)
                elapsed = time.monotonic() - started
                complete = events[-1]
                assert complete["type"] == "completed", events
                text = Path(complete["caption_paths"][0]).read_text(encoding="utf-8")
                assert "country" in text.lower(), text
                assert media.is_file()
                results[f"{device}_{mode}_seconds"] = round(elapsed, 2)
                results[f"{device}_{mode}_warnings"] = [
                    event["message"] for event in events if event["type"] == "warning"
                ]
                print(device, mode, f"{elapsed:.2f}s", text[:180], flush=True)
            events = []
            audio_job = {
                **job,
                "id": "real-mp3-vtt",
                "media_path": str(audio_media),
                "output": str(audio_media),
                "url": audio_media.as_uri(),
                "settings": replace(settings, caption_format="vtt", spoken_language="auto").to_dict(),
            }
            engine.generate(audio_job, models, threading.Event(), events.append)
            complete = events[-1]
            assert complete["caption_language_result"] == "en"
            assert complete["output"] == str(audio_media)
            assert Path(complete["caption_paths"][0]).read_text(encoding="utf-8").startswith("WEBVTT")
            results["mp3_vtt_auto_language"] = "passed"
            print("Local MP3 VTT sidecars and language detection passed.", flush=True)
        finally:
            socket.socket.connect = original_connect
    controller.shutdown()
    wait(lambda: not controller.busy)
    store.close()
    (output / ("packaged-result.json" if args.packaged else "source-result.json")).write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
