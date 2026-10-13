import hashlib
import re
import threading

import pytest

from tools.lock_resource_models import select_files
from videodock import caption_models
from videodock.caption_models import catalog, download_model, is_ready, task_models
from videodock.caption_ui import ModelManager
from videodock.controller import QueueController
from videodock.models import DownloadSettings
from videodock.ui import SettingsPanel

EXPECTED = {
    "index-translate-2b-full": ("translation", "bf16", "IndexTeam/Index-Translate-2B"),
    "index-translate-2b-q4-k-m": ("translation", "q4_k_m", "IndexTeam/Index-Translate-2B-GGUF"),
    "index-translate-9b-full": ("translation", "bf16", "IndexTeam/Index-Translate-9B"),
    "index-translate-9b-q4-k-m": ("translation", "q4_k_m", "IndexTeam/Index-Translate-9B-GGUF"),
    "ark-asr-0.6b-full": ("speech", "bf16", "Edge0/ARK-ASR-0.6B"),
    "ark-asr-3b-full": ("speech", "bf16", "Edge0/ARK-ASR-3B"),
    "qwen3-asr-1.7b-full": ("speech", "bf16", "Qwen/Qwen3-ASR-1.7B-hf"),
    "qwen3-asr-1.7b-q4-k-m": ("speech", "q4_k_m", "ldov/Qwen3-ASR-1.7B-gguf"),
    "qwen3-forcedaligner-0.6b-full": ("alignment", "bf16", "Qwen/Qwen3-ForcedAligner-0.6B-hf"),
}


def test_resource_catalog_is_complete_pinned_and_precision_specific():
    specs = [spec for spec in catalog() if spec.get("format")]
    assert {spec["id"] for spec in specs} == set(EXPECTED)
    for spec in specs:
        assert (spec["task"], spec["precision"], spec["repository"]) == EXPECTED[spec["id"]]
        assert re.fullmatch(r"[0-9a-f]{40}", spec["revision"])
        assert spec["bytes"] == sum(file["size"] for file in spec["files"])
        names = {file["name"] for file in spec["files"]}
        assert len(names) == len(spec["files"])
        for file in spec["files"]:
            assert re.fullmatch(r"[0-9a-f]{64}", file["sha256"])
            assert file["size"] > 0
            assert "/" not in file["name"] and "\\" not in file["name"]
        if spec["precision"] == "q4_k_m":
            weights = [name for name in names if name.endswith(".gguf")]
            assert len(weights) == 1 and "Q4_K_M" in weights[0]
            assert not any(name.endswith(".safetensors") for name in names)
        else:
            assert "config.json" in names and "tokenizer.json" in names
            assert any(name.endswith(".safetensors") for name in names)
            assert not any(name.endswith(".gguf") for name in names)
        if spec["id"] == "index-translate-9b-full":
            assert len([name for name in names if name.endswith(".safetensors")]) == 4
            assert "model.safetensors.index.json" in names
            assert spec["bytes"] > 2**32
        if spec["architecture"] == "arkasr":
            assert {"configuration_arkasr.py", "modeling_arkasr.py", "modeling_audio.py",
                    "processing_arkasr.py"} <= names


def test_resource_refresh_selects_only_requested_quantization_and_complete_shards():
    info = {"id": "test/repo", "siblings": [
        {"rfilename": name} for name in [
            "README.md", "test.Q4_K_M.gguf", "test.Q8_0.gguf", "mmproj-f16.gguf", "run.py",
        ]
    ]}
    assert {file["rfilename"] for file in select_files(info, "qwen3_5", "test.Q4_K_M.gguf")} == {
        "README.md", "test.Q4_K_M.gguf",
    }
    with pytest.raises(ValueError, match="Incomplete"):
        select_files(info, "qwen3_5", "missing.Q4_K_M.gguf")
    info["siblings"] = [{"rfilename": name} for name in [
        "README.md", "config.json", "tokenizer.json", "tokenizer_config.json",
        "model-00001-of-00002.safetensors",
    ]]
    with pytest.raises(ValueError, match="weight index"):
        select_files(info, "qwen3_5", "")


