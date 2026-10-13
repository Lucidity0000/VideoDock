from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import replace

from .caption_models import check_cancel, verify_model
from .languages import chinese_text, model_language


def gpu_library_error():
    if os.name == "nt":
        import ctypes
        import ctypes.util

        try:
            ctypes.WinDLL(ctypes.util.find_library("cublas64_12") or "cublas64_12.dll")
        except OSError as exc:
            return str(exc)
    return ""


def cache_key(text, source, target, revision, backend="m2m100-beam4-v1"):
    return hashlib.sha256(
        json.dumps([text, source, target, revision, backend], ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def split_input(text, encode, limit=200):
    """Bound inputs without dropping tokens; prefer sentence boundaries, then words."""
    if len(encode(text)) <= limit:
        return [text]
    parts = re.split(r"(?<=[.!?。！？])", text)
    if len(parts) > 1 and all(part != text for part in parts):
        return [chunk for part in parts if part for chunk in split_input(part, encode, limit)]
    # Binary-search the longest prefix fitting the token budget (including unspaced scripts).
    low, high = 1, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if len(encode(text[:mid])) <= limit:
            low = mid
        else:
            high = mid - 1
    cut = low
    space = text.rfind(" ", 0, cut + 1)
    if space > cut // 2:
        cut = space + 1
    if cut >= len(text):
        raise ValueError("Unable to bound subtitle input for the tokenizer.")
    return [text[:cut]] + split_input(text[cut:], encode, limit)


class TranslationEngine:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.key = None
        self.device = "cpu"
        self.runtime = None

    def release(self):
        if getattr(self, "runtime", None):
            self.runtime.close()
            self.runtime = None
        self.model = self.tokenizer = self.key = None

    def load(self, root, spec, settings, cancel, emit):
        key = (str(root), spec["id"], spec["revision"], settings.caption_device, settings.cpu_fallback)
        if self.key == key and (not self.runtime or self.runtime.process is not None):
            if self.runtime:
                self.runtime.cancel, self.runtime.emit = cancel, emit
            return
        self.release()
        if spec.get("format"):
            from .inference_client import InferenceClient
            self.runtime = InferenceClient(spec, verify_model(root, spec, cancel), settings, cancel, emit)
            self.tokenizer = self.runtime
            self.key, self.device = key, self.runtime.device
            return
        import ctranslate2
        import sentencepiece

        path = verify_model(root, spec, cancel)
        self.tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(path / "sentencepiece.model"))
        device = settings.caption_device
        library_error = gpu_library_error() if device == "cuda" else ""
        if library_error:
            if not settings.cpu_fallback:
                raise ValueError(
                    "CUDA cuBLAS is unavailable. Choose CPU or enable CPU fallback. " + library_error
                )
            emit({"type": "warning", "message": "CUDA cuBLAS unavailable; using CPU INT8. " + library_error})
            device = "cpu"
        try:
            self.model = ctranslate2.Translator(
                str(path),
                device=device,
                compute_type="int8" if device == "cpu" else "int8_float16",
                inter_threads=1,
                intra_threads=max(1, min(8, os.cpu_count() or 4)),
            )
        except (RuntimeError, OSError, ValueError) as exc:
            if device != "cuda" or not settings.cpu_fallback:
                raise ValueError(f"Cannot load translation model: {exc}. Choose CPU or free memory.") from exc
            emit({"type": "warning", "message": f"Translation GPU unavailable; using CPU INT8. {exc}"})
            self.model = ctranslate2.Translator(str(path), device="cpu", compute_type="int8")
            device = "cpu"
        self.key, self.device = key, device

    def texts(self, texts, source, target, cancel):
        src, tgt = model_language(source), model_language(target)
        if src == tgt:
            return [chinese_text(text, target) if tgt == "zh" else text for text in texts]
        if getattr(self, "runtime", None):
            self.runtime.cancel = cancel
            output = []
            for text in texts:
                result = self.runtime.call({"action": "translate", "text": text, "source": source, "target": target})
                if not result:
                    raise ValueError("Translation produced empty text. Review the source language and retry.")
                output.append(chinese_text(result, target) if tgt == "zh" else result)
            return output
        encoded = [[f"__{src}__", *self.tokenizer.encode(text, out_type=str), "</s>"] for text in texts]
        check_cancel(cancel)
        results = self.model.translate_batch(
            encoded,
            target_prefix=[[f"__{tgt}__"] for _ in encoded],
            beam_size=4,
            max_input_length=0,
            max_decoding_length=512,
        )
        check_cancel(cancel)
        output = []
        for result in results:
            tokens = result.hypotheses[0]
            # A bounded decode reaching its cap is an error, never a silently truncated cue.
            if len(tokens) >= 512:
                raise ValueError("Translation exceeded its output limit. Split this source cue and retry.")
            tokens = [
                token for token in tokens if not token.startswith("__") and token not in {"</s>", "<s>"}
            ]
            text = self.tokenizer.decode(tokens).strip()
            if not text:
                raise ValueError("Translation produced empty text. Review the source language and retry.")
            output.append(chinese_text(text, target) if tgt == "zh" else text)
        return output

    def translate(
        self,
        cues,
        source,
        target,
        spec,
        root,
        settings,
        cancel,
        emit,
        cache,
        save_cache,
        previous=(),
        regenerate=False,
    ):
        from .captions import wrap_text

        prior = {cue["id"]: cue for cue in previous}
        output = []
        for offset in range(0, len(cues), 8):
            check_cancel(cancel)
            for cue in cues[offset : offset + 8]:
                src = cue.get("language") or source
                model_language(src)
                old = prior.get(cue["id"])
                if old and old.get("manual") and not regenerate:
                    output.append({**old, "start": cue["start"], "end": cue["end"]})
                    continue
                key = cache_key(cue["text"], src, target, spec["revision"],
                                spec["id"] + "-greedy-v1" if spec.get("format") else "m2m100-beam4-v1")
                if key not in cache or regenerate:
                    if model_language(src) == model_language(target):
                        text = (
                            chinese_text(cue["text"], target)
                            if model_language(target) == "zh"
                            else cue["text"]
                        )
                    else:
                        self.load(root, spec, settings, cancel, emit)
                        chunks = split_input(
                            cue["text"].replace("\n", " "),
                            lambda text: self.tokenizer.encode(text, out_type=str),
                        )
                        parts = []
                        for start in range(0, len(chunks), 8):
                            try:
                                parts.extend(self.texts(chunks[start : start + 8], src, target, cancel))
                            except (RuntimeError, OSError) as exc:
                                if self.device != "cuda" or not settings.cpu_fallback:
                                    raise
                                emit(
                                    {
                                        "type": "warning",
                                        "message": f"GPU translation failed; using CPU. {exc}",
                                    }
                                )
                                self.release()
                                self.load(root, spec, replace(settings, caption_device="cpu"), cancel, emit)
                                parts.extend(self.texts(chunks[start : start + 8], src, target, cancel))
                        text = " ".join(parts)
                    cache[key] = text
                output.append(
                    {
                        **cue,
                        "text": wrap_text(cache[key], settings.caption_line_length),
                        "language": target,
                        "manual": False,
                    }
                )
            save_cache()
            emit(
                {
                    "type": "translation_progress",
                    "language": target,
                    "done": len(output),
                    "total": len(cues),
                    "preview": output[-1]["text"] if output else "",
                }
            )
        return output
