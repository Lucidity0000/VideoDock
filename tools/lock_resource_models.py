"""Explicit developer refresh of the packages in outputs/model_resources_translation_asr (1).md.

Fetch repository metadata and small supporting files, never model weights.
Pinned ARK custom modules are used only by the isolated inference helper.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen

COMMON_FILES = {
    "README.md", "LICENSE", "LICENSE.txt", "config.json", "generation_config.json",
    "preprocessor_config.json", "video_preprocessor_config.json", "processor_config.json",
    "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt",
    "added_tokens.json", "special_tokens_map.json", "chat_template.jinja",
    "model.safetensors.index.json",
}
ARK_FILES = {
    "configuration_arkasr.py", "modeling_arkasr.py", "modeling_audio.py", "processing_arkasr.py",
}
PACKAGES = [
    ("index-translate-2b-full", "Index-Translate-2B", "translation", "IndexTeam/Index-Translate-2B",
     "qwen3_5", "150 languages", ""),
    ("index-translate-2b-q4-k-m", "Index-Translate-2B", "translation",
     "IndexTeam/Index-Translate-2B-GGUF", "qwen3_5", "150 languages", "Index-Translate-2B.Q4_K_M.gguf"),
    ("index-translate-9b-full", "Index-Translate-9B", "translation", "IndexTeam/Index-Translate-9B",
     "qwen3_5", "150 languages", ""),
    ("index-translate-9b-q4-k-m", "Index-Translate-9B", "translation",
     "IndexTeam/Index-Translate-9B-GGUF", "qwen3_5", "150 languages", "Index-Translate-9B.Q4_K_M.gguf"),
    ("ark-asr-0.6b-full", "ARK-ASR-0.6B", "speech", "Edge0/ARK-ASR-0.6B", "arkasr", "19 languages", ""),
    ("ark-asr-3b-full", "ARK-ASR-3B", "speech", "Edge0/ARK-ASR-3B", "arkasr", "19 languages", ""),
    ("qwen3-asr-1.7b-full", "Qwen3-ASR-1.7B", "speech", "Qwen/Qwen3-ASR-1.7B-hf",
     "qwen3_asr", "30 languages + 22 Chinese dialects", ""),
    ("qwen3-asr-1.7b-q4-k-m", "Qwen3-ASR-1.7B", "speech", "ldov/Qwen3-ASR-1.7B-gguf",
     "qwen3_asr", "30 languages + 22 Chinese dialects", "Qwen3-ASR-1.7B-Q4_K_M.gguf"),
    ("qwen3-forcedaligner-0.6b-full", "Qwen3-ForcedAligner-0.6B", "alignment",
     "Qwen/Qwen3-ForcedAligner-0.6B-hf", "qwen3_forced_aligner", "11 languages", ""),
]


def select_files(info: dict, architecture: str, gguf: str) -> list[dict]:
    allowed = {gguf, "README.md", "SHA256SUMS.txt", "LICENSE", "LICENSE.txt"} if gguf else COMMON_FILES
    if architecture == "arkasr":
        allowed = allowed | ARK_FILES
    selected = [
        item for item in info["siblings"]
        if item["rfilename"] in allowed
        or (not gguf and re.fullmatch(r"model(?:-\d{5}-of-\d{5})?\.safetensors", item["rfilename"]))
    ]
    names = {item["rfilename"] for item in selected}
    required = {gguf, "README.md"} if gguf else {
        "config.json", "tokenizer.json", "tokenizer_config.json", "README.md",
    }
    if architecture == "arkasr":
        required |= ARK_FILES
    if not required <= names or (not gguf and not any(name.endswith(".safetensors") for name in names)):
        raise ValueError(f"Incomplete package: {info['id']}")
    if not gguf and "model.safetensors" not in names and "model.safetensors.index.json" not in names:
        raise ValueError(f"Sharded package has no weight index: {info['id']}")
    return sorted(selected, key=lambda item: item["rfilename"])


def lock_package(package: tuple) -> dict:
    key, title, task, repo, architecture, languages, gguf = package
    with urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=40) as response:
        info = json.load(response)
    revision = info["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"Repository has no immutable revision: {repo}")
    if info.get("cardData", {}).get("license") != "apache-2.0":
        raise ValueError(f"Review changed license before refreshing {repo}")
    files, data = [], {}
    for item in select_files(info, architecture, gguf):
        name, size = item["rfilename"], item["size"]
        if item.get("lfs"):
            digest = item["lfs"]["sha256"]
        else:
            if size > 32 * 1024**2:
                raise ValueError(f"Unexpected large non-LFS file: {repo}/{name}")
            with urlopen(f"https://huggingface.co/{repo}/resolve/{revision}/{name}", timeout=40) as response:
                content = response.read(size + 1)
            if len(content) != size:
                raise ValueError(f"Size mismatch: {repo}/{name}")
            digest = hashlib.sha256(content).hexdigest()
            data[name] = content
        files.append({"name": name, "size": size, "sha256": digest})
    if not gguf:
        config = json.loads(data["config.json"])
        dtype = config.get("dtype", config.get("torch_dtype", config.get("text_config", {}).get("dtype")))
        if dtype != "bfloat16":
            raise ValueError(f"Review changed original precision before refreshing {repo}: {dtype}")
        if "model.safetensors.index.json" in data:
            shards = set(json.loads(data["model.safetensors.index.json"])["weight_map"].values())
            if shards != {file["name"] for file in files if file["name"].endswith(".safetensors")}:
                raise ValueError(f"Incomplete weight shards: {repo}")
    runtime = (
        "transcribe.cpp" if gguf and task == "speech" else "llama.cpp" if gguf
        else "Transformers with ARK custom code" if architecture == "arkasr" else "Transformers"
    )
    guidance = "Bundled CUDA runtime; select GPU or CPU."
    if architecture == "arkasr":
        guidance += " Verified pinned custom source runs in the isolated inference helper."
    if task == "alignment":
        guidance += " Alignment requires audio and an existing transcript; this is not a speech recognizer."
    if not gguf and (architecture == "arkasr" or task == "alignment"):
        guidance += " No 4-bit source was supplied in the resource list."
    return {
        "id": key,
        "title": title + (" · 4-bit Q4_K_M" if gguf else " · Full precision BF16"),
        "family": title,
        "task": task,
        "repository": repo,
        "revision": revision,
        "languages": languages,
        "license": "Apache-2.0",
        "architecture": architecture,
        "format": "GGUF" if gguf else "Safetensors",
        "precision": "q4_k_m" if gguf else "bf16",
        "quantization": "q4_k_m" if gguf else "none",
        "download_only": False,
        "external_runtime": runtime,
        "guidance": guidance,
        "measured_guidance": "Original weights are BF16, not FP32. Storage bytes are not RAM/VRAM requirements. "
        "Review the release validation report for measured GPU checks and limits.",
        "supported_sources": ["en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it", "yue"],
        "files": files,
        "bytes": sum(file["size"] for file in files),
    }


def main():
    locked = []
    for package in PACKAGES:
        spec = lock_package(package)
        locked.append(spec)
        print(spec["id"], spec["revision"], spec["bytes"], flush=True)
    path = Path(__file__).resolve().parents[1] / "videodock" / "model_catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    ids = {spec["id"] for spec in locked}
    catalog = [spec for spec in catalog if spec["id"] not in ids] + locked
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
