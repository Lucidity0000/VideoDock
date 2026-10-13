import os
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOCK_DATA_DIR", str(tmp_path / "appdata"))


@pytest.fixture
def store(tmp_path):
    from videodock.store import Store

    result = Store(tmp_path / "queue.sqlite3")
    yield result
    result.close()


@pytest.fixture(scope="session")
def sample_media(tmp_path_factory):
    from videodock.dependencies import find_binary, subprocess_flags

    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg or not find_binary("ffprobe"):
        pytest.skip("Integration checks require FFmpeg and ffprobe; run tools/fetch_dependencies.py.")
    root = tmp_path_factory.mktemp("media")
    source = root / "media.mp4"
    result = subprocess.run(
        [
            ffmpeg,
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
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        capture_output=True,
        timeout=30,
        **subprocess_flags(),
    )
    assert result.returncode == 0, result.stderr.decode()
    (root / "en.vtt").write_text("WEBVTT\n\n00:00:00.200 --> 00:00:01.200\nHello 世界\n", encoding="utf-8")
    (root / "index.html").write_text(
        "<html><head><title>Unicode 測試</title></head><body><video controls>"
        '<source src="media.mp4" type="video/mp4">'
        '<track kind="subtitles" src="en.vtt" srclang="en" label="English">'
        "</video></body></html>",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def media_server(sample_media):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(sample_media), **kwargs)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def wait_until(app, condition, timeout=30):
    import time

    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert condition(), "Timed out waiting for background operation"
