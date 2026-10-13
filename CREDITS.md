# Acknowledgments and citations

VideoDock is an independent desktop application. Its original interface and queue orchestration build on substantial work by open-source developers, model researchers, translators and community maintainers. Thank you to the people who make these tools and models available.

These acknowledgments identify upstream work; they do not imply sponsorship or endorsement. The VideoDock project license applies to its original code only. Upstream software, model weights, documentation, datasets and trademarks retain their own terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for licensing details and [DISTRIBUTION.md](DISTRIBUTION.md) for binary-release requirements.

## Application and media tools

| Project and community | Contribution to VideoDock | Primary source |
|---|---|---|
| Qt Project and Qt for Python team | Desktop widgets, windowing and Python bindings | [Qt for Python](https://doc.qt.io/qtforpython-6/) |
| Python Software Foundation and Python contributors | Application language and standard library | [Python](https://www.python.org/), [license](https://docs.python.org/3/license.html) |
| SQLite authors and contributors | Persistent queue and history database | [SQLite](https://sqlite.org/), [copyright status](https://sqlite.org/copyright.html) |
| yt-dlp contributors, and the youtube-dl/youtube-dlc projects from which it descends | Link inspection and media acquisition | [yt-dlp](https://github.com/yt-dlp/yt-dlp), [release licensing](https://github.com/yt-dlp/yt-dlp#licensing) |
| FFmpeg developers and Gyan Doshi's Windows build project | Probing, conversion, subtitle rendering and packaged Windows binaries | [FFmpeg](https://ffmpeg.org/), [Gyan builds](https://www.gyan.dev/ffmpeg/builds/) |
| Deno contributors | JavaScript runtime used by the download engine | [Deno](https://github.com/denoland/deno) |
| PyAV contributors | Python access to FFmpeg media processing | [PyAV](https://github.com/PyAV-Org/PyAV) |

## Speech, translation and inference

| Project and community | Contribution | Primary source |
|---|---|---|
| SYSTRAN / faster-whisper contributors | Local Whisper transcription | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) |
| OpenNMT / CTranslate2 contributors | Efficient Whisper and M2M100 inference | [CTranslate2](https://github.com/OpenNMT/CTranslate2) |
| OpenAI / Whisper researchers and contributors | Optional speech-model family and public speech fixture used by opt-in development checks | [Whisper](https://github.com/openai/whisper), [Radford et al., 2022](https://arxiv.org/abs/2212.04356) |
| Hugging Face contributors | Transformers, Accelerate, tokenizers, Hub access and model repositories | [Transformers](https://github.com/huggingface/transformers), [Accelerate](https://github.com/huggingface/accelerate), [tokenizers](https://github.com/huggingface/tokenizers), [Hub client](https://github.com/huggingface/huggingface_hub) |
| PyTorch contributors | Optional additional-model tensor and CUDA runtime | [PyTorch](https://github.com/pytorch/pytorch) |
| Meta / M2M100 researchers | Optional multilingual translation model | [M2M100 model card](https://huggingface.co/facebook/m2m100_418M), [Fan et al., 2020](https://arxiv.org/abs/2010.11125) |
| ishiki-emo | Pinned M2M100 CTranslate2 conversion | [Conversion repository](https://huggingface.co/ishiki-emo/mojicast-m2m100-ct2) |
| IndexTeam | Optional Index-Translate models and official GGUF variants | [Index-Translate-2B](https://huggingface.co/IndexTeam/Index-Translate-2B), [Index-Translate-9B](https://huggingface.co/IndexTeam/Index-Translate-9B) |
| Edge0 / ARK model maintainers | Optional ARK-ASR models | [ARK-ASR-0.6B](https://huggingface.co/Edge0/ARK-ASR-0.6B), [ARK-ASR-3B](https://huggingface.co/Edge0/ARK-ASR-3B) |
| Qwen model team | Optional Qwen3 speech recognition and forced alignment | [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf), [Qwen3-ForcedAligner](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf) |
| ldov | Community Qwen3-ASR GGUF conversion | [GGUF repository](https://huggingface.co/ldov/Qwen3-ASR-1.7B-gguf) |
| ggml-org / llama.cpp and GGML contributors | Optional GGUF translation backend | [llama.cpp](https://github.com/ggml-org/llama.cpp), [GGML](https://github.com/ggml-org/ggml) |
| handy-computer / transcribe.cpp contributors | Optional GGUF speech backend | [transcribe.cpp](https://github.com/handy-computer/transcribe.cpp) |
| Silero team and contributors | Voice-activity detection | [Silero VAD](https://github.com/snakers4/silero-vad) |
| ONNX Runtime contributors | Voice-detector execution | [ONNX Runtime](https://github.com/microsoft/onnxruntime) |
| NVIDIA | Optional CUDA, cuBLAS and cuDNN runtime libraries | [CUDA terms](https://docs.nvidia.com/cuda/eula/index.html), [cuDNN terms](https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html) |

## Language processing and supporting libraries

Thanks also to the maintainers of [OpenCC](https://github.com/BYVoid/OpenCC), its [Python reimplementation](https://github.com/yichen0831/opencc-python), [SentencePiece](https://github.com/google/sentencepiece), [Nagisa](https://github.com/taishi-i/nagisa), [DyNet](https://github.com/clab/dynet), [Soynlp](https://github.com/lovit/soynlp), [NumPy](https://github.com/numpy/numpy), [SciPy](https://github.com/scipy/scipy), [Librosa](https://github.com/librosa/librosa), [Numba](https://github.com/numba/numba), [llvmlite](https://github.com/numba/llvmlite), [psutil](https://github.com/giampaolo/psutil), [filelock](https://github.com/tox-dev/filelock), [PyInstaller](https://github.com/pyinstaller/pyinstaller), [pytest](https://github.com/pytest-dev/pytest), [Ruff](https://github.com/astral-sh/ruff) and [Inno Setup](https://github.com/jrsoftware/issrc).

This is a human-readable acknowledgment of principal dependencies, not an exhaustive bill of materials for frozen executables. Before publishing binaries, collect transitive dependency notices and exact corresponding-source information as described in [DISTRIBUTION.md](DISTRIBUTION.md).

Model weights and upstream ARK custom modules are not part of the VideoDock source repository or installer. The [pinned model catalog](videodock/model_catalog.json) records repositories, revisions, sizes, hashes and declared licenses. Installation retains the upstream model cards/licenses selected in that catalog.

VideoDock's four SVG UI assets are original project assets; they were not copied from a third-party icon pack. Research citations and attribution do not establish the accuracy of any model or grant rights to downloaded media. Use VideoDock with media you are authorized to obtain and process.
