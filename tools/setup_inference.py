"""Prepare the isolated CUDA environment without changing the main caption runtime."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.fetch_inference_runtime import main as fetch_runtime  # noqa: E402


def main():
    python = ROOT / ".venv-inference/Scripts/python.exe"
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(python.parents[1])], check=True)
    flags = ["--no-input", "--disable-pip-version-check", "--keyring-provider", "disabled", "--no-cache-dir"]
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "torch==2.9.1",
            "--index-url",
            "https://download.pytorch.org/whl/cu130",
            *flags,
        ],
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-r",
            str(ROOT / "requirements-inference.txt"),
            "--index-url",
            "https://pypi.org/simple",
            *flags,
        ],
        check=True,
    )
    fetch_runtime()
    assets = json.loads((ROOT / "packaging/inference-runtime.lock.json").read_text(encoding="utf-8"))
    for asset in assets:
        if asset["id"].startswith("cuda12"):
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    str(ROOT / ".cache/inference" / asset["filename"]),
                    "--no-deps",
                    *flags,
                ],
                check=True,
            )
    wheel = ROOT / ".cache/inference/transcribe_cpp_native_cu12-0.3.1-py3-none-win_amd64.whl"
    subprocess.run([str(python), "-m", "pip", "install", str(wheel), "--no-deps", *flags], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-inference.lock.txt"),
                    "--index-url", "https://pypi.org/simple", *flags], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)


if __name__ == "__main__":
    main()
