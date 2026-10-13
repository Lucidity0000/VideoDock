# Changelog

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
