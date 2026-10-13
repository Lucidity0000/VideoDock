# VideoDock 0.4.4 validation

Validated in the Windows workspace on October 13, 2026 with isolated app data.

- Refreshed the dark theme with clearer navigation, a small vector brand mark, readable checkbox/dropdown controls, stronger model cards and color-coded job results. Empty preview, queue and history tables explain the next action. Selection counts update beside preview controls.
- The compact preview toolbar shows the first preview row at 1100 × 680 while preserving the destination and independent queue controls. **Ranges…** expands playlist interval controls and scrolls them into view. Existing per-item settings, batch captioning and all three queue actions retain their behavior.
- External titles and notices use literal text instead of Qt's automatic HTML detection. Resetting a preview now clears stale details/thumbnails and disables actions that require a selected row. Disabled primary buttons use the disabled palette.
- **107 tests pass; Ruff passes.** Three added regressions cover literal titles/errors, selection/reset/empty-state behavior, and accessible preview/range controls at minimum size. The full suite retains the download, resume, cancellation, migration, translation and batch-caption checks. The existing SentencePiece SWIG deprecation warnings remain.
- 74 source captures cover five pages, four settings sections and their scroll bottoms, three model tabs, three queue tabs, expanded playlist ranges, per-item settings and the caption editor at 1100 × 680, 1100 × 740 and 1380 × 900. Evidence is in `.test-artifacts/ui-polish-044`.
- The actual 0.4.4 portable GUI passes isolated startup, navigation through all five pages/four settings sections/three model tabs, empty-state rendering, Unicode previews/destinations and a real local-server download through the bundled worker. All nine installed additional packages enable **Use**; Index 9B Q4 and Qwen ASR Q4 still select the appropriate task and CUDA. Packaged reports/screenshots are under `.test-artifacts/releases/0.4.4`.
- Only the GUI and its visual assets change. The caption worker and frozen inference/native runtimes are reused from 0.4.3. This release does not repeat the nine-model CUDA or full-recording transcription checks; the queue #100 diagnosis and earlier accuracy/environment limits below still apply.
- All **14,950 reused worker/runtime files** match the complete 0.4.3 SHA-256 manifest, covering **6,095,499,119 bytes**. Model weights remain outside the release.
- Previous release folders and installers are retained. All launches/tests use isolated data; no user jobs or model libraries are modified and no user application is terminated. Isolated checks do not establish a user launch of this release.

# VideoDock 0.4.3 validation

Validated in the Windows workspace on October 13, 2026 with isolated app data.

- History permitted multiple row selection, but Generate captions read only the current row. The action now queues every selected saved media file in one click, using the current model settings and each item's destination, then refreshes and pumps the caption queue once.
- Original media is preferred; an existing media output is usable if the original is missing. Missing files and jobs still finishing are reported without dropping eligible selections. Audio sidecars and per-item settings remain independent. Adding work respects the caption queue's paused state.
- **104 tests pass; Ruff passes.** New UI regressions exercise a sorted, noncontiguous selection with a different current row, multiple destinations, original/output fallback, mixed audio/video settings, skipped-file reporting, no selection and invalid settings.
- The GUI is rebuilt for 0.4.3. The worker, frozen inference helper and native runtimes are reused from 0.4.2. The captioning/translation acceptance and queue #100 diagnosis below retain their scope; this hotfix does not repeat model inference measurements.
- Versioned portable and installer outputs, SHA-256 manifests and isolated packaged startup/download reports are under `dist` and `.test-artifacts/releases/0.4.3`. Older releases are retained and their pre-build hashes are checked.

# VideoDock 0.4.2 validation

Validated in the Windows workspace on October 13, 2026. Diagnostics copy the user's database read-only and extract audio into an isolated folder. No user jobs are retried, cleared or changed; no user application is terminated.

## Queue #100 diagnosis

