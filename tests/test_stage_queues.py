import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, QTimer, Signal

from videodock import controller
from videodock.captions import CaptionEngine
from videodock.models import DownloadSettings
from videodock.store import Store
from videodock.ui import MainWindow


def add_jobs(store, tmp_path, count=3):
    store.enqueue([{"url": f"https://youtu.be/split{i}", "title": title}
                   for i, title in enumerate(("Zulu", "Alpha", "Bravo")[:count])],
                  DownloadSettings(), str(tmp_path))
    return store.jobs()


def test_stage_handoff_pause_and_translation_retry(app, store, tmp_path, monkeypatch):
    workers = []

    class Worker(QObject):
        event = Signal(dict)
        ended = Signal(int)

        def __init__(self, request, parent):
            super().__init__(parent)
            self.requests, self.errors = [request], ""
            self.cancel_timer = QTimer(self)
            workers.append(self)

        def start(self):
            pass

        def submit(self, request):
            self.requests.append(request)

    monkeypatch.setattr(controller, "WorkerProcess", Worker)
    monkeypatch.setattr(controller, "is_ready", lambda *args: True)
    settings = DownloadSettings(caption_source="local", caption_mode="sidecar", translate=True, target_languages=("ja",))
    store.enqueue([{"url": "https://youtu.be/handoff", "title": "Handoff"}], settings, str(tmp_path))
    job = store.jobs()[0]
    c = controller.QueueController(store)
    c.timer.stop()
    c.start("download")
    assert c.caption_id is None and len(c.active) == 1
    assert workers[0].requests[0]["job"]["split_stages"]
    workers[0].event.emit({"type": "media_ready", "output": str(tmp_path / "media.mp4")})
    c.start("caption")
    assert c.caption_id is None and len(workers) == 1
    workers[0].ended.emit(0)
    assert store.get(job["id"])["download_status"] == "complete"
    assert store.get(job["id"])["stage"] == "caption" and c.caption_id == job["id"]
    c.start("caption")
    worker = workers[1]
    assert worker.requests[0]["job"]["defer_translation"]
    source = tmp_path / "source.json"
    source.write_text("[]")
    worker.event.emit({"type": "translation_ready", "job_id": job["id"], "cues_path": str(source), "caption_language_result": "en"})
    worker.event.emit({"type": "caption_idle", "job_id": job["id"]})
    assert store.get(job["id"])["status"] == "translation_queued" and c.caption_id is None
    c.start("translation")
    assert not worker.requests[-1]["job"]["defer_translation"]
    worker.event.emit({"type": "status", "status": "translating", "job_id": job["id"]})
    worker.event.emit({"type": "error", "message": "bad target", "job_id": job["id"]})
    failed = store.get(job["id"])
    assert (failed["download_status"], failed["caption_status"], failed["translation_status"]) == ("complete", "complete", "failed")
    c.pause()
    worker.event.emit({"type": "caption_idle", "job_id": job["id"]})
    c.caption_worker = None
    store.retry(job["id"])
    assert store.get(job["id"])["status"] == "translation_queued"
    store.update(job["id"], stage="caption", status="cancelling", caption_status="cancelling")
    c._event(job["id"], {"type": "translation_ready", "cues_path": str(source), "caption_language_result": "en"})
    assert store.get(job["id"])["status"] == "cancelled"
    assert store.get(job["id"])["translation_status"] == "cancelled"
    c.deleteLater()


def test_pipeline_defers_translation_and_reuses_durable_source(tmp_path, monkeypatch):
    from test_translation import fake_translation, imported_job

    job = imported_job(tmp_path, targets=("ja",))
    job["defer_translation"] = True
    calls, events = [], []
    fake_translation(monkeypatch, calls)
    engine = CaptionEngine()
    engine.generate(job, tmp_path / "models", threading.Event(), events.append)
    assert events[-1]["type"] == "translation_ready" and not calls
    source = Path(events[-1]["cues_path"])
    original = source.read_bytes()
    Path(job["settings"]["subtitle_import"]).write_text("invalid")
    job["defer_translation"] = False
    engine.generate(job, tmp_path / "models", threading.Event(), events.append)
    assert calls and source.read_bytes() == original
    assert events[-1]["caption_status"] == events[-1]["translation_status"] == "complete"


