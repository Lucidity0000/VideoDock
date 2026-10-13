"""Two persistent worker requests exercise GPU ASR, translation and subtitle exports."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from videodock.dependencies import subprocess_flags
    from videodock.models import DownloadSettings

    parser = argparse.ArgumentParser()
    parser.add_argument("--packaged", action="store_true")
    parser.add_argument("--align", action="store_true")
    parser.add_argument("--without-toolkit", action="store_true", help="Keep only Windows directories on the child PATH")
    args = parser.parse_args()
    mode = "packaged" if args.packaged else "source"
    folder = ROOT / ".test-artifacts/gpu" / (mode + ("-aligned-pipeline" if args.align else "-pipeline")
                                            + ("-without-toolkit" if args.without_toolkit else ""))
    folder.mkdir(parents=True, exist_ok=True)
    resource = ROOT / "dist/VideoDock-0.4.0/_internal" if args.packaged else ROOT
    command = (
        [str(resource / "vendor/VideoDockWorker.exe")]
        if args.packaged
        else [sys.executable, "-m", "videodock.worker"]
    )
    environment = {
        **os.environ,
        "VIDEODOCK_DATA_DIR": str(folder / "data"),
        "VIDEODOCK_RESOURCE_DIR": str(resource),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    if args.without_toolkit:
        windows = Path(environment.get("WINDIR", "C:/Windows"))
        environment["PATH"] = os.pathsep.join(str(path) for path in (windows / "System32", windows))
        for key in list(environment):
            if key.upper().startswith("CUDA_PATH") or key.upper() == "CUDA_HOME":
                environment.pop(key)
    settings = DownloadSettings(
        caption_mode="embed",
        caption_source="local",
        caption_model="qwen3-asr-1.7b-q4-k-m",
        spoken_language="en",
        caption_device="cuda",
        cpu_fallback=False,
        alignment_model="qwen3-forcedaligner-0.6b-full" if args.align else "",
        translate=True,
        translation_model="index-translate-9b-q4-k-m",
        target_languages=("zh-Hant", "ja"),
        default_language="zh-Hant",
        track_order=("en", "zh-Hant", "ja"),
    )
    settings.validate()
    source = ROOT / ".test-artifacts/local-captions/語音測試.mp4"
    job = {
        "id": uuid.uuid4().hex,
        "settings": settings.to_dict(),
        "media_path": str(source),
        "destination": str(folder),
        "url": source.as_uri(),
        "model_folder": str(ROOT / ".test-artifacts/model-resources/source/models"),
    }
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=(folder / "stderr.log").open("wb"),
        env=environment,
        **subprocess_flags(),
    )
    events, inbox = [], queue.Queue()
    completed = {}
    embedded = {}

    def reader():
        for line in process.stdout:
            inbox.put(json.loads(line))
        inbox.put(None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        for index in range(2):
            if index:
                job["settings"].update(
                    caption_mode="burn", bilingual_language="zh-Hant", burn_language="bilingual"
                )
                job["cues_path"] = completed["cues_path"]
                job["tracks"] = completed["tracks"]
            process.stdin.write(
                (
                    json.dumps(
                        {"action": "caption_service", "job": job, "model_folder": job["model_folder"]},
                        ensure_ascii=True,
                    )
                    + "\n"
                ).encode()
            )
            process.stdin.flush()
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                event = inbox.get(timeout=60)
                assert event is not None, "Persistent worker exited"
                events.append(event)
                print(json.dumps(event, ensure_ascii=True), flush=True)
                assert event["type"] not in {"failed", "waiting_model", "error"}, event
                if event["type"] == "completed":
                    completed = event
                    if not index:
                        embedded = event
                    assert event["caption_status"] == "complete", event
                    assert Path(event["output"]).is_file()
                    break
            else:
                raise AssertionError("GPU pipeline timed out")
        runtimes = [event for event in events if event["type"] == "model_runtime"]
        assert {item["model_id"] for item in runtimes} >= {settings.caption_model, settings.translation_model}
        assert all(item["device"] == "cuda" for item in runtimes)
        info = json.loads(
            subprocess.run(
                [
                    str(resource / "vendor/ffprobe.exe"),
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    embedded["output"],
                ],
                capture_output=True,
                check=True,
                **subprocess_flags(),
            ).stdout
        )
        streams = [item for item in info["streams"] if item["codec_type"] == "subtitle"]
        assert len(streams) == 3
        assert [item["disposition"]["default"] for item in streams] == [0, 1, 0]
        original = json.loads(Path(embedded["cues_path"]).read_text(encoding="utf-8"))
        for index, track in enumerate(embedded["tracks"]):
            cues = json.loads(Path(track["cues_path"]).read_text(encoding="utf-8"))
            assert [(c["id"], c["start"], c["end"]) for c in cues] == [
                (c["id"], c["start"], c["end"]) for c in original
            ]
            extracted = subprocess.run(
                [
                    str(resource / "vendor/ffmpeg.exe"),
                    "-v",
                    "error",
                    "-i",
                    embedded["output"],
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
            assert all(c["text"] in extracted for c in cues)
        assert sum(e["type"] == "status" and e.get("status") == "transcribing" for e in events) == 1
        (folder / "report.json").write_text(
            json.dumps({"passed": True, "system_path_only": args.without_toolkit,
                        "runtime": runtimes, "events": events}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
