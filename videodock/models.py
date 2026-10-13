from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

ACTIVE = {
    "inspecting",
    "downloading",
    "processing",
    "cancelling",
    "preparing",
    "transcribing",
    "translating",
    "exporting",
}
CAPTION_PENDING = {"caption_queued", "translation_queued", "waiting_model"}
TERMINAL = {"completed", "partial", "failed", "cancelled"}
DEFAULT_TEMPLATE = "%(title).160s [%(id)s]"


def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Use a complete http:// or https:// link: {value[:100]}")
    if parsed.username or parsed.password:
        raise ValueError("Links containing passwords are not supported.")
    return value


def parse_urls(text: str) -> list[str]:
    urls: list[str] = []
    for line in text.lstrip("\ufeff").splitlines():
        if line.strip().startswith("#"):
            continue
        for word in line.split():
            url = validate_url(word)
            if url not in urls:
                urls.append(url)
    if not urls:
        raise ValueError("Paste at least one link, or import a text file with one link per line.")
    return urls


def canonical_url(url: str) -> str:
    if url.startswith("file:"):
        return url.casefold()
    parsed = urlparse(validate_url(url))
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        return "youtube:" + parsed.path.strip("/").split("/")[0]
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if not video_id and parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = parsed.path.split("/")[2]
        if video_id:
            return "youtube:" + video_id
    return urlunparse(parsed._replace(fragment=""))


def safe_component(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:120]
    if not value:
        return "Untitled"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", value):
        value = "_" + value
    return value


def validate_template(template: str) -> None:
    if not template or any(char in template for char in "/\\\r\n\x00") or ".." in template:
        raise ValueError("The filename template must be a filename, without folders or '..'.")
    allowed = {"title", "id", "uploader", "channel", "upload_date", "height"}
    tokens = re.findall(r"%\(([^)]+)\)(?:\.\d+)?[sd]", template)
    remaining = re.sub(r"%\([^)]+\)(?:\.\d+)?[sd]", "", template).replace("%%", "")
    if "%" in remaining or any(token not in allowed for token in tokens):
        raise ValueError("Use title, id, uploader, channel, upload_date or height template fields.")
    if "id" not in tokens:
        raise ValueError("Include %(id)s in the filename template to prevent title collisions.")


