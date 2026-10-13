import threading
from dataclasses import replace
from pathlib import Path

import pytest

from videodock.engine import download, extract, format_selector
from videodock.media import check_destination, process_media, publish, validate_output
from videodock.models import DownloadSettings
from videodock.processes import Cancelled, run_lines


@pytest.mark.parametrize("fmt", ["mp4", "webm", "mp3", "m4a"])
def test_real_conversion_and_container(fmt, sample_media, tmp_path):
    settings = DownloadSettings(format=fmt)
    output = process_media(
        sample_media / "media.mp4", tmp_path, settings, None, threading.Event(), lambda _: None
    )
    info = validate_output(output, settings)
    assert abs(float(info["format"]["duration"]) - 2) < 0.2


@pytest.mark.parametrize("fmt", ["mp4", "webm"])
def test_real_embedded_subtitle_timing(fmt, sample_media, tmp_path):
    import subprocess

    from videodock.dependencies import find_binary, subprocess_flags

    settings = DownloadSettings(format=fmt, caption_mode="embed", caption_format="vtt")
    output = process_media(
        sample_media / "media.mp4",
        tmp_path,
        settings,
        sample_media / "en.vtt",
        threading.Event(),
        lambda _: None,
    )
    extracted = tmp_path / "extracted.srt"
    result = subprocess.run(
        [find_binary("ffmpeg"), "-y", "-v", "error", "-i", str(output), "-map", "0:s:0", str(extracted)],
        capture_output=True,
        timeout=20,
        **subprocess_flags(),
    )
    assert result.returncode == 0, result.stderr.decode()
    text = extracted.read_text(encoding="utf-8")
    assert "00:00:00,200 --> 00:00:01,200" in text
    assert "Hello 世界" in text


def test_real_burned_captions(sample_media, tmp_path):
    import subprocess

    from videodock.dependencies import find_binary, subprocess_flags

    settings = DownloadSettings(caption_mode="burn", caption_format="vtt")
    output = process_media(
        sample_media / "media.mp4",
        tmp_path,
        settings,
        sample_media / "en.vtt",
        threading.Event(),
        lambda _: None,
    )
    info = validate_output(output, settings)
    assert not any(s["codec_type"] == "subtitle" for s in info["streams"])
    # Compare a frame during the cue to a plain re-encode with the same settings.
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    plain = process_media(
        sample_media / "media.mp4",
        plain_dir,
        replace(settings, caption_mode="none"),
        None,
        threading.Event(),
        lambda _: None,
    )
    frames = []
    for path in [plain, output]:
        result = subprocess.run(
            [
                find_binary("ffmpeg"),
                "-v",
                "error",
                "-ss",
                "0.6",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-f",
                "md5",
                "-",
            ],
            capture_output=True,
            timeout=20,
            **subprocess_flags(),
        )
        assert result.returncode == 0
        frames.append(result.stdout)
    assert frames[0] != frames[1]


def test_publish_preserves_existing_files_and_unicode(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    rendered = work / "rendered.mp3"
    rendered.write_bytes(b"new media")
    existing = tmp_path / "中文 [abc].mp3"
    existing.write_bytes(b"existing media")
    caption = work / "captions.srt"
    caption.write_text("1\n00:00:00,200 --> 00:00:01,200\nHello\n")
    settings = DownloadSettings(format="mp3", caption_mode="sidecar")
    output = publish(rendered, tmp_path, "中文 [abc]", caption, settings, "job")
    assert existing.read_bytes() == b"existing media"
    assert output.name == "中文 [abc] (1).mp3"
    assert output.with_suffix(".en.srt").read_text() == caption.read_text()


def test_publish_skips_existing_sidecar_without_overwriting(tmp_path):
    rendered = tmp_path / "rendered.mp3"
    rendered.write_bytes(b"new media")
    existing = tmp_path / "Title.en.srt"
    existing.write_text("existing caption")
    caption = tmp_path / "new.srt"
    caption.write_text("new caption")
    output = publish(
        rendered, tmp_path, "Title", caption, DownloadSettings(format="mp3", caption_mode="sidecar"), "job"
    )
    assert output.name == "Title (1).mp3"
    assert existing.read_text() == "existing caption"
    assert output.with_suffix(".en.srt").read_text() == "new caption"


def test_resolution_limit_is_applied_to_unknown_source_metadata(sample_media, tmp_path):
    output = process_media(
        sample_media / "media.mp4",
        tmp_path,
        DownloadSettings(height=144),
        None,
        threading.Event(),
        lambda _: None,
    )
    info = validate_output(output, DownloadSettings(height=144))
    assert next(s["height"] for s in info["streams"] if s["codec_type"] == "video") == 144


def test_full_and_unwritable_destinations(tmp_path, monkeypatch):
    from collections import namedtuple

    import videodock.media as media

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(media.shutil, "disk_usage", lambda _: usage(100, 99, 1))
    with pytest.raises(ValueError, match="disk space"):
        check_destination(tmp_path)
    monkeypatch.setattr(
        media.tempfile, "NamedTemporaryFile", lambda **_: (_ for _ in ()).throw(PermissionError())
    )
    with pytest.raises(ValueError, match="Cannot write"):
        check_destination(tmp_path)


def test_format_constraints_and_real_conversion_requirement(sample_media, tmp_path):
    selector = format_selector(DownloadSettings(height=720, allow_conversion=False))
    assert "height<=?720" in selector and "vcodec^=avc1" in selector
    assert "/bv[height<=?720]+ba" not in selector
    with pytest.raises(ValueError, match="Compatible"):
        process_media(
            sample_media / "media.mp4",
            tmp_path,
            DownloadSettings(format="webm", allow_conversion=False),
            None,
            threading.Event(),
            lambda _: None,
        )


def test_unavailable_caption_is_actionable(media_server, tmp_path):
    job = {
        "id": "unavailable",
        "url": media_server + "/media.mp4",
        "title": "Test",
        "destination": str(tmp_path),
        "settings": DownloadSettings(caption_mode="sidecar").to_dict(),
        "playlist_index": 0,
    }
    with pytest.raises(ValueError, match="en creator captions are unavailable"):
        download(job, threading.Event(), lambda _: None)


def test_local_inspect_download_and_mp3_captions(media_server, tmp_path):
    info = extract(media_server + "/index.html", threading.Event())
    assert info["subtitles"].get("en")
    events = []
    settings = DownloadSettings(format="mp3", caption_mode="sidecar")
    job = {
        "id": "local",
        "url": media_server + "/index.html",
        "title": "Test",
        "destination": str(tmp_path),
        "settings": settings.to_dict(),
        "playlist_index": 7,
    }
    download(job, threading.Event(), events.append)
    completed = next(event for event in events if event["type"] == "completed")
    output = Path(completed["output"])
    assert output.name.startswith("007 - ")
    validate_output(output, settings)
    assert "00:00:00,200 --> 00:00:01,200" in output.with_suffix(".en.srt").read_text(encoding="utf-8")
    assert not (tmp_path / ".videodock" / "local").exists()


def test_silent_process_cancels_promptly():
    import sys
    import time

    event = threading.Event()
    timer = threading.Timer(0.25, event.set)
    timer.start()
    start = time.monotonic()
    with pytest.raises(Cancelled):
        run_lines([sys.executable, "-c", "import time; time.sleep(60)"], event, lambda _: None)
    assert time.monotonic() - start < 4
    timer.join()
