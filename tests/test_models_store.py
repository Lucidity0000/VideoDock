from dataclasses import replace
from pathlib import Path

import pytest

from videodock.models import DownloadSettings, canonical_url, parse_urls, safe_component, validate_template


def item(url="https://youtu.be/abc", title="測試", **kwargs):
    return {"url": url, "title": title, **kwargs}


def test_urls_and_youtube_duplicates():
    assert parse_urls(
        "\ufeff# Comment\nhttps://youtu.be/abc\nhttps://youtu.be/abc https://example.org/video"
    ) == ["https://youtu.be/abc", "https://example.org/video"]
    assert canonical_url("https://www.youtube.com/watch?v=abc&list=playlist") == canonical_url(
        "https://youtu.be/abc?t=4"
    )
    assert canonical_url("https://youtube.com/shorts/abc") == "youtube:abc"
    with pytest.raises(ValueError):
        parse_urls("file:///C:/secret")
    with pytest.raises(ValueError):
        parse_urls("https://user:password@example.org/video")


@pytest.mark.parametrize("value", ["../%(id)s", "C:\\%(id)s", "%(title)s", "%(unknown)s [%(id)s]", "%(id)s%"])
def test_unsafe_templates(value):
    with pytest.raises(ValueError):
        validate_template(value)


def test_unicode_template_and_folder():
    validate_template("測試 %(title).160s [%(id)s]")
    assert safe_component("CON") == "_CON"
    assert safe_component("課程/中文: 2026") == "課程_中文_ 2026"


def test_mp3_caption_rules():
    with pytest.raises(ValueError, match="separate"):
        DownloadSettings(format="mp3", caption_mode="embed").validate()
    DownloadSettings(format="mp3", caption_mode="sidecar").validate()


def test_persistence_order_overrides_and_recovery(store, tmp_path):
    settings = DownloadSettings()
    store.enqueue(
        [item(playlist="課程", index=2), item("https://youtu.be/def", playlist="課程", index=5)],
        settings,
        str(tmp_path),
        {1: replace(settings, format="mp3")},
    )
    jobs = store.jobs()
    assert [job["playlist_index"] for job in jobs] == [2, 5]
    assert jobs[1]["settings"]["format"] == "mp3"
    assert Path(jobs[0]["destination"]).name == "課程"
    store.update(jobs[0]["id"], status="processing", progress=42, attempts=1)
    assert store.recover() == 1
    job = store.get(jobs[0]["id"])
    assert job["status"] == "queued" and job["progress"] == 42
    assert job["attempts"] == 1
    store.set_preference("destination", "中文")
    assert store.preference("destination") == "中文"


def test_duplicates_skip_only_pending_or_existing_outputs(store, tmp_path):
    settings = DownloadSettings()
    assert store.enqueue([item()], settings, str(tmp_path)) == (1, 0)
    assert store.enqueue([item("https://youtube.com/watch?v=abc")], settings, str(tmp_path)) == (0, 1)
    job = store.jobs()[0]
    output = tmp_path / "complete.mp4"
    output.write_bytes(b"media")
    store.update(job["id"], status="completed", output=str(output))
    assert store.enqueue([item()], settings, str(tmp_path)) == (0, 1)
    output.unlink()
    assert store.enqueue([item()], settings, str(tmp_path)) == (1, 0)
    assert store.enqueue([item()], replace(settings, format="mp3"), str(tmp_path)) == (1, 0)


def test_failed_retry_and_atomic_batch(store, tmp_path):
    settings = DownloadSettings()
    with pytest.raises(ValueError):
        store.enqueue(
            [item(), item("https://youtu.be/def")],
            settings,
            str(tmp_path),
            {1: replace(settings, format="invalid")},
        )
    assert store.jobs() == []
    store.enqueue([item()], settings, str(tmp_path))
    job_id = store.jobs()[0]["id"]
    store.update(job_id, status="failed", error="Unavailable", attempts=2)
    store.retry(job_id)
    assert store.get(job_id)["status"] == "queued"
    assert store.get(job_id)["attempts"] == 2
