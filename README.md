# VideoDock

A Windows desktop app for inspecting video links, selecting playlist entries, and downloading a persistent queue. Built with Python, PySide6, SQLite, yt-dlp, and FFmpeg.

VideoDock is an independent project made possible by the upstream communities acknowledged in [CREDITS.md](CREDITS.md). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency licensing and [CITATION.cff](CITATION.cff) for software citation metadata. Use it with media you are authorized to obtain and process.

Original VideoDock code and original SVG assets are available under the [MIT License](LICENSE). Third-party software and optional model packages keep their own licenses.

The 0.6.0 update adds bulk queue editing, comparisons, scheduling, tray controls, recovery and timelines. The previous local 0.5.0 release remains intact. Public binary distribution requires the source/notice material and asset packaging described in [DISTRIBUTION.md](DISTRIBUTION.md); source publication and functional validation do not by themselves establish binary redistribution readiness.

## Run on Windows

The 0.6.1 application is `dist/VideoDock-0.6.1/VideoDock.exe`, with installer `dist/VideoDock-Setup-0.6.1.exe`. The portable folder includes its tools and caption runtimes; keep the entire folder together. The 0.5.0 and 0.6.0 portable folders, installers and SHA-256 files are preserved. Build scripts refuse existing release targets; use a new version and folder for another build.

For a source installation, use Python 3.11 or newer:

```powershell
.\setup.ps1
.\start.ps1
```

If Python is not on PATH, pass its full executable path to `setup.ps1 -Python <path>`. Setup creates a local `.venv`, installs the pinned Python dependencies, and downloads verified Windows x64 tools into `vendor/`. It does not install tools globally.

An already configured environment can run `python -m videodock`. `python -m videodock --diagnose` prints dependency locations.

## Use

1. Paste one or more video/playlist links, or import a UTF-8 text file. Blank lines and lines starting with `#` are ignored.
2. Click **Preview links** (Ctrl+Enter). Select all entries or choose individual videos; the selection count updates beside the preview actions. Open **Ranges…**, choose a playlist and enter inclusive original positions such as `1-5, 8, 12-20`. **Select ranges** changes its checkboxes; **Add ranges** queues exactly those entries with their per-item settings. Overlapping ranges add each entry once. Missing/private positions remain gaps; playlist order and filename prefixes use the original numbers.
3. Select a preview row and click **Inspect selected** to load its available video resolutions and caption languages. **Item settings** overrides the shared settings for that entry.
4. Open the independent **Download settings** page to choose format, resolution, audio quality and captions. Its sections are **Media**, **Captions**, **Translation** and **Subtitle style**. **Save defaults** remembers these choices; adding a batch also saves them. Back in **Downloads**, choose **Save to → Browse…**. **Open** beside Browse opens that folder in Windows File Explorer to inspect its files. Add selected entries, choose **Downloading**, and click **Start queue**. Queued items keep their original settings.
5. Downloads has separate persistent **Downloading**, **Captioning** and **Translating** queues. Start or pause each queue separately, or enable **Auto-start captioning after download** and **Auto-start translation after captioning** to run the enabled stages after one download-queue start. Both options are saved and initially off. Adding work alone never starts a paused stage. A successful handoff resumes the entire next queue, including older pending entries. An explicit **Pause queue** holds that stage even across later handoffs until you start it or re-enable its auto-start option. The app always opens with all queues paused. Media download/conversion finishes before caption acquisition/transcription. Completed source cues move to the translation queue before translation/export. Captioning and translation share one inference slot; downloads run independently. Each queue displays its own status and progress. Downloading also shows speed and ETA. **Pause queue** lets active jobs finish and stops starting new jobs. **Cancel selected** interrupts jobs; **Retry selected** preserves and resumes partial downloads where the server supports it. **Remove selected** stops active work and removes entries from the queue while keeping history, completed media and partial files. Removed entries no longer prevent adding the same download again.

### Favorite playlists and custom lists

