"""Parallel bounded HTTP ranges for large, hash-pinned development dependencies."""

import argparse
import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen


def download(url, size, sha256, target, workers=12):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == size:
        with target.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() == sha256:
                return target
    parts = target.with_name(target.name + ".parts")
    parts.mkdir(exist_ok=True)
    block = 4 * 1024**2

    def fetch(index):
        start, end = index * block, min(size, (index + 1) * block) - 1
        path = parts / str(index)
        if path.is_file() and path.stat().st_size == end - start + 1:
            return path
        with (
            urlopen(
                Request(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}),
                timeout=60,
            ) as response,
            path.open("wb") as output,
        ):
            if response.status != 206 or not response.headers.get("Content-Range", "").startswith(
                f"bytes {start}-"
            ):
                raise ValueError("Dependency server did not honor a bounded range.")
            remaining = end - start + 1
            while remaining:
                content = response.read(min(256 * 1024, remaining))
                if not content:
                    raise ValueError("Dependency range ended early.")
                output.write(content)
                remaining -= len(content)
        print(target.name, index + 1, "/", (size + block - 1) // block, flush=True)
        return path

    with ThreadPoolExecutor(max_workers=workers) as pool:
        paths = list(pool.map(fetch, range((size + block - 1) // block)))
    with target.open("wb") as output:
        for path in paths:
            with path.open("rb") as source:
                shutil.copyfileobj(source, output)
    with target.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != sha256:
            raise ValueError("Pinned dependency checksum mismatch.")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("size", type=int)
    parser.add_argument("sha256")
    parser.add_argument("target")
    args = parser.parse_args()
    download(args.url, args.size, args.sha256, args.target)
