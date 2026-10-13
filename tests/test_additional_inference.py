import threading
from dataclasses import replace

import pytest

from videodock.additional_captions import timed_words
from videodock.caption_models import model_spec, task_models
from videodock.inference_client import InferenceClient
from videodock.models import DownloadSettings
from videodock.translation import TranslationEngine, cache_key
from videodock.ui import SettingsPanel


def test_use_routes_models_by_task_and_selects_gpu(app):
    panel = SettingsPanel(DownloadSettings(target_languages=("ja",)))
    panel.use_model("qwen3-asr-1.7b-q4-k-m")
    assert panel.settings().caption_model == "qwen3-asr-1.7b-q4-k-m"
    assert panel.settings().caption_device == "cuda"
    assert panel.settings().caption_source == "local"
    panel.use_model("index-translate-9b-q4-k-m")
    assert panel.settings().translation_model == "index-translate-9b-q4-k-m"
    assert panel.settings().caption_model == "qwen3-asr-1.7b-q4-k-m"
    panel.use_model("qwen3-forcedaligner-0.6b-full")
    saved = panel.settings()
    assert saved.alignment_model == "qwen3-forcedaligner-0.6b-full"
    panel.load(saved)
    assert panel.settings().translation_model == saved.translation_model
    assert panel.settings().alignment_model == saved.alignment_model
    panel.deleteLater()


def test_new_model_settings_validate_tasks_and_pin_alignment(store, tmp_path):
    for spec in task_models("speech", usable_only=True):
        DownloadSettings(caption_model=spec["id"]).validate()
    for spec in task_models("translation", usable_only=True):
        DownloadSettings(translation_model=spec["id"]).validate()
    with pytest.raises(ValueError, match="speech model"):
        DownloadSettings(caption_model="index-translate-2b-full").validate()
    source = tmp_path / "audio.wav"
    source.write_bytes(b"fixture")
    settings = DownloadSettings(
        caption_source="local",
        caption_mode="sidecar",
        caption_model="qwen3-asr-1.7b-q4-k-m",
        alignment_model="qwen3-forcedaligner-0.6b-full",
    )
    store.queue_captions([str(source)], settings, str(tmp_path))
    queued = DownloadSettings.from_dict(store.jobs()[0]["settings"])
    assert queued.alignment_revision == model_spec(settings.alignment_model)["revision"]
    assert queued.model_revision == model_spec(settings.caption_model)["revision"]


def test_device_failure_restarts_in_clean_cpu_helper_only_when_allowed(monkeypatch):
    client = object.__new__(InferenceClient)
    client.settings = DownloadSettings(caption_device="cuda", cpu_fallback=True)
    client.device, client.cancel = "cuda", threading.Event()
    events, closed, started = [], [], []
    client.emit = events.append
    monkeypatch.setattr(client, "close", lambda: closed.append(True))
    monkeypatch.setattr(client, "_start", lambda: started.append(client.device))

    def call(request):
        if client.device == "cuda":
            raise RuntimeError("CUDA out of memory")
        return "translated"

    monkeypatch.setattr(client, "_call", call)
    assert client.call({"action": "translate"}) == "translated"
    assert closed == [True] and started == ["cpu"]
    assert events[0]["type"] == "warning"
    client.device, client.settings = "cuda", replace(client.settings, cpu_fallback=False)
    with pytest.raises(RuntimeError, match="CUDA"):
        client.call({"action": "translate"})
    assert started == ["cpu"]


def test_translation_cache_distinguishes_decoder_and_model():
    args = ("Hello", "en", "ja", "a" * 40)
    assert cache_key(*args) != cache_key(*args, "index-translate-2b-full-greedy-v1")
    assert cache_key(*args, "index-translate-2b-full-greedy-v1") != cache_key(
        *args, "index-translate-9b-full-greedy-v1"
    )


def test_strict_gpu_setting_does_not_reuse_an_earlier_cpu_fallback(monkeypatch, tmp_path):
    loads = []

    class Client:
        def __init__(self, spec, path, settings, cancel, emit):
            loads.append(settings.cpu_fallback)
            self.device, self.process = "cpu" if settings.cpu_fallback else "cuda", object()

        def close(self):
            self.process = None

    monkeypatch.setattr("videodock.inference_client.InferenceClient", Client)
    monkeypatch.setattr("videodock.translation.verify_model", lambda *args: tmp_path)
    engine, spec = TranslationEngine(), model_spec("index-translate-2b-full")
    settings = DownloadSettings(caption_device="cuda", cpu_fallback=True)
    engine.load(tmp_path, spec, settings, threading.Event(), lambda _: None)
    engine.load(tmp_path, spec, replace(settings, cpu_fallback=False), threading.Event(), lambda _: None)
    assert loads == [True, False]
    assert engine.device == "cuda"


def test_alignment_retains_transcript_punctuation_and_whitespace():
    words = [
        {"text": "Hello", "start_time": 0.1, "end_time": 0.4},
        {"text": "world", "start_time": 0.5, "end_time": 0.9},
    ]
    timed = timed_words(words, '"Hello, world!"', 2, 4)
    assert "".join(word.word for word in timed) == '"Hello, world!"'
    assert [(word.start, word.end) for word in timed] == [(2.1, 2.4), (2.5, 2.9)]