Open **Saved lists…** on Downloads. Preview a playlist or any video links, check the entries to keep, then choose **Save as…**, enter a name and choose **Favorite playlist** or **Custom list**. Uncheck **Include checked preview entries** to create an empty list. Both types store an editable local snapshot; the original links are reference information and are never automatically synchronized.

Choose a list and click **Load list** to restore its entries into the preview without fetching the original playlist. Current download settings apply, and per-item overrides can be set before queueing. **Inspect selected** refreshes formats and caption languages. To extend any saved list, preview links from any source, choose the list and click **Add selected**. Videos already in that list are skipped by video identity. **Edit list…** supports renaming, removing multiple entries and deleting the list. Load it again to see edits in the preview. These edits leave queued jobs, history and files intact. Lists and their entry order survive restart in the app database.

Caption choices distinguish creator-provided and automatic captions. The language field uses exact source codes (for example `en`, `en-orig`, or `zh-Hant`). Missing languages fail with available alternatives instead of silently omitting captions. SRT/VTT files are retained for every caption mode. Video supports embedding and optional burned captions. MP3 and M4A always save captions separately.

## Local captions

**Caption source** offers **Off**, YouTube creator/automatic captions, **Local model**, and either YouTube source with **local fallback**. Local model always transcribes the audio. Fallback uses the exact selected YouTube language when available, otherwise the local model. Settings are saved with each queued item, including its pinned model revision; **Item settings** supports overrides within a playlist or batch.

Open the single **Models** page to manage speech, translation and alignment packages. Each model shows language coverage, exact download bytes, license and installation status; hover over its details/status for the pinned revision and storage path. **Download** downloads only that package. You can cancel, resume, retry/repair, remove, or select an installed model with **Use**, which opens the relevant Download settings section. Settings selectors label installation state and disable unavailable packages. A saved choice that is missing stays visible with **Not downloaded**, so you can restore it with its download button or select an installed replacement. Selection, progress, completion, removal and storage changes refresh status immediately. Files are staged, checked against their SHA-256 hashes, and published as ready only after verification. Downloads of the same model are deduplicated, and files cannot be removed or repaired while the model is in use. Changing model storage selects a separate library without moving or deleting the previous one.

| Model | Coverage | Pinned package bytes | Use |
|---|---|---:|---|
| Base | Multilingual | 147,882,941 | Lightweight CPU option |
| Small | Multilingual | 486,212,372 | Default CPU preset |
| Large v3 Turbo | Multilingual | 1,621,665,983 | Default compatible-GPU preset |
| Large v3 | Multilingual | 3,090,835,702 | Quality preset |
| Distil Large v3.5 | English only | 1,516,479,656 | English preset |

The storage folder is independent of the media destination. Models are shared across jobs. Jobs needing an absent model show **Waiting model**; select those entries and click **Download required model**. No model weights are included in the installer or downloaded automatically. The runtime, tokenizer support and Silero speech detector are bundled. After installing a model, local transcription needs no connection, uploads, account or API key.

Choose the **spoken language** (`auto`, `en`, `zh`, `ja`, etc.) separately from the YouTube language. Local captions use the spoken language. Choose **Chinese caption script** to keep the original script or explicitly convert Chinese captions to **Simplified** or **Traditional Chinese** with OpenCC. This also applies to downloaded Chinese captions. The YouTube language selector shows **N/A** when the inspected source has no available caption languages; it does not invent an English option. CPU uses INT8. NVIDIA GPU uses FP16 and needs compatible CUDA 12/cuBLAS and cuDNN 9 libraries on PATH. **Use CPU if GPU is unavailable** enables fallback for missing GPU hardware/libraries or GPU execution failure; uncheck it to fail with an actionable error. Larger models need more memory; use Base when memory is limited. Package bytes are storage sizes, not RAM/VRAM requirements.

Only one caption job runs at once, in a persistent worker that reuses the loaded model. Downloads continue independently. FFmpeg prepares temporary 16 kHz mono audio; VAD and word timestamps preserve the original timeline. Line length and maximum cue duration are configurable. The queue shows processed duration and recent caption text. Caption failure/cancellation keeps the media, and **Retry selected** retries captions without downloading again. Transcription saves completed 30-second segments and resumes from the next incomplete segment, including after restart.

