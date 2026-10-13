from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable

from .dependencies import subprocess_flags
from .windows_job import WindowsJob


class Cancelled(Exception):
    pass


def kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            **subprocess_flags(),
        )
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_lines(
    command: list[str],
    cancel: threading.Event,
    on_line: Callable[[str], None],
    *,
    cwd=None,
    timeout: float | None = None,
) -> None:
    """Drain output continuously, with responsive cancellation even during silent subprocesses."""
    if cancel.is_set():
        raise Cancelled()
    options = subprocess_flags()
    if os.name != "nt":
        options["start_new_session"] = True
    job = WindowsJob()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        **options,
    )
    if os.name == "nt":
        try:
            job.assign(int(process._handle))
        except OSError:
            process.kill()
            job.close()
            raise
    lines: queue.Queue[str | None] = queue.Queue()
    tail: deque[str] = deque(maxlen=12)

    def drain():
        assert process.stdout is not None
        try:
            for line in process.stdout:
                lines.put(line.rstrip("\r\n"))
        finally:
            lines.put(None)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    started = time.monotonic()
    try:
        while True:
            if cancel.is_set():
                raise Cancelled()
            if timeout and time.monotonic() - started > timeout:
                raise TimeoutError("The source did not respond in time. Check the connection and retry.")
            try:
                line = lines.get(timeout=0.15)
            except queue.Empty:
                continue
            if line is None:
                break
            if not line.startswith(("VD_PROGRESS:", "VD_FILE:")) and len(line) < 4000:
                tail.append(line)
            on_line(line)
        code = process.wait(timeout=5)
        if cancel.is_set():
            raise Cancelled()
        if code:
            raise RuntimeError("\n".join(tail) or f"The media tool exited with code {code}.")
    finally:
        if os.name == "nt":
            job.close()
        else:
            kill_tree(process)
        reader.join(timeout=2)
        if process.stdout and not reader.is_alive():
            process.stdout.close()
