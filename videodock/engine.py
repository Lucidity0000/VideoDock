from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path

from .dependencies import engine_command, find_binary, runtime
from .media import MIN_FREE, check_destination, process_media, publish
from .models import DownloadSettings, summarize_info, validate_url
from .processes import Cancelled, run_lines


def base_args() -> list[str]:
    args = engine_command() + [
        "--ignore-config",
        "--no-color",
        "--socket-timeout",
        "30",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--encoding",
        "utf-8",
        "--output-na-placeholder",
        "null",
    ]
    js = runtime()
    if js:
        args += ["--js-runtimes", f"{js[0]}:{js[1]}"]
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg:
        args += ["--ffmpeg-location", str(Path(ffmpeg).parent)]
    return args


def extract(url: str, cancel: threading.Event, *, flat: bool = False) -> dict:
    command = base_args() + ["--dump-single-json", "--skip-download", "--quiet"]
    command += ["--flat-playlist", "--yes-playlist", "--ignore-errors"] if flat else ["--no-playlist"]
    command += ["--", validate_url(url)]
    result: list[dict] = []

    def on_line(line: str):
        if line.startswith("{"):
            result.append(json.loads(line))

    run_lines(command, cancel, on_line, timeout=300)
    if not result:
        raise ValueError("No playable videos were found. The source may be private, removed or unavailable.")
    return result[-1]


def inspect_urls(urls: list[str], cancel: threading.Event, emit) -> None:
    for url in urls:
        try:
            info = extract(url, cancel, flat=True)
            entries = info.get("entries")
            if entries is not None:
                title = info.get("title") or "Playlist"
                unavailable = 0
                for index, entry in enumerate(entries, 1):
                    if entry is None:
                        unavailable += 1
                        continue
                    item = summarize_info(entry, title, entry.get("playlist_index") or index)
                    item["playlist_key"] = url
                    emit({"type": "item", "item": item})
                if unavailable:
                    emit(
                        {
                            "type": "warning",
                            "message": f"{title}: {unavailable} unavailable entries were skipped.",
                        }
                    )
            else:
                emit({"type": "item", "item": summarize_info(info)})
        except Cancelled:
            raise
        except Exception as exc:
            emit({"type": "inspection_error", "url": url, "message": str(exc)})
    emit({"type": "done"})


def format_selector(settings: DownloadSettings) -> str:
    limit = f"[height<=?{settings.height}]" if settings.height else ""
    if settings.format in {"mp3", "m4a"}:
        return "bestaudio/best"
    if settings.format == "mp4":
        compatible = (
            f"bv[vcodec^=avc1]{limit}+ba[acodec^=mp4a]/b[ext=mp4][vcodec^=?avc1][acodec^=?mp4a]{limit}"
        )
    else:
        compatible = f"bv[ext=webm]{limit}+ba[ext=webm]/b[ext=webm]{limit}"
    if settings.allow_conversion:
        compatible += f"/bv{limit}+ba/b{limit}/bv{limit}"
    return compatible