### Queue controls and recovery

Select one or more queue rows, then open **More…**:

- **Edit selected pending jobs…** opens the saved settings for the first selected job. Check the fields to apply, adjust their values and click **Apply**. Alternatively, **Apply all changed** applies every field edited since opening the dialog without requiring checkboxes; unedited or reverted fields retain each job's saved values. Every selected job must be pending and have no active worker. Media settings lock after download; source settings lock once source captions are saved. Completed/active jobs cannot be edited. The complete selection is validated before any edit is saved.
- **Compare selected with shared settings…** shows each differing setting, the current shared value and the saved item value. The **Settings** column in each queue shows **Shared** or **Custom** against the current shared values; hover for the differences. The preview table no longer has this column, but retains item editing and right-click comparison. Changing shared defaults updates the indicator without changing queued jobs.
- **Pause selected jobs / Resume selected jobs** holds individual entries. Downloading/inspection and speech/translation stages stop through normal cancellation, retaining partial media and checkpoints; an incomplete speech segment may run again. Conversion/export cannot pause safely and must finish. Resuming releases the individual hold; a paused queue still needs **Start queue**. Queue-wide **Pause queue** continues to let active jobs finish.
- **Queue schedules…** saves one-time Start, Pause and Resume actions per queue at a local date/time, stored in UTC. VideoDock must remain open or in the tray; schedules do not wake a sleeping or powered-off PC. Pending schedules that became overdue while the app was closed are marked **missed** at launch. Cancelling a schedule removes it from the panel immediately and keeps it hidden when reopened; its cancellation remains recorded locally and cannot execute.
- **Background and completion…** independently enables completion/failure desktop notifications and optionally closes the window to the system tray. The tray menu starts/resumes or pauses each queue, opens the window and exits. System notification settings can suppress balloons. Without a system tray, keep the window open.
- The same dialog can arm **Sleep**, **Hibernate** or **Shut down** for the current run. The default is **Do nothing**. An action requires all queues to finish successfully, no held/waiting/retry jobs, no model/background operation and no future schedule. A visible 60-second countdown can be cancelled; new pending work cancels it. The action disarms after use, cancellation or exit. Windows power support and permissions apply. Shutdown does not force-close other applications.
- Drag selected pending rows within their queue to change execution order. Multiple rows retain their relative order, and the new order survives restart. Active jobs cannot be moved. Double-click a queue/history row or choose **Job timeline…** for timestamped transitions, setting/order changes, pauses, retries, segment recovery and errors. Older jobs have events only from this version onward.

**Download settings → Media → Automatic retries** selects connection/timeouts, HTTP 429 rate limits and/or HTTP 500/502/503/504 failures. Retries are off by default, bounded to 0–10 per stage and use exponential delays capped at one hour. Retry timing/counts survive restart and respect queue/job pauses. Authentication, missing/private media, disk/permission problems, model memory errors and decoder repetition require review. A manual retry resets the retry budget.

**Download settings → Captions → Failed segment fallback** optionally selects a different speech model. Only a failed 30-second segment is attempted with that model; completed segments remain saved. Missing models still require an explicit download on Models. Both failures are reported if fallback fails. Checkpoints record the model used for each segment and validate source path/size/modification time, speech settings and segment boundaries before reuse. Changed speech settings restart transcription checkpoints; output/translation or retry-policy changes retain completed speech segments. Fixed segment boundaries can affect words and context near cuts; execution checks do not establish transcription accuracy.

**Settings and dependencies → Import local media for captions…** adds existing audio/video using the current local model settings and destination. In **History**, select multiple rows with Ctrl-click or Shift-click, then click **Generate captions** once to queue all selected saved media with the current local model settings. Each item keeps its own destination. Missing files and jobs still finishing are reported as skipped; other selected items are queued. This opens the Captioning queue; click **Start queue** if it is paused. Audio always receives a sidecar. Embedding and burning create separate video outputs and retain the original. **History → Correct / re-export captions** opens local caption text and start/end seconds for corrections; re-export creates new files and preserves previous exports. An editable `.cues.json` accompanies locally generated subtitles. No speech produces an empty subtitle sidecar and retains the original media.