def test_translation_recovery_keeps_completed_stages(store, tmp_path):
    job = add_jobs(store, tmp_path, 1)[0]
    store.update(job["id"], stage="translation", status="translating", download_status="complete",
                 caption_status="complete", translation_status="translating", media_path="saved.mp4", cues_path="source.json")
    assert store.recover() == 1
    recovered = store.get(job["id"])
    assert (recovered["status"], recovered["download_status"], recovered["caption_status"], recovered["translation_status"]) == (
        "translation_queued", "complete", "complete", "queued")
    store.remove(job["id"])
    assert store.get(job["id"])["translation_status"] == "cancelled"


def test_cancel_caption_during_download_cleanup_keeps_download_complete(app, store, tmp_path, monkeypatch):
    workers = []

    class Worker(QObject):
        event = Signal(dict)
        ended = Signal(int)

        def __init__(self, request, parent):
            super().__init__(parent)
            self.errors, self.cancelled = "", False
            self.cancel_timer = QTimer(self)
            workers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(controller, "WorkerProcess", Worker)
    job = add_jobs(store, tmp_path, 1)[0]
    c = controller.QueueController(store)
    c.timer.stop()
    c.start("download")
    workers[0].event.emit({"type": "media_ready", "output": str(tmp_path / "saved.mp4")})
    c.cancel([job["id"]])
    assert not workers[0].cancelled
    assert store.get(job["id"])["download_status"] == "complete"
    workers[0].ended.emit(0)
    cancelled = store.get(job["id"])
    assert (cancelled["status"], cancelled["download_status"], cancelled["caption_status"]) == ("cancelled", "complete", "cancelled")
    # Caption cleanup can also overlap a newly queued translation stage.
    store.update(job["id"], stage="translation", status="translation_queued", caption_status="complete", translation_status="queued")
    c.caption_id = job["id"]
    c.caption_worker = Worker({}, c)
    c.cancel([job["id"]])
    assert not c.caption_worker.cancelled
    c.cancel([job["id"]])
    c.remove([job["id"]])
    c._caption_event({"type": "caption_idle", "job_id": job["id"]})
    assert store.get(job["id"])["status"] == "cancelled"
    assert store.get(job["id"])["translation_status"] == "cancelled"
    assert store.get(job["id"])["removed"]
    c.caption_worker = None
    # An in-flight missing-model response must not overwrite a cancellation.
    store.update(job["id"], status="cancelling", translation_status="cancelling")
    c._event(job["id"], {"type": "caption_waiting", "message": "missing model", "model_id": "m2m100-418m"})
    assert store.get(job["id"])["status"] == "cancelled"
    assert store.get(job["id"])["download_status"] == store.get(job["id"])["caption_status"] == "complete"
    c.shutdown()
    c.deleteLater()


def test_clear_history_protects_pending_owned_jobs_and_files(store, tmp_path):
    jobs = add_jobs(store, tmp_path)
    saved = tmp_path / "saved.mp4"
    saved.write_bytes(b"media")
    store.update(jobs[0]["id"], status="cancelled", output=str(saved))
    store.update(jobs[1]["id"], status="failed")
    store.upsert_track(jobs[0]["id"], {"language": "en", "role": "source"})
    assert store.clear_history(cancelled_only=True, exclude=(jobs[0]["id"],)) == 0
    assert store.clear_history(cancelled_only=True) == 1
    assert saved.read_bytes() == b"media" and not store.tracks(jobs[0]["id"])
    assert store.clear_history([jobs[1]["id"], jobs[2]["id"]]) == 1
    assert store.get(jobs[2]["id"])["status"] == "queued"