def download(job: dict, cancel: threading.Event, emit) -> None:
    settings = DownloadSettings.from_dict(job["settings"])
    settings.validate()
    destination = Path(job["destination"]).resolve()
    check_destination(destination)
    for name in ("ffmpeg", "ffprobe"):
        if not find_binary(name):
            raise ValueError(f"{name} is missing. Open Dependencies for setup instructions.")
    emit({"type": "status", "status": "inspecting"})
    info = extract(job["url"], cancel)
    emit({"type": "title", "title": info.get("title", job["title"])})
    deferred = settings.deferred_captions or (
        job.get("split_stages", False) and settings.caption_mode != "none" and settings.caption_source != "off"
    )
    if deferred or settings.caption_source == "off":
        settings = replace(settings, caption_mode="none")
    caption_key = "automatic_captions" if settings.caption_source == "auto" else "subtitles"
    if settings.caption_mode != "none" and settings.caption_language not in (info.get(caption_key) or {}):
        languages = ", ".join(sorted((info.get(caption_key) or {}).keys())[:20]) or "none"
        raise ValueError(
            f"{settings.caption_language} {settings.caption_source} captions are unavailable. "
            f"Available languages: {languages}. Choose another language/source or turn captions off."
        )
    work = destination / ".videodock" / job["id"]
    work.mkdir(parents=True, exist_ok=True)
    prefix = f"{job['playlist_index']:03d} - " if job.get("playlist_index") else ""
    template = prefix + settings.filename_template + ".%(ext)s"
    command = base_args() + [
        "--no-playlist",
        "--continue",
        "--part",
        "--no-overwrites",
        "--windows-filenames",
        "--trim-filenames",
        "200",
        "--format",
        format_selector(settings),
        "--merge-output-format",
        "mkv",
        "--output",
        str(work / template),
        "--newline",
        "--progress",
        "--quiet",
        "--progress-template",
        'download:VD_PROGRESS:{"bytes":%(progress.downloaded_bytes)j,'
        '"total":%(progress.total_bytes,progress.total_bytes_estimate)j,'
        '"speed":%(progress.speed)j,"eta":%(progress.eta)j}',
        "--print",
        "after_move:VD_FILE:%(filepath)j",
        "--progress-template",
        "postprocess:VD_STAGE:%(progress.status)s",
    ]
    if settings.caption_mode != "none":
        command += [
            "--write-auto-subs" if settings.caption_source == "auto" else "--write-subs",
            "--sub-langs",
            settings.caption_language,
            "--sub-format",
            "vtt/srt/best",
            "--convert-subs",
            settings.caption_format,
        ]
    command += ["--", validate_url(job["url"])]
    paths: list[Path] = []
    last_update = 0.0
    emit({"type": "status", "status": "downloading"})

    def on_line(line: str):
        nonlocal last_update
        if line.startswith("VD_FILE:"):
            paths.append(Path(json.loads(line.removeprefix("VD_FILE:"))))
        elif line.startswith("VD_PROGRESS:"):
            progress = json.loads(line.removeprefix("VD_PROGRESS:"))
            if time.monotonic() - last_update < 0.25:
                return
            last_update = time.monotonic()
            total, downloaded = progress.get("total"), progress.get("bytes")
            progress["progress"] = (
                min(100, downloaded / total * 100) if isinstance(total, (int, float)) and total else 0
            )
            emit({"type": "progress", **progress, "stage": "downloading"})
            free = shutil.disk_usage(destination).free
            remaining = max(0, total - downloaded) if isinstance(total, (int, float)) else 0
            if free < max(MIN_FREE, remaining):
                raise ValueError(
                    "The destination is running out of disk space. Free space and retry to resume."
                )
        elif line.startswith("VD_STAGE:"):
            if line.removeprefix("VD_STAGE:") == "started":
                emit({"type": "status", "status": "processing"})
        elif line.startswith("ERROR:") or line.startswith("WARNING:"):
            emit({"type": "warning", "message": line})

    run_lines(command, cancel, on_line)
    if not paths or not paths[-1].is_file():
        raise ValueError("Download finished without a media file. Retry or inspect the source again.")
    source = paths[-1].resolve()
    if not source.is_relative_to(work.resolve()):
        raise ValueError("The downloader returned a file outside its working directory.")
    # Conversion needs room for a second full output alongside the downloaded source.
    check_destination(destination, max(MIN_FREE, source.stat().st_size * 2))
    caption = None
    if settings.caption_mode != "none":
        candidates = sorted(work.glob(f"*.{settings.caption_language}.{settings.caption_format}"))
        if not candidates:
            raise ValueError(
                "The requested captions could not be downloaded. Retry or select another source."
            )
        caption = candidates[0]
    rendered = process_media(source, work, settings, caption, cancel, emit)
    if cancel.is_set():
        raise Cancelled()
    # yt-dlp has sanitized and expanded the template; keep its name when publishing.
    name = source.stem
    output = publish(rendered, destination, name, caption, settings, job["id"])
    try:
        shutil.rmtree(work)
    except OSError:
        emit(
            {"type": "warning", "message": "Download completed, but temporary files could not be cleaned up."}
        )
    emit(
        {
            "type": "media_ready" if deferred else "completed",
            "output": str(output),
            "progress": 100,
            "caption_paths": [
                str(output.with_suffix(f".{settings.caption_language}.{settings.caption_format}"))
            ]
            if caption
            else [],
            "caption_language_result": settings.caption_language if caption else "",
        }
    )
