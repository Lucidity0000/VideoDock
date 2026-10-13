"""Cache wheels already selected by pip, with PyPI SHA-256 verification."""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.download_pinned_asset import download  # noqa: E402


def main():
    log = (ROOT / ".test-artifacts/model-resources/inference-install.log").read_text(encoding="utf-8")
    names = set(re.findall(r"Downloading ([A-Za-z0-9_.+-]+\.whl)(?:\.metadata)?", log))
    target = ROOT / ".cache/inference/wheels"
    target.mkdir(parents=True, exist_ok=True)

    def fetch(filename):
        name, version = filename.split("-")[:2]
        with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=40) as response:
            metadata = json.load(response)
        asset = next(item for item in metadata["urls"] if item["filename"] == filename)
        download(asset["url"], asset["size"], asset["digests"]["sha256"], target / filename,
                 workers=6)
        print("Verified wheel:", filename, flush=True)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch, sorted(names)))


if __name__ == "__main__":
    main()