def test_ui_queues_history_sort_selection_and_folder_open(app, store, tmp_path, monkeypatch):
    from videodock.ui import QDesktopServices

    jobs = add_jobs(store, tmp_path)
    store.update(jobs[1]["id"], stage="caption", status="failed", download_status="complete", caption_status="failed")
    store.update(jobs[2]["id"], stage="translation", status="cancelled", download_status="complete", caption_status="complete", translation_status="cancelled")
    window = MainWindow(store)
    assert [q.rowCount() for q in window.stage_queues.values()] == [1, 1, 1]
    window.queue_tabs.setCurrentWidget(window.translation_queue)
    window.translation_queue.selectRow(0)
    assert window.selected_job_ids() == [jobs[2]["id"]]
    window.history_sort.setCurrentIndex(window.history_sort.findData([1, False]))
    assert [window.history.item(i, 1).text() for i in range(2)] == ["Alpha", "Bravo"]
    window.history.selectRow(0)
    window.refresh_jobs()
    assert window.selected_history_ids() == [jobs[1]["id"]]
    assert window._history_job()["id"] == jobs[1]["id"]
    window.history.sortItems(0, Qt.SortOrder.DescendingOrder)
    assert store.preference("history_sort") == [0, True]
    folder = tmp_path / "輸出影片"
    folder.mkdir()
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    window.destination.setText(str(folder))
    window.open_destination_button.click()
    assert Path(opened[0]) == folder
    window.destination.setText(str(folder / "missing"))
    window.open_destination_button.click()
    assert len(opened) == 1
    window.clear_selected_history()
    assert store.get(jobs[1]["id"]) is None and window.caption_queue.rowCount() == 0
    window.clear_cancelled_history()
    assert store.get(jobs[2]["id"]) is None and window.translation_queue.rowCount() == 0
    window.close()


def test_legacy_translation_stage_migration_preserves_jobs_and_tracks(tmp_path):
    p = tmp_path / "legacy.sqlite3"
    old = Store(p)
    job = add_jobs(old, tmp_path, 1)[0]
    settings = DownloadSettings(caption_mode="sidecar", translate=True, target_languages=("ja",))
    old.db.execute("UPDATE jobs SET status='translating',media_path='media.mp4',cues_path='source.json',settings=? WHERE id=?",
                   (json.dumps(settings.to_dict()), job["id"]))
    old.upsert_track(job["id"], {"language": "en", "role": "source", "status": "complete"})
    for name in ("stage", "download_status", "translation_status"):
        old.db.execute(f"ALTER TABLE jobs DROP COLUMN {name}")
    old.db.commit()
    old.close()
    migrated = Store(p)
    assert migrated.recover() == 1
    item = migrated.get(job["id"])
    assert item["stage"] == "translation" and item["status"] == "translation_queued"
    assert item["download_status"] == item["caption_status"] == "complete"
    assert len(item["tracks"]) == 1
    migrated.close()


def test_caption_repetition_error_keeps_audio_span_and_recovery_advice(tmp_path, monkeypatch):
    from videodock import additional_captions
    from videodock.caption_models import model_spec

    monkeypatch.setattr("faster_whisper.audio.decode_audio", lambda *args, **kwargs: [])
    monkeypatch.setattr("faster_whisper.vad.get_speech_timestamps", lambda *args: [{"start": 1374880, "end": 1391968}])
    monkeypatch.setattr(additional_captions, "verify_model", lambda *args: tmp_path)

    class Inference:
        def __init__(self, *args):
            self.process = object()

        def call(self, request):
            raise ValueError("transcribe_run: output repetition (status 19)")

    monkeypatch.setattr(additional_captions, "InferenceClient", Inference)
    engine = SimpleNamespace(cache_key=None, inference=None, release_speech=lambda: None)
    settings = DownloadSettings(caption_model="qwen3-asr-1.7b-q4-k-m")
    with pytest.raises(ValueError, match="85.930–86.998 seconds.*Generate captions.*status 19"):
        additional_captions.transcribe(engine, tmp_path / "audio.wav", tmp_path,
                                      model_spec(settings.caption_model), settings, threading.Event(), lambda event: None, 180)


def test_creator_captions_can_be_deferred_after_media_download(media_server, tmp_path):
    from videodock.engine import download

    events = []
    settings = DownloadSettings(caption_mode="sidecar", caption_source="creator", caption_language="en")
    download({"id": "creator-split", "url": media_server + "/index.html", "title": "Creator",
              "destination": str(tmp_path), "settings": settings.to_dict(), "split_stages": True},
             threading.Event(), events.append)
    assert events[-1]["type"] == "media_ready"
    assert Path(events[-1]["output"]).is_file() and events[-1]["caption_paths"] == []
