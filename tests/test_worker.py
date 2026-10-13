import json
import os
import subprocess
import sys
from pathlib import Path

from videodock.dependencies import subprocess_flags


def test_worker_protocol_overrides_windows_codepage(media_server, tmp_path):
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"

    def run(request):
        result = subprocess.run(
            [sys.executable, "-m", "videodock.worker"],
            input=json.dumps(request, ensure_ascii=False) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=40,
            check=False,
            **subprocess_flags(),
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]

    previews = run({"action": "inspect", "urls": [media_server + "/index.html"]})
    item = next(event["item"] for event in previews if event["type"] == "item")
    assert "測試" in item["title"]
    destination = tmp_path / "下載"
    results = run(
        {
            "action": "download",
            "job": {
                "id": "unicode",
                "url": media_server + "/media.mp4",
                "title": "機器學習基石",
                "destination": str(destination),
                "playlist_index": 0,
                "settings": {},
            },
        }
    )
    output = Path(next(event["output"] for event in results if event["type"] == "completed"))
    assert output.is_file() and output.parent == destination


def test_open_control_pipe_does_not_deadlock_numpy_import():
    """The GUI keeps stdin open for cancellation and the next caption job."""
    code = """
import json, threading
from videodock.worker import control_lines
controls = control_lines()
request = json.loads(next(controls))
threading.Thread(target=lambda: list(controls), daemon=True).start()
import numpy
print(json.dumps({'title': request['title'], 'runtime': numpy.__version__}), flush=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **subprocess_flags(),
    )
    import queue
    import threading

    result = queue.Queue()
    threading.Thread(target=lambda: result.put(process.stdout.readline()), daemon=True).start()
    try:
        process.stdin.write((json.dumps({"title": "中文 runtime"}) + "\n").encode("utf-8"))
        process.stdin.flush()
        line = result.get(timeout=10)
        assert json.loads(line)["title"] == "中文 runtime"
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()
