import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from videodock.caption_models import model_spec
from videodock.captions import CaptionEngine, WaitingForModel, reexport
from videodock.languages import chinese_text, model_language
from videodock.media import probe, process_media
from videodock.models import DownloadSettings
from videodock.processes import Cancelled
from videodock.subtitles import ass_text, parse_subtitles
from videodock.translation import TranslationEngine, split_input
from videodock.ui import SettingsPanel


def imported_job(tmp_path, targets=("zh-Hant", "ja"), **kwargs):
    subtitle = tmp_path / "source.srt"
    subtitle.write_text(
        "1\n00:00:00,100 --> 00:00:01,100\nHello world.\n\n2\n00:00:01,200 --> 00:00:01,800\nThank you.\n",
        encoding="utf-8",
    )
    settings = DownloadSettings(
        caption_mode="sidecar",
        caption_source="import",
        subtitle_import=str(subtitle),
        translation_source_language="en",
        translate=True,
        target_languages=targets,
        **kwargs,
    )
    return {
        "id": "translation",
        "url": subtitle.as_uri(),
        "settings": settings.to_dict(),
        "media_path": str(subtitle),
        "output": str(subtitle),
        "destination": str(tmp_path / "out"),
    }


def fake_translation(monkeypatch, calls, fail=""):
    monkeypatch.setattr("videodock.caption_pipeline.is_ready", lambda *args: True)
    monkeypatch.setattr(TranslationEngine, "load", lambda *args: None)
    monkeypatch.setattr(
        TranslationEngine,
        "texts",
        lambda self, texts, src, tgt, cancel: (
            (_ for _ in ()).throw(ValueError("bad target"))
            if tgt == fail
            else calls.extend((text, src, tgt) for text in texts) or [tgt + ": " + text for text in texts]
        ),
    )

    class Tokenizer:
        def encode(self, text, **kwargs):
            return list(text)

    monkeypatch.setattr(
        TranslationEngine,
        "__init__",
        lambda self: (setattr(self, "tokenizer", Tokenizer()), setattr(self, "device", "cpu")) and None,
    )


def test_scripts_and_supported_language_validation():
    assert chinese_text("简体中文学习", "zh-Hant") == "簡體中文學習"
    assert chinese_text("繁體中文學習", "zh-Hans") == "繁体中文学习"
    assert model_language("zh-Hant") == "zh"
    with pytest.raises(ValueError, match="Unsupported"):
        model_language("xx")
    with pytest.raises(ValueError, match="unsupported"):
        DownloadSettings(caption_mode="sidecar", translate=True, target_languages=("xx",)).validate()
    settings = DownloadSettings(caption_mode="sidecar", translate=True, target_languages=("zh-Hant", "ja"))
    assert settings == DownloadSettings.from_dict(settings.to_dict())
    assert settings.deferred_captions


def test_empty_language_options_show_na_and_recover(app):
    panel = SettingsPanel(DownloadSettings())
    assert panel.language.currentText() == "N/A"
    panel.set_details({"detailed": True, "captions": {"creator": [], "auto": []}})
    assert panel.language.currentText() == "N/A" and panel.language.count() == 1
    assert panel.settings().caption_language == ""
    panel.set_details({"detailed": True, "captions": {"creator": ["en"], "auto": []}})
    assert panel.language.currentText() == "en" and panel.language.isEditable()
    panel.source.setCurrentIndex(panel.source.findData("local"))
    assert panel.language.currentText() == "N/A"
    panel.chinese.setCurrentIndex(panel.chinese.findData("zh-Hant"))
    assert panel.settings().chinese_script == "zh-Hant"
    panel.deleteLater()


