import hashlib
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import wait_until
from PySide6.QtCore import Qt

from videodock import caption_models
from videodock.caption_models import download_model, is_ready, model_lock, model_path, remove_model
from videodock.captions import (
    CaptionEngine,
    WaitingForModel,
    build_cues,
    reexport,
    subtitle_text,
    validate_cues,
)
from videodock.controller import QueueController
from videodock.models import DownloadSettings, parse_intervals
from videodock.processes import Cancelled
from videodock.ui import MainWindow


@pytest.mark.parametrize("text", ["", "0", "2-1", "-2", "1,", "1-", "1:5", "1-2-3", "a", "1.5"])
def test_invalid_intervals(text):
    with pytest.raises(ValueError):
        parse_intervals(text)


def test_range_queue_original_positions_and_override(app, store, tmp_path):
    window = MainWindow(store)
    window.destination.setText(str(tmp_path / "out"))
    for playlist, index in [("A", 1), ("A", 3), ("A", 4), ("A", 8), ("B", 2)]:
        window._preview_event(
            {
                "type": "item",
                "item": {
                    "url": f"https://youtu.be/{playlist}{index}",
                    "title": f"{playlist}{index}",
                    "playlist": playlist,
                    "index": index,
                    "duration": 1,
                },
            }
        )
    window.overrides[2] = replace(DownloadSettings(), format="mp3")
    window.range_playlist.setCurrentIndex(window.range_playlist.findData("A"))
    window.intervals.setText("3-4,8,3")
    window.select_intervals()
    assert window.preview.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert window.preview.item(4, 0).checkState() == Qt.CheckState.Checked
    window.enqueue_intervals()
    assert [job["playlist_index"] for job in store.jobs()] == [3, 4, 8]
    assert store.jobs()[1]["settings"]["format"] == "mp3"
    window.intervals.setText("8-2")
    window.enqueue_intervals()
    assert len(store.jobs()) == 3
    window.close()
    window.deleteLater()


def test_remove_releases_duplicate_and_preserves_files(store, tmp_path):
    item = {"url": "https://youtu.be/a", "title": "A"}
    store.enqueue([item], DownloadSettings(), str(tmp_path))
    job = store.jobs()[0]
    partial = tmp_path / ".videodock" / job["id"] / "media.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"keep")
    store.remove(job["id"])
    assert store.get(job["id"])["removed"] and partial.read_bytes() == b"keep"
    assert store.next_queued() is None
    assert store.enqueue([item], DownloadSettings(), str(tmp_path)) == (1, 0)