@dataclass(frozen=True)
class DownloadSettings:
    format: str = "mp4"
    height: int = 1080  # 0 means best available
    audio_bitrate: int = 192
    caption_mode: str = "none"  # none, sidecar, embed, burn
    caption_source: str = "creator"  # creator, auto
    caption_language: str = "en"
    caption_format: str = "srt"
    caption_model: str = "small"
    model_revision: str = ""
    alignment_model: str = ""
    alignment_revision: str = ""
    spoken_language: str = "auto"
    caption_device: str = "cpu"
    cpu_fallback: bool = True
    caption_line_length: int = 42
    caption_max_duration: int = 6
    chinese_script: str = "original"  # original, zh-Hans, zh-Hant
    translate: bool = False
    translation_source_language: str = "auto"
    target_languages: tuple[str, ...] = ()
    translation_model: str = "m2m100-418m"
    translation_revision: str = ""
    keep_original: bool = True
    bilingual_language: str = ""
    bilingual_order: str = "source_first"
    track_order: tuple[str, ...] = ()
    default_language: str = ""
    burn_language: str = ""
    burn_font: str = "Microsoft JhengHei"
    burn_size: int = 24
    burn_color: str = "#FFFFFF"
    burn_position: str = "bottom"
    subtitle_import: str = ""
    allow_conversion: bool = True
    filename_template: str = DEFAULT_TEMPLATE

    def validate(self) -> None:
        if self.format not in {"mp4", "webm", "mp3", "m4a"}:
            raise ValueError("Choose MP4, WebM, MP3 or M4A.")
        if self.height not in {0, 144, 240, 360, 480, 720, 1080, 1440, 2160, 4320}:
            raise ValueError("Choose a supported resolution.")
        if self.audio_bitrate not in {96, 128, 192, 256, 320}:
            raise ValueError("Choose an audio quality preset.")
        if self.caption_mode not in {"none", "sidecar", "embed", "burn"}:
            raise ValueError("Choose a caption mode.")
        if self.caption_source not in {
            "off",
            "creator",
            "auto",
            "local",
            "fallback_creator",
            "fallback_auto",
            "import",
        } or self.caption_format not in {"srt", "vtt"}:
            raise ValueError("Choose a caption source and SRT or VTT format.")
        if self.caption_mode != "none":
            if self.caption_source in {"creator", "auto"} and not re.fullmatch(
                r"[A-Za-z0-9_-]{1,40}", self.caption_language
            ):
                raise ValueError("Use an exact caption language code such as en or zh-Hant.")
            if self.format in {"mp3", "m4a"} and self.caption_mode in {"embed", "burn"}:
                raise ValueError("Audio downloads save captions as separate SRT/VTT files.")
        validate_template(self.filename_template)
        from .caption_models import model_spec

        if model_spec(self.caption_model, self.model_revision).get("task", "speech") != "speech":
            raise ValueError("Choose a speech model from the built-in catalog.")
        if self.alignment_model:
            if model_spec(self.alignment_model, self.alignment_revision).get("task") != "alignment":
                raise ValueError("Choose an alignment model from the built-in catalog.")
            if self.caption_source == "import":
                raise ValueError("Forced alignment needs media audio. Choose local captions or a YouTube caption source.")
        if self.caption_device not in {"cpu", "cuda"}:
            raise ValueError("Choose CPU or NVIDIA GPU.")
        if not re.fullmatch(r"auto|[a-z]{2,3}", self.spoken_language):
            raise ValueError("Spoken language must be auto or a language code such as en, zh, or ja.")
        if self.caption_model == "distil-v3.5" and self.spoken_language not in {"auto", "en"}:
            raise ValueError("Distil-Whisper is English-only. Choose English or another model.")
        if not 20 <= self.caption_line_length <= 100 or not 2 <= self.caption_max_duration <= 15:
            raise ValueError("Caption lines must be 20–100 characters; cue duration must be 2–15 seconds.")
        from .languages import model_language, supported_targets

        if self.chinese_script not in {"original", "zh-Hans", "zh-Hant"}:
            raise ValueError("Choose original, Simplified or Traditional Chinese.")
        if self.translation_source_language != "auto" and not re.fullmatch(
            r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", self.translation_source_language
        ):
            raise ValueError("Use a source language tag such as en, ja or zh-Hant.")
        if model_spec(self.translation_model, self.translation_revision).get("task") != "translation":
            raise ValueError("Choose a translation model from the catalog.")
        if self.translate:
            if self.caption_mode == "none" or self.caption_source == "off":
                raise ValueError("Enable captions before translating subtitles.")
            if not self.target_languages or len(set(self.target_languages)) != len(self.target_languages):
                raise ValueError("Select distinct target languages.")
            if any(lang not in supported_targets() for lang in self.target_languages):
                raise ValueError("A target language is unsupported by this translation model.")
            if self.translation_source_language != "auto":
                model_language(self.translation_source_language)
        if self.caption_source == "import" and not self.subtitle_import:
            raise ValueError("Choose an SRT or VTT source file.")
        if self.bilingual_language and (
            not self.translate or self.bilingual_language not in self.target_languages
        ):
            raise ValueError("Choose a selected translation for bilingual subtitles.")
        if self.bilingual_order not in {"source_first", "translation_first"}:
            raise ValueError("Choose the bilingual text order.")
        if len(set(self.track_order)) != len(self.track_order):
            raise ValueError("Track order must not contain duplicate languages.")
        if self.burn_language and self.burn_language not in (*self.target_languages, "source", "bilingual"):
            raise ValueError("Choose source, bilingual, or a selected target to burn.")
        if self.burn_language == "bilingual" and not self.bilingual_language:
            raise ValueError("Choose a bilingual pair before burning it.")
        if self.burn_position not in {"bottom", "middle", "top"} or not 10 <= self.burn_size <= 96:
            raise ValueError("Choose a burn position and font size of 10–96.")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", self.burn_color):
            raise ValueError("Subtitle color must be a hex color such as #FFFFFF.")
        if not self.burn_font.strip() or any(c in self.burn_font for c in ",\r\n\\"):
            raise ValueError("Choose a valid subtitle font.")

    @property
    def uses_local(self) -> bool:
        return self.caption_mode != "none" and self.caption_source in {
            "local",
            "fallback_creator",
            "fallback_auto",
        }

    @property
    def deferred_captions(self) -> bool:
        return (
            self.caption_mode != "none"
            and self.caption_source != "off"
            and (
                self.uses_local
                or self.translate
                or self.chinese_script != "original"
                or self.caption_source == "import"
            )
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> DownloadSettings:
        fields = {key: val for key, val in value.items() if key in cls.__dataclass_fields__}
        for key in ("target_languages", "track_order"):
            if key in fields:
                fields[key] = tuple(fields[key])
        return cls(**fields)


def parse_intervals(text: str) -> list[tuple[int, int]]:
    """Inclusive original playlist positions; parsing never allocates a huge range."""
    if not text.strip():
        raise ValueError("Enter playlist positions, for example 1-5, 8, 12-20.")
    ranges = []
    for token in text.split(","):
        match = re.fullmatch(r"\s*([1-9]\d*)\s*(?:-\s*([1-9]\d*)\s*)?", token)
        if not match:
            raise ValueError("Use positive positions and inclusive ranges, for example 1-5, 8, 12-20.")
        start = int(match[1])
        end = int(match[2] or match[1])
        if end < start:
            raise ValueError("A range must end at or after its starting position.")
        ranges.append((start, end))
    return ranges


def duplicate_key(url: str, settings: DownloadSettings, destination: str) -> str:
    payload = [canonical_url(url), settings.to_dict(), str(Path(destination).resolve()).casefold()]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def summarize_info(info: dict, playlist: str = "", index: int = 0) -> dict:
    url = info.get("webpage_url") or info.get("original_url") or info.get("url", "")
    if not str(url).startswith(("http://", "https://")) and info.get("id"):
        if "youtube" in str(info.get("extractor_key", info.get("ie_key", ""))).lower():
            url = f"https://www.youtube.com/watch?v={info['id']}"
    formats = info.get("formats") or []
    return {
        "id": info.get("id", ""),
        "url": url,
        "title": info.get("title") or "Unavailable video",
        "duration": info.get("duration"),
        "uploader": info.get("uploader", ""),
        "thumbnail": info.get("thumbnail")
        or next((item.get("url") for item in reversed(info.get("thumbnails") or []) if item.get("url")), ""),
        "heights": sorted(
            {int(f["height"]) for f in formats if f.get("height") and f.get("vcodec") != "none"}
        ),
        "captions": {
            "creator": sorted((info.get("subtitles") or {}).keys()),
            "auto": sorted((info.get("automatic_captions") or {}).keys()),
        },
        "playlist": playlist,
        "index": index,
        "availability": info.get("availability", ""),
        "detailed": bool(formats),
    }