def test_import_timestamps_tags_and_rolling_duplicates(tmp_path):
    path = tmp_path / "captions.vtt"
    path.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000 align:start\n<c>Hello</c>\n\n"
        "00:00:01.500 --> 00:00:03.000\nHello world\n",
        encoding="utf-8",
    )
    cues = parse_subtitles(path, rolling=True)
    assert [cue["text"] for cue in cues] == ["Hello", "world"]
    assert cues[0]["end"] == 1.5 and cues[1]["start"] == 1.5
    path.write_text("1\n00:00:02,000 --> 00:00:01,000\nbad\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_subtitles(path)


def test_long_input_keeps_every_character():
    text = "This is a sentence. " * 70 + "無空格的很長中文文字" * 100
    chunks = split_input(text, list, 40)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 40 for chunk in chunks)


def test_offline_translation_partial_retry_cache_and_single_source(tmp_path, monkeypatch):
    job = imported_job(tmp_path)
    calls = []
    fake_translation(monkeypatch, calls, fail="ja")
    events = []
    engine = CaptionEngine()
    engine.generate(job, tmp_path / "models", threading.Event(), events.append)
    first = events[-1]
    assert first["caption_status"] == "complete" and first["translation_status"] == "partial" and "ja" in first["error"]
    assert len(first["caption_paths"]) == 2
    assert {track["language"] for track in first["tracks"]} == {"en", "zh-Hant", "ja"}
    source_bytes = Path(first["cues_path"]).read_bytes()
    # Restart without a source subtitle or loaded speech model; checkpoints suffice.
    Path(job["settings"]["subtitle_import"]).write_text("malformed", encoding="utf-8")
    calls.clear()
    fake_translation(monkeypatch, calls)
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    assert events[-1]["caption_status"] == "complete"
    assert {target for _, _, target in calls} == {"ja"}
    assert Path(first["cues_path"]).read_bytes() == source_bytes
    assert len(events[-1]["caption_paths"]) == 3


def test_cancel_resumes_completed_cues_and_empty_input(tmp_path, monkeypatch):
    job = imported_job(tmp_path, targets=("ja",))
    calls = []
    fake_translation(monkeypatch, calls)
    cancel = threading.Event()

    def stop(event):
        if event["type"] == "translation_progress":
            cancel.set()

    with pytest.raises(Cancelled):
        CaptionEngine().generate(job, tmp_path / "models", cancel, stop)
    calls.clear()
    events = []
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    assert not calls and events[-1]["caption_status"] == "complete"
    other = tmp_path / "empty"
    other.mkdir()
    job = imported_job(other)
    Path(job["settings"]["subtitle_import"]).write_text("", encoding="utf-8")
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    assert all(Path(path).read_text(encoding="utf-8").strip() == "" for path in events[-1]["caption_paths"])


def test_import_waits_only_for_translation_model_and_preserves_source(tmp_path):
    job = imported_job(tmp_path)
    events = []
    with pytest.raises(WaitingForModel) as exc:
        CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    assert exc.value.model_id == "m2m100-418m"
    assert any(event["type"] == "caption_source" for event in events)
    assert list((tmp_path / "out").glob("*.en.srt"))


def test_edit_invalidates_targets_preserves_manual_and_bilingual(tmp_path, monkeypatch):
    job = imported_job(tmp_path, bilingual_language="zh-Hant")
    calls = []
    fake_translation(monkeypatch, calls)
    events = []
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    job.update(events[-1])
    tracks = {t["language"]: t for t in job["tracks"]}
    source = json.loads(Path(tracks["en"]["cues_path"]).read_text(encoding="utf-8"))
    target = json.loads(Path(tracks["ja"]["cues_path"]).read_text(encoding="utf-8"))
    source[0]["text"] = "Edited source."
    target[0]["text"] = "Manual target."
    old_exports = {path: Path(path).read_bytes() for path in job["caption_paths"]}
    reexport(job, {"en": source, "ja": target}, threading.Event(), events.append)
    assert any(track["status"] == "stale" for track in events[-1]["tracks"])
    calls.clear()
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    ja = next(track for track in events[-1]["tracks"] if track["language"] == "ja")
    assert json.loads(Path(ja["cues_path"]).read_text(encoding="utf-8"))[0]["text"] == "Manual target."
    assert all(Path(path).read_bytes() == content for path, content in old_exports.items())


