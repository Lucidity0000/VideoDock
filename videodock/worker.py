from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time

from .engine import download, extract, inspect_urls
from .models import summarize_info
from .processes import Cancelled
from .windows_job import WindowsJob


def control_lines():
    """Keep Windows control reads from blocking native runtime initialization.

    NumPy initialization can deadlock while another thread blocks on stdin.
    Poll the inherited pipe before reading, including the first request, so
    buffered cancellation/subsequent requests cannot be lost. ReadFile only
    receives bytes already available, with no long-held stdin/pipe locks.
    """
    if os.name != "nt":
        yield from sys.stdin
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    block = ctypes.create_string_buffer(4096)
    pending = b""
    while True:
        available = wintypes.DWORD()
        if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            error = ctypes.get_last_error()
            if error not in {109, 232}:
                raise OSError(error, "Cannot inspect worker control pipe")
            break
        if not available.value:
            time.sleep(0.025)
            continue
        read = wintypes.DWORD()
        if not kernel.ReadFile(handle, block, min(len(block), available.value), ctypes.byref(read), None):
            error = ctypes.get_last_error()
            if error not in {109, 232}:
                raise OSError(error, "Cannot read worker control pipe")
            break
        if not read.value:
            break
        pending += block.raw[: read.value]
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            yield line.decode("utf-8").rstrip("\r")
    if pending:
        yield pending.decode("utf-8")


def main() -> int:
    # PyInstaller's console bootloader can reset standard stream encodings on
    # Windows even when PYTHONIOENCODING is set. The GUI protocol is always UTF-8.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    lifetime = WindowsJob()
    lifetime.assign_current()
    # Keep this handle open until process exit; the OS closes it and stops any remaining children.
    # stdin first carries the request, then optional cancellation messages.
    controls = control_lines()
    request = json.loads(next(controls))
    cancel = threading.Event()
    requests = queue.Queue()

    def read_control():
        for line in controls:
            if line.strip() == "cancel":
                cancel.set()
            elif line.strip().startswith("{"):
                requests.put(json.loads(line))
        requests.put(None)

    threading.Thread(target=read_control, daemon=True).start()

    def emit(event: dict):
        # Escaping non-ASCII characters adds a second layer of protection without
        # losing Unicode after the GUI decodes the JSON.
        print(json.dumps(event, ensure_ascii=True), flush=True)

    try:
        if request["action"] == "caption_service":
            from pathlib import Path

            from .captions import CaptionEngine, WaitingForModel, reexport

            engine = CaptionEngine()
            while request is not None:
                identifier = request["job"]["id"]

                def caption_emit(event, identifier=identifier):
                    emit({**event, "job_id": identifier})

                try:
                    if "cues" in request:
                        reexport(request["job"], request["cues"], cancel, caption_emit)
                    else:
                        engine.generate(request["job"], Path(request["model_folder"]), cancel, caption_emit)
                except WaitingForModel as exc:
                    caption_emit({"type": "caption_waiting", "message": str(exc), "model_id": exc.model_id})
                except Cancelled:
                    caption_emit({"type": "cancelled"})
                except Exception as exc:
                    caption_emit({"type": "error", "message": str(exc)})
                cancel.clear()
                caption_emit({"type": "caption_idle"})
                request = requests.get()
        elif request["action"] == "model_download":
            from pathlib import Path

            from .caption_models import download_model

            download_model(Path(request["model_folder"]), request["model_id"], cancel, emit)
        elif request["action"] == "inspect":
            inspect_urls(request["urls"], cancel, emit)
        elif request["action"] == "detail":
            emit({"type": "detail", "item": summarize_info(extract(request["url"], cancel))})
            emit({"type": "done"})
        elif request["action"] == "download":
            download(request["job"], cancel, emit)
        elif request["action"] == "update_check":
            from .updater import check_update

            emit({"type": "update_available", "release": check_update()})
        elif request["action"] == "update_install":
            from .updater import install_update

            emit({"type": "update_installed", "path": str(install_update(request["release"]))})
        else:
            raise ValueError("Unknown worker request")
        return 0
    except Cancelled:
        emit({"type": "cancelled"})
        return 2
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
