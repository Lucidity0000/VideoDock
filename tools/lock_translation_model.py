"""Explicit developer-only refresh of a verified data-only M2M100 conversion."""

import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

REPO = "ishiki-emo/mojicast-m2m100-ct2"
FILES = {"config.json", "model.bin", "shared_vocabulary.json", "sentencepiece.model", "LICENSE"}


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from videodock.languages import M2M_LANGUAGES

    with urlopen(f"https://huggingface.co/api/models/{REPO}?blobs=true", timeout=40) as response:
        info = json.load(response)
    revision = info["sha"]
    files = []
    for item in info["siblings"]:
        name = item["rfilename"]
        if name not in FILES:
            continue
        if item.get("lfs"):
            digest = item["lfs"]["sha256"]
        else:
            with urlopen(f"https://huggingface.co/{REPO}/resolve/{revision}/{name}", timeout=40) as response:
                data = response.read()
            assert len(data) == item["size"]
            digest = hashlib.sha256(data).hexdigest()
        files.append({"name": name, "size": item["size"], "sha256": digest})
    assert FILES == {file["name"] for file in files}
    root = Path(__file__).resolve().parents[1]
    spec = {
        "id": "m2m100-418m",
        "title": "M2M100 418M",
        "task": "translation",
        "repository": REPO,
        "revision": revision,
        "languages": "100 languages · many-to-many",
        "license": "MIT",
        "guidance": "CPU INT8 or NVIDIA GPU; generic Chinese + OpenCC script conversion",
        "measured_guidance": "Representative translation quality review pending; review exported text.",
        "files": files,
        "bytes": sum(file["size"] for file in files),
    }
    spec.update(
        supported_sources=M2M_LANGUAGES,
        supported_targets=M2M_LANGUAGES,
        architecture="m2m100",
        quantization="int8",
        source_model="facebook/m2m100_418M",
    )
    path = root / "videodock" / "model_catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog = [entry for entry in catalog if entry["id"] != spec["id"]]
    for entry in catalog:
        entry.setdefault("task", "speech")
    catalog.append(spec)
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(spec["id"], revision, spec["bytes"])


if __name__ == "__main__":
    main()
