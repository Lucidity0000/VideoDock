# Source publication and binary redistribution

## Source repository

Publish the original `videodock/`, `tests/`, `tools/`, `packaging/`, setup/launcher scripts, dependency declarations, documentation and project license. Retain [CREDITS.md](CREDITS.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [CITATION.cff](CITATION.cff). Pinned upstream model metadata is included; model weights, downloaded upstream Python modules, private media, diagnostic databases and personal configuration are excluded.

The project license applies only to original VideoDock material. It does not relicense upstream dependencies. A source-only repository does not redistribute the binaries that users may separately install using the documented setup process.

## Local binaries (0.4.4 and later)

The 0.6.1 UI follow-up uses separate versioned outputs and retains the 0.6.0 worker/native runtimes. Both 0.5.0 and 0.6.0 release artifacts remain preserved; redistribution obligations and publication status below are unchanged.

The 0.6.0 queue/recovery update uses a new release folder and installer. Its source and worker changes do not complete the redistribution requirements below. The 0.5.0 portable folder, installer and two SHA-256 files remain preserved. Older releases were privately archived and removed locally on October 20; recovery instructions/receipts are in `.test-artifacts/distribution-backup/2026-10-20/maintenance-summary.md`. The 0.5.0 source snapshot is local only; the last known public GitHub source is 0.4.4. No public upload is part of this work.

The local 0.4.4 portable build passed startup/navigation, installed-model selection and a real local-server download. The source suite passed 107 tests and Ruff. These are functional checks, not an assertion that all binary redistribution obligations are complete.

The 0.5.0 build also carries the current LICENSE, credits, citation and distribution documents. This does not complete the exact-version notices, corresponding source, replacement information or proprietary-runtime review below. See [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md) for the validation scope of each version.

**Do not publish the existing bundled installer/portable folder until the following items are completed for the actual shipped files.** Adding citations alone does not meet source/notice obligations.

1. Retain complete upstream copyright, license and NOTICE texts for direct and transitive components. The current summary notice is a starting point, not a complete license bundle. The exact source versions must be derived from the built runtime, not only from the development environments.
2. Provide the complete corresponding source and build/configuration information required for the exact GPL/LGPL binaries. The Gyan FFmpeg build uses `--enable-gpl --enable-version3`, and its incorporated libraries need their own source/notice coverage. The official PyInstaller-built `yt-dlp.exe` includes GPLv3+ dependencies. Review PyAV's bundled FFmpeg libraries separately. Generic upstream homepage links do not establish correspondence to the shipped binary.
3. Retain Qt/PySide/Shiboken GPL/LGPL notices and the exact source/replacement information. Keep Qt DLLs replaceable and provide instructions to run with compatible replacements. Review every bundled Qt module: some add-ons have GPL-only licensing even if the GUI uses only a subset.
4. Review CUDA/cuBLAS/cuDNN and other proprietary redistributable terms for the exact versions and permitted files. Preserve their notices; an open-source project license does not replace NVIDIA or Microsoft redistribution terms.
5. Preserve PyInstaller's bootloader licensing exception and notices. Check all frozen worker dependencies, tokenizer data, OpenCC dictionaries and embedded packages. Do not include locally cached model weights, private recordings or user databases.
6. Publish the applicable licenses, source archives/build instructions, full software inventory and checksums alongside the binary assets. State the actual validation scope and known Qwen short-fragment repetition limitation from [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md). Do not advertise universal transcription quality or a bug-free guarantee.

Primary licensing references:

- [FFmpeg license and legal considerations](https://ffmpeg.org/legal.html)
- [Qt's GPL/LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations)
- [Qt for Python's third-party licenses](https://doc.qt.io/qtforpython-6/licenses.html)
- [yt-dlp release licensing](https://github.com/yt-dlp/yt-dlp#licensing)
- [PyAV source/build information](https://github.com/PyAV-Org/PyAV)
- [PyInstaller license and exception](https://pyinstaller.org/en/stable/license.html)
- [NVIDIA CUDA EULA](https://docs.nvidia.com/cuda/eula/index.html)
- [NVIDIA cuDNN EULA](https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html)

## GitHub release asset limits

[GitHub requires every release asset to be under 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases). The local 0.4.4 installer is 3,666,653,351 bytes and the portable folder is 6,546,303,965 bytes. Neither can be uploaded as a single uncompressed release asset.

After completing binary redistribution requirements, either produce documented split archive assets under that limit or build a smaller installer with separately downloadable runtimes. Include hashes for every part and the reconstructed installer/archive, with Windows reconstruction instructions. Keep existing releases intact; repackaging must use a new output folder. Large binaries belong in release assets, not the Git history.

## GitHub Actions

Source pushes and pull requests should run lint/tests only. Large runtime/installer builds should be explicit manual jobs. A successful functional CI run does not authorize publishing binary assets without the redistribution material above.
