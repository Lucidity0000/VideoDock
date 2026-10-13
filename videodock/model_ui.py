"""Shared installation state for the model library and settings selectors."""

from PySide6.QtCore import Qt

from .caption_models import is_ready, model_spec


def refresh_selector(combo, root, workers, states):
    combo.blockSignals(True)
    try:
        for index in range(combo.count()):
            key = combo.itemData(index)
            if not key:
                continue
            spec = model_spec(key)
            installed = is_ready(root, spec)
            state = model_state(root, spec, workers, states)
            combo.setItemText(index, f"{spec['title']} · {state}")
            combo.setItemData(index, f"{state}\n{spec['bytes']:,} bytes · {spec['license']}",
                              Qt.ItemDataRole.ToolTipRole)
            combo.model().item(index).setEnabled(installed and key not in workers)
    finally:
        combo.blockSignals(False)


def model_state(root, spec, workers, states):
    key = spec["id"]
    if key in workers:
        progress = states.get(key, {})
        total = progress.get("total") or spec["bytes"]
        percent = min(100, int(progress.get("bytes", 0) / total * 100))
        return f"{progress.get('state', 'Downloading…')} · {percent}%"
    if is_ready(root, spec):
        return "Installed"
    progress = states.get(key, {})
    return "Retry / resume" if progress.get("state") == "Retry / resume" else "Not downloaded"


def refresh_download(combo, status, download, root, workers, states):
    key = combo.currentData()
    if not key:
        status.setText("Optional word alignment is off.")
        download.setEnabled(False)
        return
    spec = model_spec(key)
    installed = is_ready(root, spec)
    state = model_state(root, spec, workers, states)
    status.setText(f"{state} · {spec['bytes'] / 1024**3:,.2f} GiB · {spec['license']}")
    status.setToolTip(states.get(key, {}).get("message", ""))
    download.setText("Installed" if installed and key not in workers else
                     "Downloading…" if key in workers else
                     "Resume download" if state == "Retry / resume" else "Download selected model")
    download.setEnabled(not installed and key not in workers)
