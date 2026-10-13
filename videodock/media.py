from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .dependencies import find_binary, subprocess_flags
from .languages import container_language
from .models import DownloadSettings
from .processes import run_lines

MIN_FREE = 64 * 1024 * 1024


def check_destination(destination: Path, required: int = MIN_FREE) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".videodock-write-", dir=destination):
            pass
        free = shutil.disk_usage(destination).free
        if free < required:
            raise ValueError(
                f"Not enough disk space in {destination}. Free at least {required / 1024**2:.0f} MB."
            )
    except PermissionError as exc:
        raise ValueError(
            f"Cannot write to {destination}. Choose another destination or change folder permissions."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Destination is unavailable: {destination}. {exc}") from exc


def probe(path: Path) -> dict:
    ffprobe = find_binary("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is missing. Add it alongside ffmpeg in vendor/ or on PATH.")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        **subprocess_flags(),
    )
    if result.returncode:
        raise RuntimeError(f"Output validation failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def conversion_args(info: dict, settings: DownloadSettings, caption: Path | list[dict] | None) -> list[str]:
    streams = info.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    if settings.format in {"mp3", "m4a"}:
        if not audio:
            raise ValueError("This source has no audio track.")
        return [
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "libmp3lame" if settings.format == "mp3" else "aac",
            "-b:a",
            f"{settings.audio_bitrate}k",
        ]
    if not video:
        raise ValueError("This source has no video track. Choose MP3 or M4A instead.")
    mp4 = settings.format == "mp4"
    video_compatible = video["codec_name"] == "h264" if mp4 else video["codec_name"] in {"vp8", "vp9", "av1"}
    audio_compatible = not audio or (
        audio["codec_name"] == "aac" if mp4 else audio["codec_name"] in {"opus", "vorbis"}
    )
    if not settings.allow_conversion and not (video_compatible and audio_compatible):
        raise ValueError("Compatible streams are unavailable. Enable conversion or choose another format.")
    burn = settings.caption_mode == "burn" and caption is not None
    scale = settings.height and int(video.get("height") or 0) > settings.height
    if scale and not settings.allow_conversion:
        raise ValueError(
            "This stream exceeds the resolution limit. Enable conversion or choose a higher limit."
        )
    args = ["-map", "0:v:0", "-map", "0:a:0?"]
    if video_compatible and not burn and not scale:
        args += ["-c:v", "copy"]
    elif mp4:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
    else:
        args += ["-c:v", "libvpx-vp9", "-crf", "31", "-b:v", "0", "-row-mt", "1"]
    args += ["-c:a", "copy" if audio_compatible else ("aac" if mp4 else "libopus")]
    if burn:
        args += ["-vf", f"subtitles=captions.{caption.suffix.lstrip('.')}"]
    elif settings.caption_mode == "embed" and caption:
        tracks = caption if isinstance(caption, list) else [{"language": settings.caption_language}]
        for index, track in enumerate(tracks):
            tag = track["language"]
            args += [
                "-map",
                f"{index + 1}:0",
                f"-metadata:s:s:{index}",
                f"language={container_language(tag) if mp4 else tag}",
                f"-metadata:s:s:{index}",
                f"title={track.get('title', tag)}",
                f"-disposition:s:{index}",
                "default"
                if tag == settings.default_language or (not settings.default_language and index == 0)
                else "0",
            ]
        args += ["-c:s", "mov_text" if mp4 else "webvtt"]
    if scale:
        scale_filter = f"scale=-2:{settings.height}"
        if "-vf" in args:
            index = args.index("-vf") + 1
            args[index] = scale_filter + "," + args[index]
        else:
            args += ["-vf", scale_filter]
    if mp4:
        args += ["-movflags", "+faststart"]
    return args


def validate_output(path: Path, settings: DownloadSettings) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The media tool did not produce an output file.")
    info = probe(path)
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    containers = set(info.get("format", {}).get("format_name", "").split(","))
    if settings.format == "mp4" and (
        not video or video[0]["codec_name"] != "h264" or "mp4" not in containers
    ):
        raise ValueError("MP4 validation failed: expected H.264 video in an MP4 container.")
    if settings.format == "webm" and (
        not video or video[0]["codec_name"] not in {"vp8", "vp9", "av1"} or "webm" not in containers
    ):
        raise ValueError("WebM validation failed: expected VP8, VP9 or AV1 in a WebM container.")
    if settings.format in {"mp3", "m4a"} and (
        video or not audio or audio[0]["codec_name"] != ("mp3" if settings.format == "mp3" else "aac")
    ):
        raise ValueError("Audio output validation failed.")
    if settings.caption_mode == "embed" and not any(s.get("codec_type") == "subtitle" for s in streams):
        raise ValueError("The selected captions were not embedded in the output.")
    return info


def process_media(
    source: Path, work: Path, settings: DownloadSettings, caption: Path | None, cancel: threading.Event, emit
) -> Path:
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is missing. Add ffmpeg and ffprobe to vendor/ or install on PATH.")
    info = probe(source)
    if caption and settings.caption_mode == "burn":
        fixed = work / f"captions{caption.suffix}"
        if caption != fixed:
            shutil.copyfile(caption, fixed)
        caption = fixed
    target = work / f"rendered.{settings.format}"
    command = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    if caption and settings.caption_mode == "embed":
        for item in caption if isinstance(caption, list) else [{"path": caption}]:
            command += ["-i", str(item["path"])]
    command += conversion_args(info, settings, caption)
    command += ["-progress", "pipe:1", "-nostats", str(target)]
    duration = float(info.get("format", {}).get("duration") or 0)
    emit({"type": "status", "status": "processing", "message": "Converting / merging / adding captions"})

    def on_line(line: str):
        if line.startswith("out_time_us=") and duration:
            try:
                progress = min(99.9, int(line.split("=", 1)[1]) / 1_000_000 / duration * 100)
                emit({"type": "progress", "progress": progress, "stage": "processing"})
            except ValueError:
                pass

    run_lines(command, cancel, on_line, cwd=work)
    result = validate_output(target, settings)
    if isinstance(caption, list):
        subtitles = [stream for stream in result["streams"] if stream.get("codec_type") == "subtitle"]
        if len(subtitles) != len(caption):
            raise ValueError("Multi-language export is missing one or more subtitle tracks.")
    return target


def publish(
    rendered: Path,
    destination: Path,
    name: str,
    caption: Path | list[dict] | None,
    settings: DownloadSettings,
    job_id: str,
) -> Path:
    """Reserve a filename exclusively before replacing it, so existing media is never overwritten."""
    target = destination / f"{name}.{settings.format}"
    counter = 1
    sidecar = None
    while True:
        reserved = False
        try:
            with target.open("xb"):
                pass
            reserved = True
            if caption:
                sidecar = target.with_suffix(f".{settings.caption_language}.{settings.caption_format}")
                with sidecar.open("xb"):
                    pass
            break
        except FileExistsError:
            if reserved:
                target.unlink(missing_ok=True)
            target = destination / f"{name} ({counter}).{settings.format}"
            counter += 1
        except OSError:
            if reserved:
                target.unlink(missing_ok=True)
            raise
    try:
        if caption and sidecar:
            # Stage first; never leave a completed job with missing captions.
            temporary = destination / f".{job_id}.caption.tmp"
            shutil.copyfile(caption, temporary)
            os.replace(temporary, sidecar)
        os.replace(rendered, target)
    except BaseException:
        target.unlink(missing_ok=True)
        if caption:
            (destination / f".{job_id}.caption.tmp").unlink(missing_ok=True)
            if sidecar:
                sidecar.unlink(missing_ok=True)
        raise
    return target