def test_legacy_database_migration_preserves_duplicate_detection(tmp_path):
    import sqlite3

    from videodock.store import Store

    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE jobs (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, url TEXT NOT NULL,
        title TEXT NOT NULL, settings TEXT NOT NULL, destination TEXT NOT NULL,
        playlist TEXT NOT NULL DEFAULT '', playlist_index INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0, speed REAL, eta REAL,
        error TEXT NOT NULL DEFAULT '', output TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
        duplicate_key TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL)""")
    db.execute(
        """INSERT INTO jobs (id,url,title,settings,destination,duplicate_key,created,updated)
        VALUES (?,?,?,?,?,?,?,?)""",
        ("legacy", "https://youtu.be/a", "A", "{}", str(tmp_path), "old-fingerprint", "old", "old"),
    )
    db.commit()
    db.close()
    store = Store(path)
    try:
        assert store.get("legacy")["caption_paths"] == []
        assert store.enqueue(
            [{"url": "https://youtu.be/a", "title": "A"}], DownloadSettings(), str(tmp_path)
        ) == (0, 1)
    finally:
        store.close()


def test_caption_settings_snapshot_recovery_and_retry(store, sample_media, tmp_path):
    settings = DownloadSettings(caption_source="local", caption_mode="sidecar", caption_model="base")
    store.queue_captions([str(sample_media / "media.mp4")], settings, str(tmp_path))
    job = store.jobs()[0]
    assert job["settings"]["model_revision"] == caption_models.model_spec("base")["revision"]
    store.update(job["id"], status="transcribing", caption_status="transcribing", processed_duration=1)
    assert store.recover() == 1
    assert store.get(job["id"])["status"] == "caption_queued"
    store.update(job["id"], status="failed")
    store.retry(job["id"])
    assert store.get(job["id"])["media_path"] == str(sample_media / "media.mp4")
    assert store.get(job["id"])["status"] == "caption_queued"


def small_spec():
    content = b"test-model-data"
    return {
        "id": "base",
        "revision": "a" * 40,
        "repository": "test/repo",
        "bytes": len(content),
        "files": [{"name": "model.bin", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
    }, content


class Response:
    def __init__(self, data, offset=0, ranged=False):
        import io

        self.source = io.BytesIO(data[offset:])
        self.status = 206 if ranged else 200
        self.headers = {"Content-Range": f"bytes {offset}-{len(data) - 1}/{len(data)}"}

    def read(self, size):
        return self.source.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def test_model_resume_repair_integrity_and_removal(tmp_path, monkeypatch):
    spec, content = small_spec()
    monkeypatch.setattr(caption_models, "model_spec", lambda _: spec)
    stage = tmp_path / ".staging" / spec["id"] / spec["revision"]
    stage.mkdir(parents=True)
    (stage / "model.bin.part").write_bytes(content[:5])
    requests = []

    def fetch(request, **_):
        requests.append(request)
        offset = int(request.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
        return Response(content, offset, ranged=bool(offset))

    monkeypatch.setattr(caption_models, "urlopen", fetch)
    events = []
    download_model(tmp_path, "base", threading.Event(), events.append)
    assert requests[0].headers["Range"] == "bytes=5-"
    assert is_ready(tmp_path, spec)
    with model_lock(tmp_path, spec), pytest.raises(ValueError, match="in use"):
        remove_model(tmp_path, "base")
    (model_path(tmp_path, spec) / "model.bin").write_bytes(b"x" * len(content))
    download_model(tmp_path, "base", threading.Event(), events.append)
    assert (model_path(tmp_path, spec) / "model.bin").read_bytes() == content
    remove_model(tmp_path, "base")
    assert not is_ready(tmp_path, spec)


def test_model_bad_hash_disk_full_and_cancel(tmp_path, monkeypatch):
    spec, content = small_spec()
    monkeypatch.setattr(caption_models, "model_spec", lambda _: spec)
    monkeypatch.setattr(caption_models, "urlopen", lambda *_, **__: Response(b"x" * len(content)))
    with pytest.raises(ValueError, match="Integrity"):
        download_model(tmp_path, "base", threading.Event(), lambda _: None)
    assert not is_ready(tmp_path, spec)
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        download_model(tmp_path, "base", event, lambda _: None)
    monkeypatch.setattr(
        caption_models, "check_destination", lambda *args: (_ for _ in ()).throw(ValueError("disk full"))
    )
    with pytest.raises(ValueError, match="disk full"):
        download_model(tmp_path, "base", threading.Event(), lambda _: None)


def test_readable_cues_preserve_long_silent_timeline():
    settings = DownloadSettings(caption_line_length=20, caption_max_duration=3)
    words = [SimpleNamespace(start=600 + i * 0.5, end=600.4 + i * 0.5, word=" word") for i in range(24)]
    segments = [SimpleNamespace(start=600, end=612, text="words", words=words)]
    cues = build_cues(segments, settings, threading.Event(), lambda _: None, 3600)
    validate_cues(cues)
    assert cues[0]["start"] == 600
    assert all(cue["end"] - cue["start"] <= 3 and len(cue["text"].splitlines()) <= 2 for cue in cues)
    assert "00:10:00,000" in subtitle_text(cues, "srt")
    assert subtitle_text([], "vtt").startswith("WEBVTT")
    with pytest.raises(ValueError):
        validate_cues([{"start": 1, "end": 2, "text": "a"}, {"start": 1.9, "end": 3, "text": "b"}])


def test_offline_engine_sidecar_preserves_original_and_reexports(sample_media, tmp_path, monkeypatch):
    source = sample_media / "media.mp4"
    settings = DownloadSettings(caption_source="local", caption_mode="sidecar", caption_model="base")
    job = {
        "id": "caption",
        "url": source.as_uri(),
        "settings": settings.to_dict(),
        "media_path": str(source),
        "output": str(source),
        "destination": str(tmp_path / "字幕"),
    }
    engine = CaptionEngine()
    segment = SimpleNamespace(
        start=0.2,
        end=1.2,
        text="Hello 世界.",
        words=[SimpleNamespace(start=0.2, end=1.2, word="Hello 世界.")],
    )
    model = SimpleNamespace(transcribe=lambda *a, **kw: (iter([segment]), SimpleNamespace(language="en")))
    monkeypatch.setattr(engine, "_load", lambda *a: model)
    monkeypatch.setattr("videodock.captions.is_ready", lambda *a: True)
    events = []
    original = source.read_bytes()
    engine.generate(job, tmp_path / "models", threading.Event(), events.append)
    completed = events[-1]
    assert completed["type"] == "completed"
    assert source.read_bytes() == original
    subtitle = Path(completed["caption_paths"][0])
    assert "Hello 世界." in subtitle.read_text(encoding="utf-8")
    assert not (Path(job["destination"]) / ".videodock" / "caption-captions").exists()
    job.update(completed)
    reexport(job, [{"start": 0.3, "end": 1.3, "text": "Corrected."}], threading.Event(), events.append)
    assert Path(events[-1]["caption_paths"][0]) != subtitle
    assert "Hello" in subtitle.read_text(encoding="utf-8")


def test_caption_waiting_and_cancel_keeps_saved_media(app, store, sample_media, tmp_path):
    source = sample_media / "media.mp4"
    store.set_preference("model_folder", str(tmp_path / "models"))
    store.queue_captions([str(source)], DownloadSettings(caption_model="base"), str(tmp_path / "out"))
    controller = QueueController(store)
    controller.start()
    job = store.jobs()[0]
    assert job["status"] == "waiting_model" and not controller.caption_id
    controller.cancel([job["id"]])
    assert store.get(job["id"])["status"] == "cancelled" and source.is_file()
    store.retry(job["id"])
    controller.pump()
    controller.remove([job["id"]])
    assert store.get(job["id"])["removed"]
    controller.shutdown()
    wait_until(app, lambda: not controller.busy)
    controller.deleteLater()


def test_missing_model_fails_before_audio_work(sample_media, tmp_path):
    source = sample_media / "media.mp4"
    job = {
        "id": "no-model",
        "url": source.as_uri(),
        "media_path": str(source),
        "output": str(source),
        "destination": str(tmp_path),
        "settings": DownloadSettings(caption_source="local", caption_mode="sidecar").to_dict(),
    }
    with pytest.raises(WaitingForModel):
        CaptionEngine().generate(job, tmp_path / "models", threading.Event(), lambda _: None)
    assert source.is_file()


def test_gpu_missing_hardware_memory_and_english_only(tmp_path, monkeypatch):
    import ctranslate2
    import faster_whisper

    engine = CaptionEngine()
    spec = caption_models.model_spec("base")
    monkeypatch.setattr("videodock.captions.verify_model", lambda *args: tmp_path)
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    settings = DownloadSettings(caption_device="cuda", cpu_fallback=False)
    with pytest.raises(ValueError, match="unavailable"):
        engine._load(tmp_path, spec, settings, threading.Event(), lambda _: None)
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr("videodock.translation.gpu_library_error", lambda: "")
    attempts = []

    def load(path, **options):
        attempts.append(options["device"])
        if options["device"] == "cuda":
            raise RuntimeError("out of memory")
        return SimpleNamespace()

    monkeypatch.setattr(faster_whisper, "WhisperModel", load)
    engine._load(tmp_path, spec, replace(settings, cpu_fallback=True), threading.Event(), lambda _: None)
    assert attempts == ["cuda", "cpu"] and engine.loaded_device == "cpu"
    with pytest.raises(ValueError, match="English-only"):
        DownloadSettings(caption_model="distil-v3.5", spoken_language="zh").validate()


def test_imported_audio_always_sidecar(store, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fixture")
    store.queue_captions([str(audio)], DownloadSettings(caption_mode="burn"), str(tmp_path))
    assert store.jobs()[0]["settings"]["caption_mode"] == "sidecar"


def test_download_local_captions_waits_without_losing_media(app, store, media_server, tmp_path):
    store.set_preference("model_folder", str(tmp_path / "models"))
    store.enqueue(
        [{"url": media_server + "/media.mp4", "title": "Source"}],
        DownloadSettings(caption_source="local", caption_mode="embed", caption_model="base"),
        str(tmp_path / "out"),
    )
    controller = QueueController(store)
    controller.start()
    wait_until(app, lambda: store.jobs()[0]["status"] == "waiting_model" and not controller.active)
    job = store.jobs()[0]
    assert Path(job["media_path"]).is_file() and job["output"] == job["media_path"]
    assert job["attempts"] == 1
    controller.cancel([job["id"]])
    store.retry(job["id"])
    controller.pump()
    assert store.get(job["id"])["attempts"] == 1
    controller.shutdown()
    wait_until(app, lambda: not controller.busy)
    controller.deleteLater()


def test_youtube_fallback_uses_available_captions_without_model(app, store, media_server, tmp_path):
    store.set_preference("model_folder", str(tmp_path / "no-models"))
    store.enqueue(
        [{"url": media_server + "/index.html", "title": "Caption source"}],
        DownloadSettings(caption_source="fallback_creator", caption_mode="embed", caption_model="base"),
        str(tmp_path / "out"),
    )
    controller = QueueController(store)
    controller.start()
    wait_until(
        app,
        lambda: (
            store.jobs()[0]["status"] in {"completed", "failed"}
            and not controller.caption_id
            and not controller.active
        ),
        timeout=45,
    )
    job = store.jobs()[0]
    assert job["status"] == "completed", job["error"]
    assert Path(job["media_path"]).is_file() and Path(job["output"]).is_file()
    assert job["media_path"] != job["output"]
    assert "世界" in Path(job["caption_paths"][0]).read_text(encoding="utf-8")
    controller.shutdown()
    wait_until(app, lambda: not controller.busy)
    controller.deleteLater()


def test_fallback_missing_language_waits_and_removal_stops_download(app, store, media_server, tmp_path):
    store.set_preference("model_folder", str(tmp_path / "no-models"))
    store.enqueue(
        [{"url": media_server + "/index.html", "title": "Caption source"}],
        DownloadSettings(
            caption_source="fallback_creator",
            caption_mode="sidecar",
            caption_language="zh",
            caption_model="base",
        ),
        str(tmp_path / "out"),
    )
    controller = QueueController(store)
    controller.start()
    wait_until(
        app,
        lambda: (
            store.jobs()[0]["status"] == "waiting_model"
            and not controller.caption_id
            and not controller.active
        ),
        timeout=45,
    )
    assert Path(store.jobs()[0]["media_path"]).is_file()
    store.enqueue(
        [{"url": media_server + "/media.mp4", "title": "Remove me"}],
        DownloadSettings(),
        str(tmp_path / "out"),
    )
    controller.pump()
    job = store.jobs()[-1]
    assert job["id"] in controller.active
    controller.remove([job["id"]])
    wait_until(app, lambda: job["id"] not in controller.active)
    assert store.get(job["id"])["removed"] and store.get(job["id"])["status"] == "cancelled"
    assert "Traceback" not in store.get(job["id"])["error"]
    controller.shutdown()
    wait_until(app, lambda: not controller.busy)
    controller.deleteLater()
