"""Stage a verified, portable Inno Setup compiler entirely inside build/."""

from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"


def main():
    BUILD.mkdir(exist_ok=True)
    compiler = BUILD / "inno" / "ISCC.exe"
    if compiler.is_file():
        print(compiler)
        return
    api = "https://api.github.com/repos/jrsoftware/issrc/releases/tags/is-7_1_0"
    with urllib.request.urlopen(
        urllib.request.Request(api, headers={"User-Agent": "VideoDock-build"}), timeout=30
    ) as response:
        release = json.load(response)
    asset = next(item for item in release["assets"] if item["name"] == "innosetup-7.1.0-x64.exe")
    expected = "0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f"
    if asset.get("digest") != "sha256:" + expected:
        raise ValueError("The Inno Setup release digest did not match the pinned compiler.")
    installer = BUILD / asset["name"]
    with urllib.request.urlopen(asset["browser_download_url"], timeout=60) as response:
        contents = response.read()
    if hashlib.sha256(contents).hexdigest() != expected:
        raise ValueError("Compiler download checksum mismatch.")
    installer.write_bytes(contents)
    result = subprocess.run(
        [
            str(installer),
            "/PORTABLE=1",
            "/CURRENTUSER",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/NOICONS",
            f"/DIR={compiler.parent}",
            f"/LOG={BUILD / 'inno-install.log'}",
        ],
        check=False,
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode or not compiler.is_file():
        raise RuntimeError("Portable compiler setup failed. See build/inno-install.log.")
    print(compiler)


if __name__ == "__main__":
    main()