- Downloaded media is intact. The job uses Qwen3-ASR-1.7B Q4_K_M, Chinese (`zh`), CUDA, embedded captions, and no translation. Its recorded error is `transcribe_run: output repetition: decode stopped when the output began repeating itself (status 19)`.
- The unchanged frozen helper reproduces the exact error on the real lecture's **85.930–86.998-second** VAD segment after six successful preceding spans. The stored progress of 75.99 seconds is the last successful span, not the failing span's start. This is a decoder repetition guard, not a download/translation failure. It is not classified as a CUDA/device failure, so the CPU fallback option does not retry it.
- The caption adapter now reports the model and failing time range, keeps the backend error, and explains how to generate captions from the saved media using another model. It does not suppress the error or claim to recover the complete lecture. Reproduction evidence is in `.test-artifacts/queue-100-20261013`.
- Giving the same segment additional audio context (84.930–87.998 or 80–100 seconds) avoids status 19 in isolated comparisons. Automatic language selection also avoids the error but incorrectly detects Thai on the short fragment. These checks implicate fragile decoding of the short fragment; they do not establish transcript accuracy or full-lecture recovery. The release does not automatically switch languages or discard failed speech.

## Source and UI acceptance

- **101 tests pass; Ruff passes.** Stage regressions cover independent starts/pauses, waiting for download-worker cleanup before starting captions, cancellation at that handoff without changing successful download status, caption-to-translation handoff, durable source reuse, translation failure/retry/restart without changing successful stage results, legacy database migration, deferred creator captions, history clearing/file preservation, sorting/selection retention, Unicode folder opening, and actionable decoder repetition errors. Tests isolate app data from the user's installed model library.
- The page is **Models**. **Open** beside **Save to → Browse…** opens the existing destination in File Explorer. Downloading, Captioning and Translating have separate persistent queues and controls; each stage has its own saved status. Captioning and translation retain one shared inference slot, while media downloads run independently.
- History exposes separate Download/Captions/Translation results, clearing of cancelled or selected terminal records, eight sorting presets, and clickable column sorting. Sorting persists and selection survives worker refresh. Clearing leaves saved/partial files and checkpoints intact and protects active/pending jobs.
- The real source Base/M2M100 queue passes caption completion with translation paused, explicit translation resume, unchanged durable source cues, exactly one transcription and three embedded tracks with the chosen default. Cached verified models are used; no new model download is claimed.
- 71 layout captures include all pages, settings/model sections, three queue tabs, history and caption editor at 1100 × 680, 1100 × 740 and 1380 × 900. Reports are in `.test-artifacts/queues-042` and `.test-artifacts/releases/0.4.2`.

## Runtime scope

The caption worker and GUI are rebuilt for these pipeline/UI changes. The frozen additional-model inference helper and native CUDA runtimes remain unchanged from 0.4.1/0.4.0; the prior nine-model CUDA evidence remains below and is not repeated as a new acceptance claim. Broad multilingual/long-recording quality and fresh-VM/player checks retain the earlier limits. Isolated launches do not establish a user launch of any release.

## Packaged acceptance

- The actual 0.4.2 GUI passes startup/navigation, all three queue tabs, independent history status columns, eight sorting choices, both clearing controls, the destination Open button, Unicode preview/destination and a real download through the bundled worker.
- All nine verified additional packages enable Use. Installed Index 9B Q4 and Qwen ASR Q4 choices select the appropriate model and CUDA in Download settings.
- The rebuilt packaged worker passes the same real Base/M2M100 caption/translation handoff: translation remains queued until started, source cues stay unchanged, one transcription yields three embedded tracks, and default-track metadata is correct.
- A separate isolated packaged-worker request using the real lecture's opening audio reproduces #100's decoder failure and reports **85.930–86.998 seconds**, saved-media retention and History → Generate captions. It does not publish a misleading completed transcript.
- Portable and installer outputs are versioned as 0.4.2. Builds run separately from packaged acceptance; native dependencies are reused without fetching/re-extracting tools. Pre-build hashes of 30 previous release artifacts are retained for final integrity verification. Reports are under `.test-artifacts/releases/0.4.2` and `.test-artifacts/queues-042`.

