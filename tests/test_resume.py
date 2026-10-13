import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from videodock.engine import download
from videodock.media import validate_output
from videodock.models import DownloadSettings
from videodock.processes import Cancelled


def test_real_partial_download_resumes_with_http_range(sample_media, tmp_path):
    contents = (sample_media / "media.mp4").read_bytes() + bytes(3 * 1024 * 1024)
    ranges = []

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", len(contents))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        def do_GET(self):
            start = 0
            header = self.headers.get("Range", "")
            if header:
                start = int(header.removeprefix("bytes=").split("-")[0])
                ranges.append(start)
            self.send_response(206 if header else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", len(contents) - start)
            self.send_header("Accept-Ranges", "bytes")
            if header:
                self.send_header("Content-Range", f"bytes {start}-{len(contents) - 1}/{len(contents)}")
            self.end_headers()
            try:
                for index in range(start, len(contents), 64 * 1024):
                    self.wfile.write(contents[index : index + 64 * 1024])
                    self.wfile.flush()
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    job = {
        "id": "resume",
        "url": f"http://127.0.0.1:{server.server_port}/sample.mp4",
        "title": "Resume sample",
        "destination": str(tmp_path),
        "playlist_index": 0,
        "settings": DownloadSettings().to_dict(),
    }
    cancel = threading.Event()

    def interrupt(event):
        if event["type"] == "progress" and event.get("bytes", 0) > 128 * 1024:
            cancel.set()

    try:
        with pytest.raises(Cancelled):
            download(job, cancel, interrupt)
        partials = list((tmp_path / ".videodock" / "resume").glob("*.part"))
        assert partials and partials[0].stat().st_size > 0
        events = []
        download(job, threading.Event(), events.append)
        output = Path(next(event["output"] for event in events if event["type"] == "completed"))
        validate_output(output, DownloadSettings())
        assert any(start > 0 for start in ranges), "The retry did not request the preserved partial data"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