def test_resource_manager_enables_use_only_for_installed_models(
    app, store, tmp_path, monkeypatch,
):
    store.set_preference("model_folder", str(tmp_path / "models"))
    controller = QueueController(store)
    downloaded, selected = [], []
    monkeypatch.setattr(controller, "start_model_download", downloaded.append)
    manager = ModelManager(store, controller, selected.append)
    assert downloaded == []
    assert [manager.tabs.tabText(i) for i in range(manager.tabs.count())] == [
        "Speech models", "Translation models", "Alignment models",
    ]
    for key in EXPECTED:
        controls = manager.controls[key]
        controls[2].click()
        assert not controls[5].isEnabled()
        manager.select_model(key)
    assert downloaded == list(EXPECTED)
    assert selected == []

    # Verified installed models expose both file access and the Use action.
    spec = caption_models.model_spec("qwen3-asr-1.7b-q4-k-m")
    monkeypatch.setattr("videodock.caption_ui.is_ready", lambda root, row: row["id"] == spec["id"])
    manager.refresh()
    controls = manager.controls[spec["id"]]
    assert not controls[2].isEnabled() and controls[5].isEnabled()
    assert controls[7].isEnabled() and "Installed revision:" in controls[0].toolTip()
    controls[5].click()
    assert selected == [spec["id"]]

    panel = SettingsPanel(DownloadSettings())
    assert {panel.local_model.itemData(i) for i in range(panel.local_model.count())} == {
        "base", "small", "turbo", "large-v3", "distil-v3.5", "ark-asr-0.6b-full", "ark-asr-3b-full",
        "qwen3-asr-1.7b-full", "qwen3-asr-1.7b-q4-k-m",
    }
    assert {spec["id"] for spec in task_models("translation", usable_only=True)} == {
        "m2m100-418m", "index-translate-2b-full", "index-translate-2b-q4-k-m",
        "index-translate-9b-full", "index-translate-9b-q4-k-m",
    }
    assert len(task_models("alignment", usable_only=True)) == 1
    panel.deleteLater()
    manager.deleteLater()
    controller.shutdown()


def test_multifile_resource_download_resumes_and_rejects_corrupt_shard(tmp_path, monkeypatch):
    import io

    contents = {"config.json": b'{"dtype":"bfloat16"}', "model-00001.safetensors": b"weight-one",
                "model-00002.safetensors": b"weight-two"}
    spec = {
        "id": "test-full", "revision": "a" * 40, "repository": "test/repo",
        "files": [{"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                  for name, content in contents.items()], "bytes": sum(map(len, contents.values())),
    }
    monkeypatch.setattr(caption_models, "model_spec", lambda _: spec)
    stage = tmp_path / ".staging" / spec["id"] / spec["revision"]
    stage.mkdir(parents=True)
    (stage / "config.json").write_bytes(contents["config.json"])
    (stage / "model-00001.safetensors.part").write_bytes(b"weight")
    requests = []
    corrupt = True

    class Response(io.BytesIO):
        def __init__(self, data, offset):
            super().__init__(data[offset:])
            self.status = 206 if offset else 200
            self.headers = {"Content-Range": f"bytes {offset}-{len(data) - 1}/{len(data)}"}

    def fetch(request, **kwargs):
        name = request.full_url.rsplit("/", 1)[1]
        offset = int(request.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
        requests.append((name, offset, request.full_url))
        content = contents[name]
        if corrupt and name == "model-00002.safetensors":
            content = b"x" * len(content)
        return Response(content, offset)

    monkeypatch.setattr(caption_models, "urlopen", fetch)
    with pytest.raises(ValueError, match="Integrity check failed"):
        download_model(tmp_path, spec["id"], threading.Event(), lambda _: None)
    assert not is_ready(tmp_path, spec)
    assert (stage / "model-00001.safetensors").read_bytes() == contents["model-00001.safetensors"]
    assert not (stage / "model-00002.safetensors.part").exists()
    corrupt = False
    download_model(tmp_path, spec["id"], threading.Event(), lambda _: None)
    assert is_ready(tmp_path, spec)
    assert [(name, offset) for name, offset, _ in requests] == [
        ("model-00001.safetensors", 6), ("model-00002.safetensors", 0), ("model-00002.safetensors", 0),
    ]
    assert all(spec["revision"] in url for _, _, url in requests)
