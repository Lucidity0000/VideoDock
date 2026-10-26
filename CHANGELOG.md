# Changelog

## 0.6.1 — 2026-10-27

- Move the shared/custom Settings indicator from preview rows into all three queues, with current shared-value comparisons and difference tooltips.
- Add **Apply all changed** to bulk editing. Apply every edit made since the dialog opened while preserving unedited mixed values and atomic stage locks.
- Hide cancelled schedules immediately and after reopening the panel, while retaining their disabled state in local records.
- Rebuild the GUI in a separate local release; retain the verified 0.6.0 worker/native runtimes and all previous release artifacts.

## 0.6.0 — 2026-10-26

- Add atomic field-selective editing for selected pending jobs and comparisons against current shared settings.
- Add persistent per-stage date/time schedules, individual job holds, drag-and-drop queue order and timestamped job timelines.
- Add opt-in tray operation, independent completion/failure notifications and per-run sleep/hibernate/shutdown with a cancellable countdown.
- Add selected transient-failure retries with persistent bounded backoff, an explicit fallback speech model and durable 30-second transcription checkpoints shared by all speech backends.
- Preserve local 0.5.0 release artifacts and block builds from replacing an existing release target. Older distributions were privately archived and removed during the October 20 cleanup; deleted model packages are not restored.

## 0.5.0 — 2026-10-20

- Add saved, independent auto-start options for download → captioning and captioning → translation. Explicit pauses and paused startup remain respected; handoffs wait for worker cleanup and retain one inference slot.
- Add favorite playlists and custom lists on Downloads. Save checked entries or an empty list, load the saved snapshot, append checked entries from any preview, rename, remove multiple entries or delete the list. Original links remain reference information; queue/history/files are independent.
- Preserve original entry metadata/order, deduplicate videos within each list and migrate existing databases without changing queue records.
- Include the current project license, credits, citation and distribution documents in the local portable/installer builds. Full binary redistribution requirements remain incomplete.
- Validate 121 tests, Ruff, 79 source layout captures, packaged startup/list editing/model selection/download checks and real Base/M2M100 automatic and manual handoffs. Keep the existing Qwen short-fragment limitation and prior inference/compatibility limits explicit.

## 0.4.4 — 2026-10-13

- Refresh the dark theme, navigation, model cards, status colors and vector UI controls.
- Add guidance to empty preview/queue/history tables and show the checked-item count.
- Keep preview actions and a preview row accessible at 1100 × 680; expand playlist intervals with **Ranges…**.
- Display external titles/errors literally and clear stale preview details/actions on reset.
- Retain the 0.4.3 multi-selection caption fix and unchanged worker/inference runtimes.
- Validate 107 source tests, Ruff, 74 layout captures, packaged startup/navigation, installed-model selection and a real local-server download. Preserve 42 previous release artifacts and verify 14,950 reused runtime files against 0.4.3.

### Initial public source publication

- Apply MIT to original VideoDock code/assets and add upstream acknowledgments, primary research citations and citation metadata.
- Correct the distinction between yt-dlp's Unlicense source and its GPLv3+ official Windows executable.
- Exclude environments, caches, model weights, binaries, private media and databases from the repository.
- Split Windows CI into source checks and an explicit internal build option; do not publish bundled binaries until the requirements in [DISTRIBUTION.md](DISTRIBUTION.md) are completed.

The known Qwen short-fragment decoder repetition limitation remains. Functional checks do not establish broad model accuracy, fresh-VM compatibility or binary redistribution compliance. See [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md).