@pytest.mark.parametrize("fmt", ["mp4", "webm"])
def test_real_multi_track_mapping_and_extraction(sample_media, tmp_path, fmt):
    import subprocess

    from videodock.dependencies import find_binary, subprocess_flags

    captions = []
    texts = ["English", "繁體中文", "日本語"]
    for language, text in zip(["en", "zh-Hant", "ja"], texts, strict=True):
        path = tmp_path / (language + ".srt")
        path.write_text(f"1\n00:00:00,100 --> 00:00:01,100\n{text}\n", encoding="utf-8")
        captions.append({"path": path, "language": language, "title": language})
    settings = DownloadSettings(format=fmt, caption_mode="embed", default_language="zh-Hant")
    result = process_media(
        sample_media / "media.mp4", tmp_path, settings, captions, threading.Event(), lambda _: None
    )
    streams = [stream for stream in probe(result)["streams"] if stream["codec_type"] == "subtitle"]
    assert len(streams) == 3
    assert [stream["disposition"]["default"] for stream in streams] == [0, 1, 0]
    for index, text in enumerate(texts):
        output = subprocess.run(
            [
                find_binary("ffmpeg"),
                "-v",
                "error",
                "-i",
                str(result),
                "-map",
                f"0:s:{index}",
                "-f",
                "srt",
                "-",
            ],
            capture_output=True,
            **subprocess_flags(),
        )
        assert output.returncode == 0 and text in output.stdout.decode("utf-8")


def test_chinese_conversion_without_speech_or_translation_model(tmp_path):
    job = imported_job(tmp_path, targets=("zh-Hant",), chinese_script="zh-Hans")
    job["settings"]["translation_source_language"] = "zh-Hans"
    Path(job["settings"]["subtitle_import"]).write_text(
        "1\n00:00:00,100 --> 00:00:01,100\n学习简体中文\n", encoding="utf-8"
    )
    events = []
    CaptionEngine().generate(job, tmp_path / "no-models", threading.Event(), events.append)
    path = next(path for path in events[-1]["caption_paths"] if "zh-Hant" in path)
    assert "學習簡體中文" in Path(path).read_text(encoding="utf-8")


def test_translation_queue_pins_model_and_mixed_overrides(store, tmp_path):
    settings = DownloadSettings(caption_mode="sidecar", translate=True, target_languages=("zh-Hant", "ja"))
    items = [{"url": f"https://youtu.be/{i}", "title": str(i)} for i in range(2)]
    store.enqueue(
        items, settings, str(tmp_path), overrides={1: replace(settings, target_languages=("zh-Hans",))}
    )
    jobs = store.jobs()
    assert jobs[0]["settings"]["translation_revision"] == model_spec("m2m100-418m")["revision"]
    assert jobs[1]["settings"]["target_languages"] == ["zh-Hans"]
    store.update(jobs[0]["id"], status="translating", media_path="saved.mp4")
    assert store.recover() == 1
    assert store.get(jobs[0]["id"])["status"] == "caption_queued"


def test_ass_styling_cjk_rtl_and_text_injection():
    settings = DownloadSettings(burn_size=36, burn_color="#ABCDEF", burn_position="top")
    text = ass_text([{"start": 0.1, "end": 1, "text": "繁體中文\nالعربية {tag}"}], settings)
    assert "&H00EFCDAB" in text and ",8,30,30,30,1" in text
    assert "繁體中文\\Nالعربية \\{tag\\}" in text


