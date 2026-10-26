"""Verify the actual windowed release and console worker against a local HTTP source."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tomllib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
OUTPUT = ROOT / ".test-artifacts" / "releases" / VERSION / "packaged"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["VIDEODOCK_DATA_DIR"] = str(OUTPUT / "appdata")
    environment["PYTHONIOENCODING"] = "utf-8"
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    gui = ROOT / "dist" / f"VideoDock-{version}" / "VideoDock.exe"
    subprocess.run([str(gui), "--smoke-test", str(OUTPUT)], env=environment, check=True, timeout=30)
    report = json.loads((OUTPUT / "report.json").read_text(encoding="utf-8"))
    assert report["tabs"] == 5 and (OUTPUT / "window.png").is_file()
    assert report["page_names"] == ["Downloads", "Download settings", "Models", "History",
                                    "Settings and dependencies"]
    assert report["settings_tabs"] == ["Media", "Captions", "Translation", "Subtitle style"]
    assert report["queue_names"] == ["Downloading", "Captioning", "Translating"]
    assert report["open_destination"] == "Open" and len(report["history_sort_options"]) == 8
    assert report["history_columns"][3:6] == ["Download", "Captions", "Translation"]
    assert report["clear_history_actions"] == ["Clear selected history", "Clear cancelled history"]
    assert report["model_tabs"] == ["Speech models", "Translation models", "Alignment models"]
    assert report["saved_lists"]["remaining_entries"] == 1 and report["saved_lists"]["added_from_other_link"]
    assert report["auto_start"] == {"caption": True, "translation": True, "queues_paused": True}
    assert report["queue_controls"] == {"bulk_edit": True, "comparison": True, "job_pause_resume": True,
                                        "schedules": True, "timeline": True, "power_executed": False,
                                        "settings_in_queues": True, "apply_all_changed": True,
                                        "cancelled_schedules_hidden": True}
    assert len(report["resource_models"]) == 9
    assert set(report["speech_selector"]) == {"base", "small", "turbo", "large-v3", "distil-v3.5",
                                            "ark-asr-0.6b-full", "ark-asr-3b-full",
                                            "qwen3-asr-1.7b-full", "qwen3-asr-1.7b-q4-k-m"}
    assert not any("Missing" in value for value in report["dependencies"].values()), report
    environment["VIDEODOCK_RESOURCE_DIR"] = report["resources"]
    vendor = Path(report["resources"]) / "vendor"
    media = OUTPUT / "input.mp4"
    subprocess.run(
        [
            str(vendor / "ffmpeg.exe"),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(media),
        ],
        check=True,
        timeout=20,
    )

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(OUTPUT), **kwargs)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (OUTPUT / "index.html").write_text(
            '<html><head><meta charset="utf-8"><title>機器學習基石 · Unicode preview</title></head>'
            '<body><video src="input.mp4"></video></body></html>',
            encoding="utf-8",
        )
        inspection = subprocess.run(
            report["worker"],
            input=json.dumps(
                {"action": "inspect", "urls": [f"http://127.0.0.1:{server.server_port}/index.html"]},
                ensure_ascii=False,
            )
            + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=60,
            check=False,
        )
        previews = [json.loads(line) for line in inspection.stdout.splitlines() if line.startswith("{")]
        assert inspection.returncode == 0, (inspection.stdout, inspection.stderr)
        item = next(event["item"] for event in previews if event["type"] == "item")
        assert "機器學習基石" in item["title"], item
        request = {
            "action": "download",
            "job": {
                "id": "packaged",
                "url": f"http://127.0.0.1:{server.server_port}/input.mp4",
                "title": "機器學習基石 · Packaged smoke test",
                "destination": str(OUTPUT / "下載測試"),
                "playlist_index": 0,
                "settings": {},
            },
        }
        result = subprocess.run(
            report["worker"],
            input=json.dumps(request, ensure_ascii=False) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=60,
            check=False,
        )
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        assert result.returncode == 0, (result.stdout, result.stderr)
        completed = next(event for event in events if event["type"] == "completed")
        assert Path(completed["output"]).is_file()
        assert Path(completed["output"]).parent == OUTPUT / "下載測試"
        print("Packaged GUI, Unicode preview, Unicode destination, and actual download worker passed.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