# VideoDock 0.4.1 validation

Validated in the Windows development workspace on October 13, 2026. Previous releases remain versioned. All launches, download-button checks and layout captures use isolated diagnostic data; no user queue or model files are modified.

## Settings and layout

- One Caption models page owns speech, translation and alignment library management. Download settings is independent of Downloads and groups Media, Captions, Translation and Subtitle style. Save defaults preserves queued snapshots. Downloads retains its Save to / Browse control and removes the redundant Open destination action.
- Model selectors show installation state and disable missing or busy packages. Saved missing selections remain visible for restoration. Status updates on selection, progress, cancellation/resume, completion, removal and library-folder changes. Disk readiness overrides stale session states.
- The translation download button drives the real model worker: an isolated 496,017,327-byte M2M100 package, seeded from the verified test cache, passes full SHA-256 verification/publication and immediately enables Use. This check does not claim a fresh network download.
- **92 tests pass; Ruff passes.** Five new regressions cover page ownership, installed/unavailable selectors, storage switching, translation download lifecycle, Browse, saved defaults versus queued settings, and per-item/format control state. Existing open-pipe, UTF-8, cancellation and inference regressions remain covered. SentencePiece SWIG warnings remain benign.
- Layout capture covers five main pages, all four settings sections including their scroll bottoms, all three model-library tabs, per-item settings and the caption editor at 1100 × 680, 1100 × 740 and 1380 × 900. Destination and queue actions remain visible at the minimum size. Dark scrollbars, model cards, disabled controls and editor column sizing were inspected. The 62 captures and reports are in `.test-artifacts/ui-refresh`.

## Packaged acceptance

- The actual versioned 0.4.1 portable GUI passes startup, navigation through all five main pages and four settings sections, Unicode preview/destinations and a real download through its bundled worker.
- All nine verified additional packages still enable Use. Selecting Index 9B Q4 and Qwen ASR Q4 opens the appropriate Download settings section, retains the task-specific model choice and selects CUDA. Missing models remain unavailable for Use.
- The GUI was rebuilt separately from tests, without fetching/replacing dependencies or rebuilding the unchanged inference helper and caption worker. The per-user installer uses this same portable folder. Versioned release executables and a complete SHA-256 manifest are delivered under `dist`; the 22 previous executables/installers/checksum artifacts have a pre-build hash snapshot for verification.
- Packaged screenshots and reports are under `.test-artifacts/releases/0.4.1`. These checks do not repeat the nine-model inference measurements; unchanged-runtime inference evidence remains in the 0.4.0 section below.

## Validation limits

This release changes GUI organization and state reporting. It does not change inference runtimes or model packages. The verified 0.4.0 helper and caption-worker bundle are retained. Broader language/long-recording quality, external-player compatibility, fresh-VM installation and live YouTube availability retain the limits below. Isolated launches do not establish that the user launched either release.

# VideoDock 0.4.0 validation

Validated in the Windows development workspace on October 7, 2026. Existing releases and the user's model library remain intact. Test models, databases and outputs are isolated under `.test-artifacts/gpu` and `.test-artifacts/model-resources`.

## Source and GPU checks

