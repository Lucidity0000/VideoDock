"""Explicit developer refresh of the allowlisted, pinned data-only model catalog."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

MODELS = [
    ("base", "Whisper Base", "Systran/faster-whisper-base", "Multilingual", "Lightweight CPU preset"),
    ("small", "Whisper Small", "Systran/faster-whisper-small", "Multilingual", "Recommended CPU preset"),
    (
        "turbo",
        "Whisper Large v3 Turbo",
        "dropbox-dash/faster-whisper-large-v3-turbo",
        "Multilingual",
        "Recommended compatible-GPU preset",
    ),
    (
        "large-v3",
        "Whisper Large v3",
        "Systran/faster-whisper-large-v3",
        "Multilingual",
        "Quality preset; high memory use",
    ),
    (
        "distil-v3.5",
        "Distil-Whisper Large v3.5",
        "distil-whisper/distil-large-v3.5-ct2",
        "English only",
        "English preset; high memory use",
    ),
]
ALLOWED = {
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
    "vocabulary.json",
    "preprocessor_config.json",
}


def main():
    catalog = []
    for key, title, repo, languages, guidance in MODELS:
        with urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=40) as response:
            info = json.load(response)
        revision = info["sha"]
        files = []
        for item in info["siblings"]:
            name = item["rfilename"]
            if name not in ALLOWED:
                continue
            size = item["size"]
            if item.get("lfs"):
                digest = item["lfs"]["sha256"]
            else:
                with urlopen(
                    f"https://huggingface.co/{repo}/resolve/{revision}/{name}", timeout=40
                ) as response:
                    data = response.read()
                assert len(data) == size
                digest = hashlib.sha256(data).hexdigest()
            files.append({"name": name, "size": size, "sha256": digest})
        assert {"config.json", "model.bin", "tokenizer.json"} <= {f["name"] for f in files}
        catalog.append(
            {
                "id": key,
                "title": title,
                "repository": repo,
                "revision": revision,
                "languages": languages,
                "license": "MIT",
                "guidance": guidance,
                "measured_guidance": "VideoDock hardware measurements pending; see README for upstream benchmarks.",
                "files": files,
                "bytes": sum(f["size"] for f in files),
            }
        )
        print(key, revision, catalog[-1]["bytes"], flush=True)
    target = Path(__file__).resolve().parents[1] / "videodock" / "model_catalog.json"
    existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    refreshed = {spec["id"] for spec in catalog}
    catalog.extend(spec for spec in existing if spec["id"] not in refreshed)
    target.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
