import hashlib
import io
from types import SimpleNamespace

import pytest

from videodock import updater


def test_engine_checksum_failure_keeps_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "data_directory", lambda: tmp_path)
    monkeypatch.setattr(updater.sys, "platform", "win32")
    (tmp_path / "bin").mkdir()
    target = tmp_path / "bin" / "yt-dlp.exe"
    target.write_bytes(b"existing")
    monkeypatch.setattr(updater, "request", lambda _: io.BytesIO(b"corrupted"))
    release = {
        "url": "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.exe",
        "name": "yt-dlp.exe",
        "sha256": hashlib.sha256(b"expected").hexdigest(),
        "size": 9,
        "version": "2026.08.19",
    }
    with pytest.raises(ValueError, match="checksum"):
        updater.install_update(release)
    assert target.read_bytes() == b"existing"
    assert not target.with_suffix(".exe.new").exists()


def test_verified_update_checks_version_before_replacing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "data_directory", lambda: tmp_path)
    monkeypatch.setattr(updater.sys, "platform", "win32")
    binary = b"verified engine"
    monkeypatch.setattr(updater, "request", lambda _: io.BytesIO(binary))
    monkeypatch.setattr(
        updater.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=0, stdout="2026.08.19\n")
    )
    release = {
        "url": "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.exe",
        "name": "yt-dlp.exe",
        "sha256": hashlib.sha256(binary).hexdigest(),
        "size": len(binary),
        "version": "2026.08.19",
    }
    target = updater.install_update(release)
    assert target.read_bytes() == binary
    release["url"] = "https://example.org/engine.exe"
    with pytest.raises(ValueError, match="official"):
        updater.install_update(release)
