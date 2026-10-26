import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QSystemTrayIcon

from videodock import controller
from videodock.captions import CaptionEngine, WaitingForModel
from videodock.desktop import power_command
from videodock.models import DownloadSettings
from videodock.processes import Cancelled
from videodock.queue_policy import transient_failure
from videodock.queue_ui import (
    BulkSettingsDialog,
    ComparisonDialog,
    QueueOptionsDialog,
    ScheduleDialog,
    differences,
)
from videodock.store import Store
from videodock.transcription import transcribe_segments
from videodock.ui import MainWindow, SettingsPanel


@pytest.fixture
def fake_workers(monkeypatch):
    workers = []

    class Worker(QObject):
        event = Signal(dict)
        ended = Signal(int)

        def __init__(self, request, parent=None):
            super().__init__(parent)
            self.requests = [request]
            self.errors = ""
            self.cancel_timer = QTimer(self)
            self.cancelled = False
            workers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

        def submit(self, request):
            self.requests.append(request)

    monkeypatch.setattr(controller, "WorkerProcess", Worker)
    monkeypatch.setattr(controller, "is_ready", lambda *_: True)
    return workers


def enqueue(store, tmp_path, count=3, settings=None):
    store.enqueue([{"url": f"https://youtu.be/controls-{i}", "title": f"Item {i}"} for i in range(count)],
                  settings or DownloadSettings(), str(tmp_path))
    return [job["id"] for job in store.jobs()]


def queue_controller(store):
    result = controller.QueueController(store)
    result.timer.stop()
    return result


def test_bulk_edits_are_atomic_and_keep_unselected_fields(store, tmp_path):
    ids = enqueue(store, tmp_path)
    store.bulk_settings([ids[1]], {"height": 720})
    store.bulk_settings(ids[:2], {"audio_bitrate": 320, "retry_categories": ("network",)})
    assert [job["settings"]["height"] for job in store.jobs()] == [1080, 720, 1080]
    assert [job["settings"]["audio_bitrate"] for job in store.jobs()] == [320, 320, 192]
    before = store.jobs()
    with pytest.raises(ValueError):
        store.bulk_settings(ids, {"height": 999})
    assert store.jobs() == before
    store.update(ids[1], status="downloading")
    before = store.get(ids[0])
    with pytest.raises(ValueError):
        store.bulk_settings(ids[:2], {"height": 480})
    assert store.get(ids[0]) == before
    with pytest.raises(ValueError):
        store.bulk_settings([ids[0]], {"height": 480}, exclude=[ids[0]])
    assert any(event["kind"] == "settings" for event in store.timeline(ids[0]))


def test_bulk_preserves_completed_stage_and_repins_models(store, tmp_path):
    identifier = enqueue(store, tmp_path, 1)[0]
    store.update(identifier, stage="caption", status="caption_queued", download_status="complete")
    with pytest.raises(ValueError, match="Media settings"):
        store.bulk_settings([identifier], {"format": "webm"})
    store.bulk_settings([identifier], {"caption_model": "base", "fallback_model": "small", "caption_source": "local", "caption_mode": "sidecar"})
    saved = store.get(identifier)
    assert saved["settings"]["model_revision"] and saved["settings"]["fallback_revision"]
    assert saved["download_status"] == "complete"
    store.update(identifier, cues_path="saved.json")
    with pytest.raises(ValueError, match="already saved"):
        store.bulk_settings([identifier], {"spoken_language": "zh"})
    store.bulk_settings([identifier], {"burn_size": 30})
    assert store.get(identifier)["settings"]["burn_size"] == 30


def test_reordering_persists_and_changes_dispatch_order(store, tmp_path):
    ids = enqueue(store, tmp_path, 4)
    store.reorder(ids[2:], ids[0], stage="download")
    assert [job["id"] for job in store.jobs()] == ids[2:] + ids[:2]
    assert store.next_queued()["id"] == ids[2]
    with StoreContext(tmp_path / "queue.sqlite3") as reopened:
        assert [job["id"] for job in reopened.jobs()] == ids[2:] + ids[:2]
    store.update(ids[0], status="downloading")
    before = store.jobs()
    with pytest.raises(ValueError, match="Active"):
        store.reorder([ids[0]], None, stage="download")
    assert store.jobs() == before


class StoreContext:
    def __init__(self, path):
        self.store = Store(path)

    def __enter__(self):
        return self.store

    def __exit__(self, *_):
        self.store.close()


