from dataclasses import replace
from pathlib import Path

from conftest import wait_until
from PySide6.QtCore import Qt

from videodock.controller import QueueController
from videodock.models import DownloadSettings
from videodock.ui import MainWindow, SettingsPanel


def test_audio_settings_and_missing_language(app):
    panel = SettingsPanel(DownloadSettings(caption_mode="embed"))
    panel.format.setCurrentIndex(panel.format.findData("mp3"))
    assert panel.settings().caption_mode == "sidecar"
    assert not panel.height.isEnabled()
    panel.set_details(
        {"detailed": True, "heights": [720, 1080], "captions": {"creator": ["fr"], "auto": ["en"]}}
    )
    assert "unavailable" in panel.availability.text()
    panel.source.setCurrentIndex(1)
    assert "unavailable" not in panel.availability.text()
    panel.deleteLater()


def test_enqueue_selected_overrides_and_persisted_destination(app, store, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOCK_DATA_DIR", str(tmp_path / "appdata"))
    window = MainWindow(store)
    window.destination.setText(str(tmp_path / "outputs"))
    for index in range(3):
        window._preview_event(
            {
                "type": "item",
                "item": {
                    "url": f"https://youtu.be/{index}",
                    "title": f"Video {index}",
                    "playlist": "Playlist",
                    "index": index + 1,
                    "duration": 20,
                    "detailed": False,
                },
            }
        )
    window.preview.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    window.overrides[2] = replace(DownloadSettings(), format="mp3")
    window.enqueue()
    jobs = store.jobs()
    assert [job["playlist_index"] for job in jobs] == [1, 3]
    assert jobs[1]["settings"]["format"] == "mp3"
    assert store.preference("destination") == str(tmp_path / "outputs")
    window.close()
    window.deleteLater()


def test_real_queue_mixed_success_concurrency_and_history(app, store, media_server, tmp_path):
    items = [
        {"url": media_server + suffix, "title": suffix}
        for suffix in ["/media.mp4", "/missing.mp4", "/index.html"]
    ]
    store.enqueue(items, DownloadSettings(), str(tmp_path / "output"))
    controller = QueueController(store)
    active_counts = []
    controller.changed.connect(lambda: active_counts.append(len(controller.active)))
    controller.start()
    wait_until(
        app,
        lambda: (
            all(job["status"] in {"completed", "failed"} for job in store.jobs()) and not controller.active
        ),
        timeout=60,
    )
    jobs = store.jobs()
    assert [job["status"] for job in jobs] == ["completed", "failed", "completed"]
    assert max(active_counts) == 2
    assert "404" in jobs[1]["error"]
    assert all(Path(job["output"]).is_file() for job in [jobs[0], jobs[2]])
    controller.pause()
    controller.deleteLater()


def test_preview_error_is_preserved_after_completion(app, store):
    window = MainWindow(store)
    message = "This source requires authentication. Sign in and retry."
    window._preview_event({"type": "inspection_error", "message": message})
    window._preview_event({"type": "done"})
    assert message in window.notice.text()
    window.close()
    window.deleteLater()