def test_translation_gpu_preflight_fallback_and_disabled(tmp_path, monkeypatch):
    import ctranslate2
    import sentencepiece

    monkeypatch.setattr("videodock.translation.verify_model", lambda *args: tmp_path)
    monkeypatch.setattr("videodock.translation.gpu_library_error", lambda: "missing cuBLAS")
    monkeypatch.setattr(sentencepiece, "SentencePieceProcessor", lambda **kwargs: object())
    devices = []
    monkeypatch.setattr(
        ctranslate2, "Translator", lambda *args, **kwargs: devices.append(kwargs["device"]) or object()
    )
    spec = model_spec("m2m100-418m")
    events = []
    TranslationEngine().load(
        tmp_path, spec, DownloadSettings(caption_device="cuda"), threading.Event(), events.append
    )
    assert devices == ["cpu"] and events[0]["type"] == "warning"
    with pytest.raises(ValueError, match="cuBLAS"):
        TranslationEngine().load(
            tmp_path,
            spec,
            DownloadSettings(caption_device="cuda", cpu_fallback=False),
            threading.Event(),
            events.append,
        )


def test_saved_translation_source_preserves_ids_and_cue_overrides(store, tmp_path, monkeypatch):
    job = imported_job(tmp_path)
    calls = []
    fake_translation(monkeypatch, calls)
    events = []
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    job.update(events[-1])
    source_track = next(track for track in job["tracks"] if track["role"] == "source")
    cues = json.loads(Path(source_track["cues_path"]).read_text(encoding="utf-8"))
    cues[0]["id"] = "custom-id"
    cues[0]["language"] = "ja"
    Path(source_track["cues_path"]).write_text(json.dumps(cues), encoding="utf-8")
    settings = DownloadSettings(caption_mode="sidecar", translate=True, target_languages=("zh-Hant",))
    store.queue_translation(job, settings)
    queued = store.jobs()[-1]
    copied = Path(queued["destination"]) / ".videodock-captions" / queued["id"] / "source.json"
    assert json.loads(copied.read_text(encoding="utf-8"))[0]["id"] == "custom-id"
    CaptionEngine().generate(queued, tmp_path / "models", threading.Event(), events.append)
    assert any(src == "ja" for _, src, _ in calls)


def test_retry_one_target_leaves_other_failed_target_untouched(tmp_path, monkeypatch):
    job = imported_job(tmp_path)
    calls = []
    fake_translation(monkeypatch, calls, fail="ja")
    events = []
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    folder = Path(events[-1]["cues_path"]).parent
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for track in manifest["tracks"]:
        if track["role"] == "target":
            track["status"] = "failed"
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    fake_translation(monkeypatch, calls)
    calls.clear()
    job["retry_languages"] = ["ja"]
    CaptionEngine().generate(job, tmp_path / "models", threading.Event(), events.append)
    assert {target for _, _, target in calls} == {"ja"}
    assert events[-1]["caption_status"] == "complete" and events[-1]["translation_status"] == "partial"


def test_legacy_reexport_uses_private_cue_folder_without_overwriting(tmp_path):
    cue = {"start": 0.1, "end": 1, "text": "Old caption"}
    source = tmp_path / "legacy.srt"
    source.write_text("1\n00:00:00,100 --> 00:00:01,000\nOld caption\n", encoding="utf-8")
    cue_file = tmp_path / "legacy.srt.cues.json"
    cue_file.write_text(json.dumps([cue]), encoding="utf-8")
    (tmp_path / "en.json").write_text("User file", encoding="utf-8")
    (tmp_path / "manifest.json").write_text("User manifest", encoding="utf-8")
    job = {
        "id": "legacy-edit",
        "settings": DownloadSettings(caption_mode="sidecar", caption_source="local").to_dict(),
        "media_path": str(source),
        "output": str(source),
        "caption_paths": [str(source)],
        "cues_path": str(cue_file),
        "destination": str(tmp_path),
        "caption_language_result": "en",
    }
    events = []
    reexport(job, [{**cue, "text": "Corrected caption"}], threading.Event(), events.append)
    assert (tmp_path / "en.json").read_text(encoding="utf-8") == "User file"
    assert (tmp_path / "manifest.json").read_text(encoding="utf-8") == "User manifest"
    assert Path(events[-1]["cues_path"]).parent == tmp_path / ".videodock-captions" / job["id"]
    assert "Old caption" in source.read_text(encoding="utf-8")
