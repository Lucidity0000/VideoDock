"""Dedicated onedir CUDA runtime; model weights remain outside the application."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas, binaries, hidden = [], [], []
for package in ("torch", "accelerate", "librosa", "nagisa", "soynlp", "transcribe_cpp", "transcribe_cpp_native", "transcribe_cpp_native_cu12"):
    data, binary, imports = collect_all(package)
    datas.extend(data)
    binaries.extend(binary)
    hidden.extend(imports)
for package in ("transformers", "huggingface_hub", "tokenizers", "safetensors", "psutil", "DyNet38"):
    datas.extend(copy_metadata(package))
for module in ("transformers.models.qwen3_5", "transformers.models.qwen3_asr",
               "transformers.models.qwen2", "transformers.models.whisper",
               "transformers.models.auto", "transformers.generation", "transformers.integrations"):
    hidden.extend(collect_submodules(module))
datas.extend([(str(root / "videodock/model_catalog.json"), "videodock")])
a = Analysis([str(root / "run_inference_worker.py")], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["PySide6", "tensorflow", "jax", "flax", "torchvision", "torchaudio", "matplotlib"],
             hookspath=[], hooksconfig={}, runtime_hooks=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VideoDockInferenceWorker",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="inference")
