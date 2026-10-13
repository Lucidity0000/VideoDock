"""Stage an allowlisted, credential-checked source snapshot for GitHub publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("videodock", "tests", "tools", "packaging", ".github")
ROOT_FILES = (
    ".gitignore", "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "CREDITS.md",
    "CITATION.cff", "CHANGELOG.md", "DISTRIBUTION.md", "RELEASE_VALIDATION.md",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt", "requirements-inference.txt",
    "requirements-inference.lock.txt", "run_videodock.py", "run_worker.py", "run_inference_worker.py",
    "setup.ps1", "start.ps1",
)
EXTENSIONS = {".py", ".json", ".spec", ".iss", ".ps1", ".svg", ".yml", ".yaml"}
SECRETS = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-proj-[A-Za-z0-9_-]{30,})\b"
)


def source_files():
    files = [ROOT / name for name in ROOT_FILES]
    for name in DIRECTORIES:
        files.extend(path for path in (ROOT / name).rglob("*")
                     if path.is_file() and path.suffix in EXTENSIONS and "__pycache__" not in path.parts)
    return sorted(set(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".test-artifacts"):
        raise SystemExit("Publication staging must remain inside the workspace .test-artifacts folder.")
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        if SECRETS.search(text):
            raise SystemExit(f"Potential credential found in {path.relative_to(ROOT)}; publication stopped.")
        relative = path.relative_to(ROOT)
        destination = output / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        data = text.encode("utf-8")
        records.append({"file": relative.as_posix(), "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "git_blob_sha": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()})
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    with zipfile.ZipFile(output / f"VideoDock-{version}-source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            archive.write(output / "source" / record["file"], "VideoDock/" + record["file"])
    (output / "manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Staged {len(records)} source files ({sum(row['bytes'] for row in records):,} bytes); "
          "no binaries, environments, model weights, databases, media or cached outputs.")


if __name__ == "__main__":
    main()
