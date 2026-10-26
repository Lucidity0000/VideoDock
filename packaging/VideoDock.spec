# PyInstaller spec for the windowed Windows application.
import re
import tomllib
from pathlib import Path

root = Path(SPECPATH).parent
version = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
vendor = root / 'vendor'
a = Analysis(
    [str(root / 'run_videodock.py')],
    pathex=[str(root)],
    binaries=[(str(vendor / name), 'vendor') for name in
              ['VideoDockWorker.exe', 'yt-dlp.exe', 'ffmpeg.exe', 'ffprobe.exe', 'deno.exe']],
    datas=[(str(root / 'THIRD_PARTY_NOTICES.md'), '.'), (str(vendor / 'ffmpeg-LICENSE'), 'vendor'),
           *((str(root / name), '.') for name in ('LICENSE', 'CREDITS.md', 'CITATION.cff', 'DISTRIBUTION.md')),
           (str(root / 'README.md'), '.'), (str(root / 'RELEASE_VALIDATION.md'), '.'),
           (str(root / 'requirements-inference.lock.txt'), '.'),
           (str(root / 'packaging' / 'inference-runtime.lock.json'), '.'),
           (str(root / 'videodock' / 'model_catalog.json'), 'videodock'),
           (str(root / 'videodock' / 'assets'), 'videodock/assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['yt_dlp', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'av', 'tokenizers', 'sentencepiece', 'opencc', 'torch', 'transformers', 'transcribe_cpp'], noarchive=False, optimize=0,
)
# Qt 6.11 uses the ICU API supplied by Windows. An unrelated ICU from another
# program on the build machine's PATH can be picked up by dependency scanning,
# shadow the system library, and make QtCore fail with a missing entry point.
a.binaries = [entry for entry in a.binaries
              if not re.fullmatch(r'icu(?:uc|in|dt)\d*\.dll', Path(entry[0]).name.lower())]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='VideoDock',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
runtime_datas = [('vendor/' + name + '/' + path.relative_to(vendor / name).as_posix(), str(path), 'DATA')
                 for name in ('inference', 'llama', 'cuda12')
                 for path in (vendor / name).rglob('*') if path.is_file()]
coll = COLLECT(exe, a.binaries, a.datas, runtime_datas, strip=False, upx=False, name=f'VideoDock-{version}')

