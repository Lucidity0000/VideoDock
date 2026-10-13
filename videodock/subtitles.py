from __future__ import annotations

import html
import re
from pathlib import Path


def seconds(value):
    pieces = value.replace(",", ".").split(":")
    if len(pieces) not in {2, 3}:
        raise ValueError("Invalid subtitle timestamp.")
    minutes, sec = int(pieces[-2]), float(pieces[-1])
    hours = int(pieces[0]) if len(pieces) == 3 else 0
    if not 0 <= sec < 60 or not 0 <= minutes < 60 or hours < 0:
        raise ValueError("Invalid subtitle timestamp.")
    return hours * 3600 + minutes * 60 + sec


def parse_subtitles(path: Path, rolling=False):
    """Read UTF-8 SRT/VTT; strip styling and de-duplicate overlapping rolling captions."""
    from .captions import validate_cues

    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", content.strip()):
        if block.startswith(("NOTE", "STYLE", "REGION")):
            continue
        lines = block.splitlines()
        for row, line in enumerate(lines):
            match = re.match(
                r"\s*(\d{1,3}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->\s*"
                r"(\d{1,3}:\d{2}(?::\d{2})?[.,]\d{3})(?:\s+.*)?$",
                line,
            )
            if not match:
                continue
            start, end = seconds(match[1]), seconds(match[2])
            text = html.unescape(re.sub(r"<[^>]*>", "", "\n".join(lines[row + 1 :]))).strip()
            if not text:
                continue
            if rolling and cues and start < cues[-1]["end"]:
                previous = cues[-1]
                old, new = previous["text"].replace("\n", " "), text.replace("\n", " ")
                if old == new:
                    previous["end"] = max(previous["end"], end)
                    break
                overlap = 0
                for size in range(1, min(len(old), len(new)) + 1):
                    if old[-size:] == new[:size]:
                        overlap = size
                if overlap:
                    text = new[overlap:].strip()
                if start < previous["end"]:
                    previous["end"] = start
                    if previous["end"] <= previous["start"]:
                        cues.pop()
                if not text:
                    break
            cues.append({"id": f"cue-{len(cues) + 1:06d}", "start": start, "end": end, "text": text})
            break
    if not cues and "-->" in content:
        raise ValueError("No valid SRT/VTT cues found. Check subtitle timestamps and UTF-8 encoding.")
    if not cues and content.strip() not in {"", "WEBVTT"}:
        raise ValueError("This file is not a supported SRT or VTT subtitle file.")
    validate_cues(cues)
    return cues


def bilingual_cues(source, target, order):
    by_id = {cue["id"]: cue for cue in target}
    result = []
    for cue in source:
        translated = by_id.get(cue["id"])
        if not translated:
            raise ValueError("Bilingual tracks must contain matching source cue IDs.")
        texts = [cue["text"], translated["text"]]
        if order == "translation_first":
            texts.reverse()
        result.append({**cue, "text": "\n".join(texts)})
    return result


def ass_text(cues, settings):
    from .captions import validate_cues

    validate_cues(cues)
    rgb = settings.burn_color.lstrip("#")
    color = "&H00" + rgb[4:6] + rgb[2:4] + rgb[0:2]
    alignment = {"bottom": 2, "middle": 5, "top": 8}[settings.burn_position]
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 0\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{settings.burn_font},{settings.burn_size},{color},{color},&H00000000,&H80000000,"
        f"0,0,0,0,100,100,0,0,1,2,1,{alignment},30,30,30,1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def stamp(time):
        value = round(time * 100)
        return f"{value // 360000}:{value // 6000 % 60:02d}:{value // 100 % 60:02d}.{value % 100:02d}"

    for cue in cues:
        text = cue["text"].replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        text = text.replace("\n", "\\N")
        header += f"Dialogue: 0,{stamp(cue['start'])},{stamp(cue['end'])},Default,,0,0,0,,{text}\n"
    return header