Local acceptance measurements on this development machine: Base CPU INT8 transcribed and exported an 11-second English fixture in approximately 1.3 seconds with a warm filesystem cache; burned output took approximately 1.7 seconds. GPU selection on the RTX 5070 Ti Laptop fell back to CPU because cuBLAS was absent. These short-fixture measurements do not establish long-recording accuracy or performance of other presets. Upstream [faster-whisper benchmarks and GPU requirements](https://github.com/SYSTRAN/faster-whisper) provide additional guidance; representative multilingual/long-recording and full GPU measurements remain pending.

## Additional local models and GPU

**Models** includes the packages listed in the [pinned model catalog](videodock/model_catalog.json), grouped into **Speech models**, **Translation models** and **Alignment models**. Each precision has its own Download, Cancel, Resume / retry, Repair and Remove actions, plus **Open folder** after installation. Packages use immutable repository revisions, exact byte sizes and per-file SHA-256 verification through the existing model library. No weights are bundled or downloaded on launch.

| Model | Original weights: full precision BF16 | 4-bit Q4_K_M GGUF |
|---|---:|---:|
| Index-Translate-2B | 4,571,142,860 bytes | 1,312,171,442 bytes |
| Index-Translate-9B | 19,329,300,742 bytes | 5,780,097,395 bytes |
| ARK-ASR-0.6B | 2,620,242,346 bytes | No source supplied |
| ARK-ASR-3B | 8,143,004,837 bytes | No source supplied |
| Qwen3-ASR-1.7B | 4,087,644,754 bytes | 1,319,893,217 bytes |
| Qwen3-ForcedAligner-0.6B | 1,847,235,286 bytes | No source supplied |

“Full precision” follows the supplied resource list: these repositories publish original **BF16**, not FP32, Safetensors weights. Full packages include tokenizer/processor configuration and all weight shards. Verified pinned ARK custom Python modules run in the isolated inference worker. Index GGUF downloads select only Q4_K_M and supporting documentation/checksums; image projectors and other quantizations are unnecessary for text translation and are excluded. Qwen GGUF uses the exact Q4_K_M artifact from the supplied community repository. The three entries without a 4-bit link have only their original-weight variants.

Installed packages enable **Use**. Speech models select the local recognizer, Index models select the translation model, and ForcedAligner selects optional word alignment for the current recognizer. Use selects NVIDIA GPU for these additional models. The portable app bundles Transformers/Torch CUDA, llama.cpp CUDA, transcribe.cpp CUDA and their redistributable libraries in a separate process. No global CUDA toolkit is required; a compatible NVIDIA driver is required. CPU remains selectable, and the existing CPU fallback setting applies. The queue reports the actual inference backend/device and any fallback or offloading.

Original weights use BF16 on GPU; GGUF uses the downloaded Q4_K_M weights. On a 12 GB GPU, prefer the 9B Q4 package. The original 9B weights exceed VRAM and automatically offload to available RAM/disk while retaining GPU layers; this needs additional storage and can be slow. Package sizes describe storage rather than peak memory use. Full-weight CPU inference uses FP32 and can require considerably more RAM.

ARK and Qwen speech run over bounded VAD spans. Without alignment, their cue times are estimated within those spans. **Word alignment** applies Qwen3-ForcedAligner to the audio and transcript for word timing in its 11 supported languages. It cannot recognize speech on its own or align an imported SRT without audio. ARK does not report a detected language: specify **Spoken language** or a source-language override before translation/alignment. The shared translation selector offers the existing 100-language set; Index's upstream coverage is broader. Review generated captions/translations before use; execution checks do not establish accuracy for all languages or long recordings.

`python tools/lock_resource_models.py` explicitly refreshes only these nine catalog entries, validating required supporting files, shard indexes and original precision while fetching metadata and small files. It never downloads weights. The Whisper and M2M100 refresh tools preserve these additional entries.

`python tools/smoke_resource_models.py --check-sources` checks all nine pinned repositories and weight URLs without downloading weights. Add `--download` to explicitly install and fully verify Index-Translate-2B Q4_K_M in `.test-artifacts/model-resources/source/models`, including cancellation/resume through the model manager. After building, `--download --packaged --seed-from-source` tests the bundled worker's cancellation, ranged resume and complete verification using verified source bytes as a partial-file seed, leaving 64 MiB to fetch. Test packages remain separate from the user's library.

## Translation and multilingual subtitles

Enable **Download settings → Translation → Translate subtitles**, then check one or more searchable target languages. Translation is off by default. Keep the original subtitles, optionally add a bilingual original/translation pair, and choose the pair's text order. These settings are saved with queued items and support playlist/batch overrides. The source-language override is separate from both the YouTube caption code and the local spoken-language setting. Whisper reports one detected language for the recording; it does not reliably identify every mixed-language segment. The editor supports explicit source-language overrides for individual cues.

**Models** has **Speech models**, **Translation models** and **Alignment models** tabs. **M2M100 418M** is a pinned, MIT-licensed CTranslate2 INT8 conversion with 100 language directions, a SentencePiece tokenizer, and a **496,017,327-byte** download. Use **Download translation model** or the manager to install it. Downloads require an explicit click, support cancellation/resume/repair, verify every file, and never download weights automatically. No translation model weights ship in the installer. It uses the existing model storage, device selection and CPU fallback controls. Native CUDA requires cuBLAS; unavailable Windows cuBLAS is detected before initializing GPU models. CPU translation and transcription work offline without an account, upload, service or API key.

M2M100 generates generic Chinese. **Chinese (Simplified) · zh-Hans** and **Chinese (Traditional) · zh-Hant** explicitly apply OpenCC conversion after translation. Full tags are retained in filenames, track titles and editable records, with ISO 639-2 metadata for MP4. The initial package supports many-to-many translation; optional pair-specific Marian packages have not been added.

- **Separate files:** export one collision-safe SRT/VTT per language, with an accompanying editable cue JSON. MP3/M4A always keep sidecars.
- **Embed:** export selected languages as separate selectable tracks using MP4 `mov_text` or WebM `webvtt`. Set **Embedded track order** with comma-separated full tags and **Default track language**; blank uses the first track. Bilingual tracks display both texts at once.
- **Burn:** choose the original, a target, or a bilingual pair. Set font, size, hex color and position using the style preview. A styled ASS intermediate renders the text into a new video. The original media and subtitle files remain available. The style preview is illustrative; exported placement scales with video dimensions.
- **Import SRT/VTT…:** choose UTF-8 subtitle files and set **Source language override**. No speech model is required. **Imported SRT/VTT** in the caption source selector can also apply an imported subtitle file to media being downloaded.
- **History → Translate / add languages:** reuse saved source cues/subtitles and media without downloading or transcribing again. Select targets in the shared settings first.
- **History → Correct / re-export captions:** language tabs show source and target text, times, cue-level source-language overrides and readability indicators. Source changes mark translations stale. Re-export creates new subtitle/media files and preserves previous exports.
- **History → Retry / regenerate language:** retry one target independently. Manual translations are kept by default; explicitly choose to regenerate manual edits to replace them.

The pipeline acquires source cues once, preserves stable cue IDs and timestamps, and translates every target directly from that source. Overlapping rolling YouTube text is de-duplicated. Oversized inputs are split without dropping tokens; reaching the output limit fails that language instead of silently truncating it. Empty source cues produce empty subtitles without invented dialogue. Successful tracks remain available if another target fails; the job reports **Partial** and each track keeps its error.

Source cues, track manifests and completed translation checkpoints live under `<destination>/.videodock-captions/<job-id>/`, outside disposable audio/render directories. Keep this folder for editing and restart recovery. A cache keyed by source text/language, target, model revision and decoding settings avoids repeating completed work. Source edits invalidate affected text through those keys; manual target edits remain until explicitly regenerated. Only one inference stage runs at a time, releasing speech weights before loading translation. Downloads continue independently.

The automated suite and opt-in smoke cover script conversion, subtitle import, source reuse, partial target failures, cancellation/checkpoint recovery, manual edits, per-cue overrides, multi-track MP4/WebM extraction and default metadata. Run `python tools/smoke_translation.py --download` to explicitly install the isolated translation test package and exercise real offline English → Traditional Chinese/Japanese output, three embedded tracks and bilingual burning from one transcription. Run `python tools/smoke_translation.py --packaged` after the release build to exercise two requests through the bundled persistent worker with stdin kept open. Test assets and models remain under `.test-artifacts/`, separate from the user's library. Review model translations before use; short-fixture execution does not establish multilingual accuracy, long-recording quality or player compatibility across every player.

MP4 output uses H.264 video and AAC audio. WebM uses VP8/VP9/AV1 with Opus/Vorbis. Compatible streams are preferred; FFmpeg encodes incompatible streams when conversion is enabled. Resolution is a maximum, with the best source up to that limit selected. Unknown-resolution sources are checked after downloading and downscaled if needed. Changing a file extension never substitutes for conversion. Audio quality presets select the output bitrate; transcoding cannot improve the original source quality.

Two jobs run at once by default; change this to 1–4 in **Settings & dependencies**. Shared settings can be saved with **Save defaults**, and settings and the default destination are remembered when adding a batch. Uncheck **Remember destination** for a temporary batch location.

History retains completed, failed and cancelled jobs, with independent **Download**, **Captions** and **Translation** results. **Clear cancelled history** removes cancelled records, and **Clear selected history** removes selected terminal records (Ctrl/Shift selects multiple rows). Active or pending jobs cannot be cleared. Clearing retains media, subtitles, editable checkpoints and partial files. Sort by updated time, added order, title, result or format; choose ascending/descending presets or click any column header. Sorting is remembered, and worker updates preserve the selected records. Duplicate detection compares the video identity, output settings and destination. Completed jobs are skipped only while the recorded output still exists. Existing files are preserved; explicit duplicate downloads get numbered filenames. Filenames retain Unicode and are sanitized for Windows. Templates must include `%(id)s` and cannot create folders.

## Persistence and recovery

Windows data is stored at `%LOCALAPPDATA%\VideoDock\videodock.sqlite3`. Set `VIDEODOCK_DATA_DIR` to use another data directory. A single-instance lock prevents two windows from operating the same queue.

Interrupted active jobs return to their download, caption or translation queue on launch; individual holds and completed stages stay intact. The app opens paused so you can review the recovered queue before resuming. Partial media remains at `<destination>/.videodock/<job-id>/`; cancellation does not erase it. Closing stops workers and preserves unfinished jobs unless close-to-tray is enabled. Transcription checkpoints remain in `<destination>/.videodock-captions/<job-id>/transcription.json`; temporary derived audio is cleaned.

Caption settings/status, original media, subtitle paths, processed duration and installed-model records are migrated into the existing database automatically. Interrupted caption or translation jobs return to the appropriate queue. Derived caption audio is cleaned on completion, failure or graceful cancellation; directories left by forced worker termination are cleared when that item is retried.

Destination checks test write access and free space before download and conversion. Media is validated with ffprobe before publication. Captions and output filenames are reserved before publication to preserve existing files.

## Dependencies and updates

Windows builds include FFmpeg, ffprobe, Deno, and the official yt-dlp executable (including its EJS components). Source installs also include `yt-dlp[default]` as a fallback. Tools can be supplied in `vendor/` or on PATH. Check their detected locations in **Settings & dependencies**.

**Check engine update** reads the official yt-dlp GitHub release. **Install verified update** checks the release asset's SHA-256 digest, exact size, and reported version before atomically installing it under the app data directory. The current engine is retained on any failure. Installation pauses the queue and requires active jobs to finish first. The app does not enable remote EJS script downloads.

`packaging/dependencies.lock.json` records the exact bundled release URLs and SHA-256 hashes. `python tools/fetch_dependencies.py --refresh` deliberately resolves and locks newer tool versions. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for licenses and source references.

## Development and release builds

```powershell
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
.\packaging\build.ps1
```

The release script verifies tools, builds the isolated inference helper, console caption worker and windowed GUI with PyInstaller, and compiles a per-user installer with Inno Setup. Setup prepares the helper's separate `.venv-inference` with dependencies pinned in `requirements-inference.lock.txt`; `packaging/inference-runtime.lock.json` pins the native CUDA assets. If no compiler is installed, a SHA-256-pinned Inno Setup compiler is staged in portable mode inside `build/`; no system installation or file associations are created. An existing compiler can be passed with `-ISCC <path>`. Use `-SkipInstaller` to validate the portable build before compiling the installer. Keep builds separate from tests because dependency extraction replaces vendor files. Build outputs are unsigned. `.github/workflows/windows.yml` runs lint/tests on pushes and pull requests. A manual build option prepares the dedicated inference environment and checks the packaged app; it uploads validation reports only. Public binary releases require the redistribution material in `DISTRIBUTION.md`.

The automated acceptance suite uses an HTTP media server and real yt-dlp, FFmpeg and ffprobe. It covers all four formats, caption timing/embedding/burning, audio caption sidecars, ordering and per-item overrides, duplicate preservation, mixed-success batches, process cancellation, HTTP-range resume, restart recovery, Unicode, unavailable videos, full/unwritable destinations, and update integrity failures. Network-independent tests do not establish that a particular live YouTube video is available from a given account/network.

`python tools/smoke_captions.py --download` explicitly downloads Base into `.test-artifacts/local-captions/models`, interrupts/resumes it through the GUI controller, verifies all files, and tests real offline transcription with socket connections blocked, embedding, burning and GPU fallback. It uses the SHA-256-pinned public JFK fixture from OpenAI Whisper's test repository. Run `python tools/smoke_captions.py --packaged` after building to test the actual bundled persistent caption worker. `tools/lock_caption_models.py` is an explicit developer-only catalog refresh; the app never resolves unpinned model revisions. Runtime versions are pinned to avoid the incompatible newer PyAV audio API.

Architecture: `ui.py` / `caption_ui.py` contain the PySide6 screens; `store.py` handles SQLite migrations and snapshots; `controller.py` schedules independent download, caption and translation queues, one shared inference service, and model operations. `engine.py` downloads and publishes media before deferred caption work. `captions.py` prepares audio and transcribes; `caption_pipeline.py`, `subtitles.py` and `translation.py` normalize, checkpoint, translate, export and re-export per-language tracks. `translation_ui.py` contains the translation controls. `caption_models.py` installs hash-verified packages from `model_catalog.json`; ARK's pinned custom modules run only in the isolated inference helper after verification. `additional_captions.py` adapts the additional speech/alignment models, and `inference_client.py` / `inference_worker.py` manage their private offline CUDA processes. `worker.py` exposes the UTF-8 JSON protocol for disposable download/model workers and the persistent caption worker. The windowed GUI excludes ML DLLs; the console worker contains faster-whisper, CTranslate2, PyAV and the bundled ONNX VAD asset.

Python paths, storage and process execution support future macOS/Linux builds. On those platforms install FFmpeg/ffprobe and Deno 2.3+ or Node 22+ on PATH, then `pip install .` and run `videodock`. Windows x64 is the packaged/tested release target.

Chapter selection and saved named presets remain later additions.

Older local distributions were privately backed up and removed on October 20, 2026. Historical validation statements that they remained locally describe the earlier validation dates. Recovery instructions and SHA-256 readback/restoration receipts are in `.test-artifacts/distribution-backup/2026-10-20/maintenance-summary.md`. The four intentionally deleted model packages remain unavailable until explicitly downloaded; this update does not restore them. The 0.5.0 publication folder is a local source snapshot, not Git staging or a GitHub upload; the last known public source is 0.4.4. No public binary publication or completion of redistribution obligations is claimed.