- **87 tests pass; Ruff passes.** New regressions cover installed Use controls, task-specific selection, saved model/alignment choices, revision pinning, separate translation cache keys, clean GPU failure recovery, strict GPU settings after an earlier CPU fallback, and punctuation-preserving alignment. The open-pipe NumPy regression remains covered.
- Use routes all nine additional packages to speech, translation or optional word alignment. GPU choice is retained in queued settings. Model integrity is checked before any weights or pinned ARK code execute. Workers retain UTF-8 input/output, ASCII-escaped JSON and Windows available-byte pipe reads.
- Direct CUDA inference with CPU fallback disabled passes all nine additional variants in the packaged runtime: Index-Translate-2B BF16/Q4, Index-Translate-9B BF16/Q4, both ARK BF16 sizes, Qwen3-ASR BF16/Q4 and Qwen3-ForcedAligner BF16. Each speech runtime handles two requests with stdin open. Index Q4 reports 26/34 offloaded layers. BF16 tensor allocations are approximately 4.4 GB (Index 2B), 2.3/7.5 GB (ARK), 4.1 GB (Qwen ASR) and 1.8 GB (aligner). These are tensor counts, not peak VRAM measurements.
- The user's installed Index 9B Q4 and Qwen ASR Q4 packages were hash-verified read-only and copied into the isolated test library for these checks.
- The real persistent worker completes Qwen Q4 speech, optional forced alignment, Index 9B Q4 translations to Traditional Chinese/Japanese, three embedded tracks and bilingual burning. It transcribes once across two requests. Speech/alignment workers exit before translation loads, releasing GPU memory. Alignment retains original punctuation/spacing. Japanese/Korean alignment tokenizers are bundled and their source tokenization checks pass.
- Existing Base/M2M100 offline translation and bilingual-export smoke still passes. CTranslate2 keeps its original cuBLAS preflight/fallback behavior; its GPU path is separate from the new runtimes.

## Packaged acceptance

- The actual 0.4.0 GUI shows enabled **Use** buttons for all nine verified installed packages in an isolated library. Clicking the installed Index 9B Q4 and Qwen ASR Q4 buttons selects the corresponding translation/recognition model and CUDA. Uninstalled models retain disabled Use controls. All three model tabs, Unicode previews/destinations and actual media downloads pass.
- The packaged persistent caption service passes Qwen Q4 transcription, BF16 forced alignment and Index 9B Q4 translation with CPU fallback disabled. It exports English, Traditional Chinese and Japanese tracks, verifies their IDs/times, default-track disposition and Unicode text extracted back from MP4, then burns bilingual captions using the same transcription.
- Original Index 9B successfully generates Chinese and Japanese translations with **7,716,481,888 bytes of GPU tensors plus disk offloading** on the RTX 5070 Ti Laptop. Its two short requests, including loading and verification, take approximately 216 seconds in this test. This is execution evidence, not a general benchmark; Q4 avoids this offloading and is the recommended fit for 12 GB VRAM.
- Cancelling a real packaged Index 9B Q4 CUDA request closes the owned worker/server process tree in approximately 2.7 seconds; a fresh helper then loads 34 GPU layers and completes another Japanese translation. No user application is terminated.
- The packaged Base caption queue still passes two-item processing, correction/re-export with previous exports retained, and active removal while keeping media. The packaged Base/M2M100 persistent translation smoke passes multilingual embedding and bilingual burning from one transcription.
- Builds and tests run separately. The versioned portable release bundles isolated CUDA runtimes and retains ICU exclusions. SHA-256 files cover release executables and every portable file; previous release artifacts are checked against their pre-build hashes. The per-user installer includes the same portable contents and validation documents.

## Validation limits

- English short fixtures and English-to-Chinese/Japanese translations establish execution only. Broader multilingual, long-recording, timing and translation quality review remains pending. ARK needs an explicit language for translation/alignment. Unaligned ARK/Qwen cues use estimated timing within VAD spans.
- Original weights are BF16. The 9B original package exceeds this 12 GB GPU and requires RAM/disk offloading; Q4 is the preferred fit. CPU original-weight inference uses FP32 and needs more RAM. No global CUDA toolkit is needed by the portable release, but a compatible NVIDIA driver is required.
- Fresh-VM installation, external-player compatibility and the earlier live YouTube download remain unverified. Smoke launches use isolated data and do not establish that the user has launched this release.

GPU reports, packaged selection screenshots and logs are under `.test-artifacts/gpu`. `installed-ui/report.json`, `remaining-packaged.json`, `index9-full-packaged.json`, `packaged-aligned-pipeline/report.json` and `cancellation/report.json` record the checks above. All nine test packages are completely installed and SHA-256 verified in `.test-artifacts/model-resources/source/models`.

