"""Hash the complete portable release and installer, and verify older artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, help="Pre-build artifact snapshot to verify")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    dist = ROOT / "dist"
    portable = dist / f"VideoDock-{version}"
    installer = dist / f"VideoDock-Setup-{version}.exe"
    assert installer.is_file() and installer.stat().st_size > 100_000_000, "Installer is missing or incomplete"
    previous_count = 0
    if args.previous:
        for item in json.loads(args.previous.read_text(encoding="utf-8")):
            path = ROOT / item["file"]
            assert path.stat().st_size == item["size"] and digest(path) == item["sha256"], path
            previous_count += 1
    hashes = {path.relative_to(dist).as_posix(): digest(path)
              for path in sorted(portable.rglob("*")) if path.is_file()}
    all_files = dist / f"VideoDock-{version}-SHA256FILES.txt"
    all_files.write_text("".join(f"{value}  {name}\n" for name, value in hashes.items()), encoding="utf-8")
    names = [f"VideoDock-{version}/VideoDock.exe",
             f"VideoDock-{version}/_internal/vendor/VideoDockWorker.exe",
             f"VideoDock-{version}/_internal/vendor/inference/VideoDockInferenceWorker.exe"]
    lines = [f"{hashes[name]}  {name}\n" for name in names]
    lines.extend(f"{digest(path)}  {path.name}\n" for path in [installer, all_files])
    sums = dist / f"VideoDock-{version}-SHA256SUMS.txt"
    sums.write_text("".join(lines), encoding="utf-8")
    report = {"version": version, "portable_files": len(hashes),
              "portable_bytes": sum(path.stat().st_size for path in portable.rglob("*") if path.is_file()),
              "installer_bytes": installer.stat().st_size, "older_artifacts_verified": previous_count,
              "checksums": str(sums), "complete_manifest": str(all_files)}
    report_path = ROOT / ".test-artifacts/releases" / version / "release-artifacts.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