def test_individual_pause_resume_and_late_handoff(app, store, tmp_path, fake_workers):
    ids = enqueue(store, tmp_path)
    c = queue_controller(store)
    c.limit = 1
    c.pause_jobs([ids[1]])
    assert store.get(ids[1])["status"] == "paused"
    c.start("download")
    worker = fake_workers[0]
    c.pause_jobs([ids[0]])
    assert worker.cancelled and store.get(ids[0])["held"]
    worker.event.emit({"type": "media_ready", "output": "saved.mp4"})
    worker.ended.emit(0)
    job = store.get(ids[0])
    assert (job["stage"], job["status"], job["download_status"]) == ("caption", "paused", "complete")
    c.pause()
    c.resume_jobs([ids[0], ids[1]])
    assert store.get(ids[0])["status"] == "caption_queued"
    assert not store.get(ids[1])["held"] and not c.running
    c.pause_jobs([ids[1]])
    c.cancel([ids[1]])
    assert store.get(ids[1])["status"] == "cancelled" and not store.get(ids[1])["held"]
    for job_id in list(c.active):
        c._event(job_id, {"type": "cancelled"})
        c._ended(job_id, 0)
    c.deleteLater()


@pytest.mark.parametrize("stage_status", ["processing", "exporting"])
def test_individual_pause_rejects_unsafe_stages(app, store, tmp_path, stage_status):
    identifier = enqueue(store, tmp_path, 1)[0]
    store.update(identifier, status=stage_status)
    c = queue_controller(store)
    c.pause_jobs([identifier])
    assert not store.get(identifier)["held"]
    c.deleteLater()


def test_hold_and_retry_survive_restart_and_recovery(app, store, tmp_path):
    ids = enqueue(store, tmp_path)
    store.update(ids[0], held=1, status="cancelling")
    due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    store.update(ids[1], status="retry_wait", retry_at=due, retry_count=2)
    assert store.recover() == 1
    assert store.get(ids[0])["status"] == "paused"
    assert store.get(ids[1])["retry_at"] == due
    c = queue_controller(store)
    assert not c.running
    c.tick(datetime.now(UTC) + timedelta(days=1))
    assert store.get(ids[1])["status"] == "retry_wait"
    c.deleteLater()


@pytest.mark.parametrize("message,expected", [
    ("HTTP Error 429: Too Many Requests", "rate_limit"), ("HTTP Error 503", "server"),
    ("Connection reset by peer", "network"), ("Read timed out", "network"),
    ("HTTP 403 Forbidden", ""), ("HTTP 404: not found", ""),
    ("CUDA out of memory", ""), ("output repetition (status 19)", ""),
    ("Permission denied", ""), ("Unknown decoder failure", ""),
])
def test_transient_failure_selection(message, expected):
    assert transient_failure(message) == expected


def test_retry_waits_for_cleanup_respects_pause_and_is_bounded(app, store, tmp_path, fake_workers):
    identifier = enqueue(store, tmp_path, 1, DownloadSettings(retry_categories=("network",), retry_limit=1, retry_delay=2))[0]
    c = queue_controller(store)
    notices = []
    c.notification.connect(lambda *args: notices.append(args))
    c.start("download")
    fake_workers[0].event.emit({"type": "error", "message": "Connection reset by peer"})
    assert store.get(identifier)["status"] == "failed"
    fake_workers[0].ended.emit(1)
    waiting = store.get(identifier)
    assert waiting["status"] == "retry_wait" and waiting["retry_count"] == 1
    assert not notices
    c.pause("download")
    c.tick(datetime.now(UTC) + timedelta(hours=1))
    assert len(fake_workers) == 1
    c.start("download")
    c.tick(datetime.now(UTC) + timedelta(hours=1))
    assert len(fake_workers) == 2
    fake_workers[1].event.emit({"type": "error", "message": "Connection reset by peer"})
    fake_workers[1].ended.emit(1)
    assert store.get(identifier)["status"] == "failed"
    assert any(item[0] == "failure" for item in notices)
    assert any(event["kind"] == "retry" for event in store.timeline(identifier))
    c.deleteLater()


