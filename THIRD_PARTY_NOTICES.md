# Third-party software

VideoDock runs the following tools as separate processes or uses their Python/Qt libraries:

- PySide6 / Qt: LGPLv3 / GPLv3 / commercial licenses. https://doc.qt.io/qtforpython-6/licenses.html
  Qt DLLs are shipped separately and can be replaced with compatible builds.
- yt-dlp source and PyPI wheel: Unlicense. https://github.com/yt-dlp/yt-dlp
  The official PyInstaller-built Windows executable includes GPLv3+ components and the
  combined executable is GPLv3+, as documented by upstream:
  https://github.com/yt-dlp/yt-dlp#licensing . Its EJS components and other bundled
  dependencies retain their respective notices. Consult the exact release's
  THIRD_PARTY_LICENSES.txt, not only the source repository's Unlicense.
- Deno: MIT. https://github.com/denoland/deno/blob/main/LICENSE.md
- faster-whisper: MIT. https://github.com/SYSTRAN/faster-whisper
- CTranslate2: MIT. https://github.com/OpenNMT/CTranslate2
- Whisper model packages: MIT. The data-only repositories and exact revisions/files are in
  videodock/model_catalog.json. Model weights are downloaded on demand and are not included in the installer.
- M2M100 418M: MIT, Copyright Facebook, Inc. and its affiliates. Source model:
  https://huggingface.co/facebook/m2m100_418M . The pinned CTranslate2 conversion is
  https://huggingface.co/ishiki-emo/mojicast-m2m100-ct2 . Its LICENSE is downloaded and verified
  alongside its data files. Exact conversion revision, byte sizes and SHA-256 hashes are in
  videodock/model_catalog.json. Weights are downloaded on demand, never bundled.
- SentencePiece: Apache-2.0. https://github.com/google/sentencepiece
- Additional model downloads: Apache-2.0, as declared by the pinned repositories:
  IndexTeam/Index-Translate-2B, IndexTeam/Index-Translate-9B and their official GGUF conversions;
  Edge0/ARK-ASR-0.6B and Edge0/ARK-ASR-3B; Qwen/Qwen3-ASR-1.7B-hf,
  Qwen/Qwen3-ForcedAligner-0.6B-hf and the community ldov/Qwen3-ASR-1.7B-gguf conversion.
  Exact repository URLs, revisions, files, sizes and SHA-256 hashes are in videodock/model_catalog.json.
  Weights and upstream custom source modules are downloaded on demand, never bundled.
  Verified pinned ARK custom source files run in the isolated inference worker.
  Upstream model cards are retained with each package.
- PyTorch: BSD-style license. https://github.com/pytorch/pytorch/blob/v2.9.1/LICENSE
  CUDA 13.0 Windows wheels include NVIDIA CUDA/cuBLAS/cuDNN redistributables and their notices.
- Transformers and Accelerate: Apache-2.0. https://github.com/huggingface/transformers
  https://github.com/huggingface/accelerate
- llama.cpp b11457: MIT. https://github.com/ggml-org/llama.cpp
- transcribe.cpp 0.3.1 and GGML: MIT. https://github.com/handy-computer/transcribe.cpp
  CUDA native provider comes from the pinned upstream Windows release wheel.
- NVIDIA CUDA 12.9 and 13.4 runtime/cuBLAS redistributables: NVIDIA Software License.
  https://docs.nvidia.com/cuda/eula/index.html
  Archive/wheel hashes and local redistributable hashes are pinned in packaging/inference-runtime.lock.json.
- Librosa: ISC. https://github.com/librosa/librosa
- SciPy: BSD-3-Clause. https://github.com/scipy/scipy
- Numba and llvmlite: BSD-2-Clause. https://github.com/numba/numba
- psutil: BSD-3-Clause. https://github.com/giampaolo/psutil
  Package license files are retained with the dedicated inference worker.
- Nagisa and its bundled Japanese tokenizer data: MIT. https://github.com/taishi-i/nagisa
- DyNet38: Apache-2.0. https://github.com/clab/dynet
- Soynlp: LGPL-3.0. https://github.com/lovit/soynlp
  Its Python source and package license accompany the dedicated runtime.
- OpenCC Python reimplementation and bundled conversion dictionaries: Apache-2.0.
  https://github.com/yichen0831/opencc-python and https://github.com/BYVoid/OpenCC
- Silero VAD: MIT. Its ONNX speech detector is included with faster-whisper.
  https://github.com/snakers4/silero-vad
- ONNX Runtime: MIT. https://github.com/microsoft/onnxruntime
- Hugging Face tokenizers/hub: Apache-2.0. https://github.com/huggingface/tokenizers
  https://github.com/huggingface/huggingface_hub
- PyAV: BSD-3-Clause, with bundled FFmpeg libraries and their upstream license notices.
  https://github.com/PyAV-Org/PyAV
- NumPy: BSD-3-Clause. https://github.com/numpy/numpy
- filelock: Unlicense. https://github.com/tox-dev/filelock
- FFmpeg essentials binaries from Gyan: GPLv3 builds, including libx264/libvpx/libass.
  The original license is retained under vendor/ in release builds.
  Build configuration, library versions, and corresponding source/build references:
  https://www.gyan.dev/ffmpeg/builds/ and https://github.com/GyanD/codexffmpeg
  FFmpeg source: https://ffmpeg.org/download.html

The exact binary versions and verified archive hashes appear in packaging/dependencies.lock.json.
Distributors must retain upstream licenses and satisfy corresponding source distribution obligations.

This document summarizes principal dependencies; it is not a complete license/NOTICE archive
for frozen binaries. See CREDITS.md for acknowledgments and DISTRIBUTION.md for the remaining
binary redistribution requirements. Original VideoDock source, upstream software, model
weights and media are distinct works and retain their respective terms. Attribution does
not imply endorsement or grant rights to third-party recordings.