# VideoDock 0.3.1 validation

Validated in this Windows workspace on October 7, 2026. The 0.3.0, 0.2.0 and older release folders/installers are preserved. All model tests use isolated libraries under `.test-artifacts/model-resources`; no user model library or queue is modified.

## Model download checks

- **81 automated tests pass; Ruff passes.** All 77 previous regressions remain covered, including the Windows open-stdin NumPy import regression.
- Added six original BF16 Safetensors packages and three exact Q4_K_M GGUF packages from `outputs/model_resources_translation_asr (1).md`. Every entry pins an immutable repository revision, exact per-file bytes and SHA-256 hashes. Full packages retain tokenizer/processor files and every weight shard; ARK also retains its pinned custom source files as files that VideoDock never executes.
- Source validation checks all nine pinned repositories, all weight file sizes/hashes against repository metadata, and public weight download URLs. GGUF selection excludes other quantizations and optional image projectors. No 4-bit source was supplied for ARK or ForcedAligner, so those entries expose original weights only.
- Tests cover complete catalog coverage, precision-specific files, shard index requirements, no automatic downloads, all nine Download actions, disabled inference selection for download-only models, installed-folder access, and multi-file resume/repair without publishing a corrupt shard.
- The source model manager downloaded the complete **1,312,171,442-byte Index-Translate-2B Q4_K_M package** in an isolated library after interruption/resume, then verified every file's full SHA-256 hash. An initial silent resume check was interrupted and rerun with progress logging; its partial bytes were retained and the resumed installation verified successfully.
- Source and packaged UI snapshots show Speech, Translation and Alignment tabs. Caption selectors keep their supported Whisper/M2M100 choices. All nine new packages are visibly **Download only**, with their precision, format, runtime, size and storage path shown; installed packages expose Open folder and remain unavailable for inference.

## Packaged checks

- The versioned portable application, console worker and per-user installer compiled successfully. The GUI and worker contain the same pinned catalog; model weights and ARK custom source modules are not bundled. The ICU exclusions and PeekNamedPipe/available-byte ReadFile implementation remain intact.
- The actual 0.3.1 bundled worker cancelled and resumed Index-Translate-2B Q4_K_M, downloaded the remaining bytes, verified the complete package and published it as installed. This packaged resume test seeds partial files from the already verified source test package, deliberately leaving 64 MiB of weights to fetch; it does not claim a second fresh full download.
- Packaged GUI startup, all three model tabs, Unicode link previews/destinations and real media downloads pass.
- The real persistent caption queue smoke passes two-item processing, CPU/GPU preflight fallback, correction/re-export with previous exports retained, and active caption removal while keeping media.
- The actual persistent translation worker passes Base transcription, Traditional Chinese/Japanese tracks, three embedded tracks and bilingual burning from one transcription, with stdin kept open across both requests. Native CUDA still falls back before initialization because cuBLAS is absent.
- Builds and smokes run separately. No running user application is terminated. SHA-256 checksums accompany the portable GUI, worker and installer under `dist`; previous 0.2.0/0.3.0 GUI, worker, installer and checksum files are checked against their pre-build hashes.

## Validation limits

- The nine added packages provide verified downloads, not integrated inference. Transformers, llama.cpp and transcribe.cpp are not bundled or connected to the caption pipeline. No new-model transcription, translation, alignment, GPU execution, quality or memory claim is made. ForcedAligner requires an existing transcript and audio.
- “Full precision” means the repositories' original BF16 weights, not FP32. The listed sizes include supporting files and describe storage rather than memory requirements.
- Only Index-Translate-2B Q4_K_M received a complete real download. Other new packages have pinned metadata/hash and reachable-weight-URL checks plus common downloader regressions; their complete multi-gigabyte downloads remain unexercised.
- Native GPU acceleration, multilingual/long-recording quality review, external-player compatibility and fresh-VM installation retain the 0.3.0 limitations below. Smoke launches are isolated validation and do not establish that the user has launched this release.