def test_schedules_execute_once_cancel_and_mark_missed(app, store, tmp_path, fake_workers):
    enqueue(store, tmp_path, 1)
    c = queue_controller(store)
    due = datetime.now(UTC) + timedelta(hours=1)
    start = store.add_schedule("download", "start", due)
    pause = store.add_schedule("download", "pause", due + timedelta(minutes=1))
    resume = store.add_schedule("download", "resume", due + timedelta(minutes=2))
    cancelled = store.add_schedule("caption", "start", due)
    store.schedule_state(cancelled, "cancelled")
    c.tick(due)
    assert c.stage_running("download") and len(fake_workers) == 1
    c.tick(due + timedelta(minutes=1))
    assert not c.stage_running("download")
    c.tick(due + timedelta(minutes=2))
    assert c.stage_running("download") and len(fake_workers) == 1
    states = {item["id"]: item["state"] for item in store.schedules()}
    assert [states[key] for key in (start, pause, resume, cancelled)] == ["executed"] * 3 + ["cancelled"]
    missed = store.add_schedule("caption", "start", due)
    store.db.execute("UPDATE queue_schedules SET due=? WHERE id=?", ((datetime.now(UTC) - timedelta(hours=1)).isoformat(), missed))
    store.db.commit()
    other = queue_controller(store)
    assert next(item for item in store.schedules() if item["id"] == missed)["state"] == "missed"
    assert not other.running
    fake_workers[0].event.emit({"type": "completed", "output": "done.mp4"})
    fake_workers[0].ended.emit(0)
    c.deleteLater()
    other.deleteLater()


def test_completion_requires_success_and_no_pending_or_future_work(app, store, tmp_path):
    ids = enqueue(store, tmp_path, 2)
    c = queue_controller(store)
    completed = []
    c.completed_run.connect(lambda: completed.append(True))
    c.run_jobs.update(ids)
    store.update(ids[0], status="completed")
    c._check_completion()
    assert not completed
    store.update(ids[1], status="failed")
    c._check_completion()
    assert not completed
    c.run_jobs.update(ids)
    store.update(ids[1], status="completed")
    schedule = store.add_schedule("download", "start", datetime.now(UTC) + timedelta(days=1))
    c._check_completion()
    assert not completed
    store.schedule_state(schedule, "cancelled")
    c.run_jobs.update(ids)
    c._check_completion()
    c._check_completion()
    assert len(completed) == 1
    c.deleteLater()


def test_overdue_start_then_pause_does_not_dispatch_between_actions(app, store, tmp_path, fake_workers):
    enqueue(store, tmp_path, 1)
    c = queue_controller(store)
    due = datetime.now(UTC) + timedelta(hours=1)
    store.add_schedule("download", "start", due)
    store.add_schedule("download", "pause", due + timedelta(minutes=1))
    c.tick(due + timedelta(minutes=2))
    assert not c.stage_running("download") and not fake_workers
    c.deleteLater()


def test_bulk_cannot_disable_a_stage_already_queued(store, tmp_path):
    identifier = enqueue(store, tmp_path, 1)[0]
    settings = DownloadSettings(caption_source="local", caption_mode="sidecar", translate=True, target_languages=("ja",))
    store.bulk_settings([identifier], settings.to_dict())
    store.update(identifier, stage="caption", status="caption_queued", download_status="complete")
    with pytest.raises(ValueError, match="Cancel it"):
        store.bulk_settings([identifier], {"caption_mode": "none", "translate": False})
    store.update(identifier, stage="translation", status="translation_queued", cues_path="source.json")
    with pytest.raises(ValueError, match="Cancel it"):
        store.bulk_settings([identifier], {"translate": False})