Reports, source/package screenshots and build logs are under `.test-artifacts/model-resources` and `.test-artifacts/packaged`. Caption and translation reports remain in their existing isolated test folders.

# VideoDock 0.3.0 validation

Validated in this Windows development workspace on October 7, 2026. The 0.2.0 portable folder and installer are preserved. All new tests use isolated databases, destinations and model libraries; the user's app is never terminated by build or smoke scripts.

## Automated and source checks

- Ruff passes; **77 automated tests pass**. All 60 previous regressions remain covered, including the open-stdin NumPy import, active removal, caption-only retry and migrated duplicate detection.
- New checks cover language settings and playlist overrides, N/A for empty language options, Simplified/Traditional script conversion, SRT/VTT import and rolling text, unsupported languages, stable IDs/timestamps, long input without text loss, empty input, per-language partial failures/retry, translation cache and cancellation/restart, manual-edit retention and edited-source invalidation, and private-folder migration for legacy correction without overwriting existing destination files.
- Real FFmpeg tests export three subtitle tracks to MP4 and WebM, verify the default track disposition, and extract every stream back to SRT to verify its Unicode text.
- M2M100's pinned 496,017,327-byte package was downloaded through the GUI controller into the isolated test library, cancelled, resumed, and verified against its file sizes and SHA-256 hashes.
- Real Base transcription and M2M100 CPU INT8 translation ran with socket connections blocked: an English fixture produced English, Traditional Chinese and Japanese sidecars and three embedded MP4 streams, followed by bilingual burning. The second export reuses source cues; no second transcription occurs. Runtime is approximately 4 seconds for this 11-second fixture with a warm filesystem cache; this is not a general benchmark.
- Native CUDA translation probing reproduced the missing `cublas64_12.dll`. Combining a failed CUDA speech runtime with translation initially hung in the diagnostic process. Windows cuBLAS preflight now selects CPU before initializing either GPU model, and fresh combined inference completes. CPU fallback can be disabled with an actionable error. Unit checks separately simulate GPU-memory failures and fallback.
- The cue editor exposes source/target language tabs and per-cue source-language overrides; source changes mark target tracks stale, and manual target edits survive regeneration unless the user selects their replacement.
- Model weights and test fixture assets are never taken from the user's library. Durable cue manifests/checkpoints remain under `.videodock-captions`; temporary derived audio/render work is cleaned.

## Packaged checks

The versioned portable app and installer compiled successfully. The 0.3.0 console worker includes SentencePiece, OpenCC dictionaries, CTranslate2 and the pinned model catalog; weights remain separate.

- The packaged GUI passed isolated startup/layout checks, Chinese-containing preview titles, Unicode destinations and real downloads through the bundled worker.
- The packaged persistent worker processed a fresh English Base transcription and M2M100 translations to Traditional Chinese/Japanese, embedded three selectable MP4 tracks with Traditional Chinese as default, and extracted every stream back to SRT with its Unicode text intact.
- A second request on the same open stdin pipe produced an English–Traditional-Chinese bilingual burn from the saved cues and translations. Exactly one transcription occurred across both requests. Caption IDs and timestamps matched the source, and the rendered CJK frame was retained for inspection.
- The existing packaged caption queue smoke also passed two-item persistent processing, correction/re-export with prior exports preserved, and removal of an active caption job while retaining media.
- Windows CUDA selections used the validated cuBLAS preflight and CPU fallback. Native GPU acceleration is not claimed.
- Build and smoke commands ran separately, avoiding concurrent vendor FFmpeg replacement/use. No running user app was terminated. SHA-256 release checksums accompany the artifacts under `dist`.


## Validation limits

- Native GPU acceleration remains unverified because this machine lacks CUDA cuBLAS; CPU fallback is exercised.
- The JFK fixture establishes execution, timing and track recovery. Translation quality needs representative multilingual and long-recording review. The Japanese sample is grammatically awkward around a cue boundary; do not infer production translation accuracy from successful execution. Per-cue translation can lose sentence context across subtitle boundaries.
- Real player compatibility across external players, CJK/RTL font fallback across other Windows installations, and a fresh Windows VM installer run remain manual/environment checks. ASS styling is tested with CJK/Arabic text; a bilingual CJK burn frame is rendered for visual inspection.
- Optional pair-specific Marian packages and automatic code-switch identification remain future enhancements; explicit per-cue language overrides are implemented.
- Live downloading the previously previewed YouTube video remains untested. Local HTTP and subtitle-source regressions do not establish its availability.

The source/package reports and screenshots are under `.test-artifacts/translation/`. The previous release validation follows for the inherited download and speech workflows.

# VideoDock 0.2.0 validation

Validated in this Windows 11 development workspace on October 6–7, 2026. Tests use isolated SQLite databases, media destinations and model storage; the user's existing queue and releases are retained.

## Automated checks

- Ruff lint passes and **60 automated tests pass**. The regression suite covers all existing download formats, caption exports, cancellation/resume, restart recovery, Unicode paths and update verification, including duplicate detection in migrated 0.1.x databases.
- Added playlist interval checks cover inclusive ranges, invalid ranges, overlapping ranges, original-number gaps, playlist scope, ordering and per-item settings.
- Queue removal checks cover pending and active jobs, preserved partial files/history, and adding the same download again.
- Model checks cover pinned hashes/sizes, resumed range downloads, corruption/repair, full-disk errors, cancellation, and preventing removal while locked.
- Caption checks cover persisted settings/revisions, caption-only retries, missing-model waits, available/missing YouTube fallback languages, long-timeline cue formatting, offline exports/re-exports, audio sidecars, English-only settings and GPU-memory fallback.

## Real runtime and package checks

- Downloaded the pinned Whisper Base package through the GUI controller, cancelled it, resumed its partial files, and verified the complete installation.
- Ran Base CPU INT8 on the SHA-256-pinned public JFK speech fixture from the OpenAI Whisper test repository. Socket connections were blocked during source transcription. Tokenizer and bundled Silero VAD loaded offline.
- Generated SRT with word timestamps, embedded MP4 captions and burned synchronized captions into a separate output. Original media remained present.
- Generated MP3 VTT sidecars with automatic spoken-language detection.
- NVIDIA hardware was detected, but `cublas64_12.dll` was absent. Actual GPU execution raised a library error and correctly retried on CPU. CPU fallback can be disabled.
- The versioned portable GUI and console worker passed real HTTP downloads, Unicode title preview/destinations, and a persistent two-item local caption session.
- Updated source layout was inspected at 1100 × 740; the queue stays visible and both settings/addition panes scroll independently.
- PyAV 19 removed `metadata_errors`, which faster-whisper 1.2.1 uses. PyAV is pinned to the verified 16.0.1 runtime.
- A blocking Windows stdin reader can deadlock NumPy initialization. Worker requests/control messages now poll the native pipe and read only available bytes. A regression test keeps stdin open during the actual NumPy import.

The test reports and screenshots live under `.test-artifacts/`. An 11-second English fixture took about 1.3–1.5 seconds for CPU transcription/sidecar export and 1.6–1.7 seconds including burned output on this machine with a warm filesystem cache. These figures are not benchmarks for larger models or long recordings.

## Validation still requiring other environments/media

- Native GPU execution with CUDA/cuBLAS and cuDNN installed; full GPU memory/performance measurements.
- A fresh Windows VM installer test; current package tests run isolated from user data on the development machine.
- Real multilingual and long-recording accuracy/timing evaluations, and measured hardware guidance for Small, Turbo, Large v3 and Distil v3.5. Those presets are cataloged and supported, but only Base weights were exercised here.
- The previously previewed live YouTube video remains untested as a download; local HTTP acceptance does not establish its availability.

These are validation limits, not hidden automatic model downloads or online transcription requirements. No transcription service or API key is used.