def test_checkpoint_resume_failed_segment_and_fallback(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr("videodock.transcription.run_lines", lambda *_: None)
    monkeypatch.setattr("videodock.transcription.find_binary", lambda *_: "ffmpeg")
    calls, events = [], []
    engine = CaptionEngine()
    settings = DownloadSettings(caption_source="local", caption_mode="sidecar", caption_model="base")

    def raw(*args):
        calls.append(args[3].caption_model)
        if len(calls) == 2:
            raise ValueError("failed segment")
        return [{"start": .1, "end": 1.5, "text": "Hello 世界"}], "en"

    monkeypatch.setattr(engine, "_transcribe_segment", raw)
    with pytest.raises(ValueError, match="failed segment"):
        transcribe_segments(engine, source, work, tmp_path, settings, threading.Event(), events.append, 65)
    checkpoint = json.loads((work / "transcription.json").read_text(encoding="utf-8"))
    assert len(checkpoint["segments"]) == 1
    cues, language = transcribe_segments(engine, source, work, tmp_path, replace(settings, retry_delay=45), threading.Event(), events.append, 65)
    assert len(calls) == 4 and language == "en"
    assert [cue["start"] for cue in cues] == [.1, 30.1, 60.1]
    assert any(event["type"] == "checkpoint_resume" for event in events)
    assert engine.alignment_segments == cues
    transcribe_segments(engine, source, work, tmp_path, settings, threading.Event(), events.append, 65)
    assert len(calls) == 4
    source.write_bytes(b"changed source")
    transcribe_segments(engine, source, work, tmp_path, settings, threading.Event(), events.append, 65)
    assert len(calls) == 7


def test_failed_segments_use_only_explicit_fallback_and_keep_primary_error(tmp_path, monkeypatch):
    source = tmp_path / "speech.wav"
    source.write_bytes(b"audio")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr("videodock.transcription.run_lines", lambda *_: None)
    monkeypatch.setattr("videodock.transcription.find_binary", lambda *_: "ffmpeg")
    engine = CaptionEngine()
    events, models = [], []
    settings = DownloadSettings(caption_model="base", fallback_model="small", caption_source="local", caption_mode="sidecar")

    def raw(*args):
        model = args[3].caption_model
        models.append(model)
        if model == "base":
            raise ValueError("decoder repetition")
        return [{"start": 0, "end": 1, "text": "Recovered"}], "en"

    monkeypatch.setattr(engine, "_transcribe_segment", raw)
    cues, _ = transcribe_segments(engine, source, work, tmp_path, settings, threading.Event(), events.append, 5)
    assert cues[0]["text"] == "Recovered" and models == ["base", "small"]
    assert "decoder repetition" in next(event["message"] for event in events if event["type"] == "segment_fallback")
    saved = json.loads((work / "transcription.json").read_text(encoding="utf-8"))
    assert saved["segments"][0]["model"] == "small"
    monkeypatch.setattr(engine, "_transcribe_segment", lambda *_: (_ for _ in ()).throw(WaitingForModel("Missing", "base")))
    with pytest.raises(WaitingForModel):
        transcribe_segments(engine, source, work, tmp_path, replace(settings, spoken_language="en"), threading.Event(), events.append, 5)


def test_cancel_retains_completed_segments_and_detects_corruption(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    work = tmp_path / "work"
    work.mkdir()
    cancel = threading.Event()
    settings = DownloadSettings()
    engine = CaptionEngine()
    monkeypatch.setattr("videodock.transcription.run_lines", lambda *_: None)
    monkeypatch.setattr("videodock.transcription.find_binary", lambda *_: "ffmpeg")

    def raw(*_):
        cancel.set()
        return [{"start": 0, "end": 1, "text": "Completed segment"}], "en"

    monkeypatch.setattr(engine, "_transcribe_segment", raw)
    with pytest.raises(Cancelled):
        transcribe_segments(engine, source, work, tmp_path, settings, cancel, lambda _: None, 60)
    path = work / "transcription.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["segments"]) == 1
    saved["segments"][0]["end"] = 999
    path.write_text(json.dumps(saved), encoding="utf-8")
    cancel.clear()
    with pytest.raises(ValueError, match="boundaries"):
        transcribe_segments(engine, source, work, tmp_path, settings, cancel, lambda _: None, 60)


def test_ui_bulk_comparison_schedules_and_settings_roundtrip(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    ids = enqueue(store, tmp_path)
    window = MainWindow(store)
    window.controller.timer.stop()
    dialog = BulkSettingsDialog(store.jobs(), window.settings_panel.settings().to_dict(), window)
    for index in range(dialog.fields.count()):
        item = dialog.fields.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == "height":
            item.setCheckState(Qt.CheckState.Checked)
    dialog.panel.height.setCurrentIndex(dialog.panel.height.findData(480))
    dialog.apply()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert all(job["settings"]["height"] == 480 for job in store.jobs())
    compared = ComparisonDialog([(job["title"], job["settings"]) for job in store.jobs()], DownloadSettings().to_dict(), window)
    assert compared.table.rowCount() == 3
    assert differences(store.get(ids[0])["settings"], DownloadSettings().to_dict()) == [("height", 1080, 480)]
    schedule = ScheduleDialog(store, window)
    schedule.add()
    assert len(store.schedules()) == 1
    schedule.entries.setCurrentRow(0)
    schedule.cancel_selected()
    assert store.schedules()[0]["state"] == "cancelled"
    assert schedule.entries.count() == 0
    settings = DownloadSettings(caption_model="base", fallback_model="small", retry_categories=("network", "server"), retry_limit=4, retry_delay=60)
    panel = SettingsPanel(settings)
    result = panel.settings()
    assert (result.fallback_model, result.retry_categories, result.retry_limit, result.retry_delay) == (
        "small", ("network", "server"), 4, 60)
    for item in (dialog, compared, schedule, panel):
        item.close()
    window.close()


def test_queue_settings_indicator_moves_from_preview_and_tracks_shared_values(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow(store)
    window.controller.timer.stop()
    shared = window.settings_panel.settings()
    ids = enqueue(store, tmp_path, 3, shared)
    store.update(ids[1], stage="caption", status="caption_queued")
    store.update(ids[2], stage="translation", status="translation_queued")
    store.bulk_settings([ids[0]], {"height": 480})
    window.refresh_jobs()
    assert [window.preview.horizontalHeaderItem(i).text() for i in range(window.preview.columnCount())] == [
        "✓", "#", "Title", "Duration", "Playlist"]
    for queue in window.stage_queues.values():
        assert queue.horizontalHeaderItem(7).text() == "Settings"
        assert queue.cellWidget(0, 4) is not None
    assert window.queue.item(0, 7).text() == "Custom"
    assert "height: 1080 → 480" in window.queue.item(0, 7).toolTip()
    assert window.caption_queue.item(0, 7).text() == "Shared"
    assert window.translation_queue.item(0, 7).text() == "Shared"
    window.queue.selectRow(0)
    window.settings_panel.height.setCurrentIndex(window.settings_panel.height.findData(480))
    window.update_settings_summary()
    assert window.queue.item(0, 7).text() == "Shared"
    assert window.caption_queue.item(0, 7).text() == "Custom"
    assert window.selected_job_ids() == [ids[0]]
    # An incomplete shared edit must not interrupt job refresh or lose the saved values.
    window.settings_panel.translation_panel.enabled.setChecked(True)
    window.refresh_jobs()
    assert all(queue.item(0, 7).text() == "—" for queue in window.stage_queues.values())
    assert store.get(ids[0])["settings"]["height"] == 480
    window.close()


def test_bulk_apply_all_changed_preserves_unedited_mixed_values(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    ids = enqueue(store, tmp_path, 2)
    store.bulk_settings([ids[1]], {"height": 720, "audio_bitrate": 320})
    window = MainWindow(store)
    window.controller.timer.stop()
    dialog = BulkSettingsDialog(store.jobs(), window.settings_panel.settings().to_dict(), window)
    dialog.panel.retry_limit.setValue(5)
    dialog.panel.retry_delay.setValue(45)
    dialog.panel.height.setCurrentIndex(dialog.panel.height.findData(480))
    dialog.panel.height.setCurrentIndex(dialog.panel.height.findData(1080))
    assert all(dialog.fields.item(i).checkState() == Qt.CheckState.Unchecked for i in range(dialog.fields.count()))
    dialog.apply_all_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    jobs = store.jobs()
    assert [job["settings"]["height"] for job in jobs] == [1080, 720]
    assert [job["settings"]["audio_bitrate"] for job in jobs] == [192, 320]
    assert all(job["settings"]["retry_limit"] == 5 and job["settings"]["retry_delay"] == 45 for job in jobs)
    dialog.close()
    window.close()


def test_bulk_apply_all_changed_without_edits_keeps_jobs_untouched(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    enqueue(store, tmp_path, 2)
    window = MainWindow(store)
    window.controller.timer.stop()
    dialog = BulkSettingsDialog(store.jobs(), window.settings_panel.settings().to_dict(), window)
    notices = []
    monkeypatch.setattr("videodock.queue_ui.QMessageBox.information", lambda *args: notices.append(args))
    before = store.jobs()
    dialog.apply_all_button.click()
    assert notices and store.jobs() == before
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.close()
    window.close()


def test_bulk_apply_all_changed_keeps_atomic_stage_locks(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    ids = enqueue(store, tmp_path, 2, DownloadSettings(caption_mode="sidecar", caption_source="local"))
    store.update(ids[1], stage="caption", status="caption_queued", download_status="complete")
    window = MainWindow(store)
    window.controller.timer.stop()
    dialog = BulkSettingsDialog(store.jobs(), window.settings_panel.settings().to_dict(), window)
    dialog.panel.height.setCurrentIndex(dialog.panel.height.findData(480))
    warnings = []
    monkeypatch.setattr("videodock.queue_ui.QMessageBox.warning", lambda *args: warnings.append(args))
    before = store.jobs()
    dialog.apply_all_button.click()
    assert warnings and store.jobs() == before
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.close()
    window.close()


def test_cancelled_schedules_stay_hidden_when_panel_reopens(app, store):
    due = datetime.now(UTC) + timedelta(hours=1)
    cancelled = store.add_schedule("download", "start", due)
    active = store.add_schedule("caption", "resume", due + timedelta(minutes=1))
    executed = store.add_schedule("translation", "pause", due + timedelta(minutes=2))
    store.schedule_state(executed, "executed")
    dialog = ScheduleDialog(store)
    dialog.entries.setCurrentRow(0)
    dialog.cancel_selected()
    visible = [dialog.entries.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dialog.entries.count())]
    assert visible == [active, executed]
    assert next(entry for entry in store.schedules() if entry["id"] == cancelled)["state"] == "cancelled"
    dialog.close()
    reopened = ScheduleDialog(store)
    assert [reopened.entries.item(i).data(Qt.ItemDataRole.UserRole) for i in range(reopened.entries.count())] == visible
    reopened.close()


def test_drag_drop_moves_complete_rows_and_preserves_selection(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    ids = enqueue(store, tmp_path)
    window = MainWindow(store)
    window.controller.timer.stop()
    window.show()
    app.processEvents()
    queue = window.queue
    queue.selectRow(0)
    accepted = []
    event = SimpleNamespace(source=lambda: queue, position=lambda: QPointF(5, queue.viewport().height() + 10),
                            acceptProposedAction=lambda: accepted.append(True), ignore=lambda: None)
    queue.dropEvent(event)
    assert accepted and [job["id"] for job in store.jobs()] == ids[1:] + ids[:1]
    assert window.selected_job_ids() == [ids[0]]
    assert queue.cellWidget(2, 4) is not None and queue.item(2, 1).text() == "Item 0"
    window.close()


def test_tray_close_exit_notifications_and_power_countdown(app, store, tmp_path, monkeypatch):
    # The tray shell and OS power boundary are mocked; the countdown and queue guards are real.
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda *_: None)
    messages = []
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *args: messages.append(args))
    monkeypatch.setattr(QSystemTrayIcon, "supportsMessages", lambda *_: True)
    window = MainWindow(store)
    window.controller.timer.stop()
    options = QueueOptionsDialog(window)
    options.tray.setChecked(True)
    options.notifications["failure"].setChecked(False)
    options.power.setCurrentIndex(options.power.findData("sleep"))
    options.save()
    assert window.desktop.power_action == "sleep"
    window.desktop.notify("failure", "failed", "error")
    assert not messages
    window.desktop.notify("completion", "done", "ok")
    assert messages
    window.show()
    app.processEvents()
    window.close()
    assert not window.isVisible() and not window.controller.shutting_down
    window.desktop.queue_completed()
    assert window.desktop.countdown
    ids = enqueue(store, tmp_path, 1)
    window.controller.changed.emit()
    assert window.desktop.countdown is None and window.desktop.power_action == "none"
    store.update(ids[0], status="completed")
    requested = []
    monkeypatch.setattr(window.desktop, "perform", requested.append)
    window.desktop.arm("shutdown")
    window.desktop.queue_completed()
    countdown = window.desktop.countdown
    timer = countdown.findChild(QTimer)
    for _ in range(60):
        timer.timeout.emit()
    assert requested == ["shutdown"] and window.desktop.power_action == "none"
    window.desktop.exit()
    assert not window.isVisible()


def test_power_commands_never_force_close_applications():
    shutdown = power_command("shutdown")
    assert shutdown[-3:] == ["/s", "/t", "0"] and "/f" not in shutdown
    assert power_command("hibernate")[-1] == "/h"
    assert "SetSuspendState" in power_command("sleep")[-1]
    with pytest.raises(ValueError):
        power_command("invalid")


def test_power_disarms_after_unsuccessful_run(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    identifier = enqueue(store, tmp_path, 1)[0]
    window = MainWindow(store)
    window.controller.timer.stop()
    window.desktop.arm("sleep")
    window.controller.run_jobs.add(identifier)
    store.update(identifier, status="failed")
    window.controller._check_completion()
    assert window.desktop.power_action == "none" and not window.desktop.countdown
    window.close()
