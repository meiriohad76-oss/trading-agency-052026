from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "configure_local_llm.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("configure_local_llm", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("configure_local_llm.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_env_lines_replaces_existing_values_without_printing_secret() -> None:
    script = _load_script()

    lines = [
        "OTHER=value",
        "AGENCY_LOCAL_LLM_ENABLED=false",
        "AGENCY_LOCAL_LLM_API_KEY=",
    ]
    updated = script.update_env_lines(
        lines,
        {
            "AGENCY_LOCAL_LLM_ENABLED": "true",
            "AGENCY_LOCAL_LLM_API_KEY": "secret-value",
            "AGENCY_LOCAL_LLM_MODEL": "qwen2.5:3b",
        },
    )

    assert "AGENCY_LOCAL_LLM_ENABLED=true" in updated
    assert "AGENCY_LOCAL_LLM_API_KEY=secret-value" in updated
    assert "AGENCY_LOCAL_LLM_MODEL=qwen2.5:3b" in updated
    assert updated[0] == "OTHER=value"


def test_extract_models_accepts_openwebui_data_payload() -> None:
    script = _load_script()

    models = script.extract_models(
        {
            "data": [
                {"id": "llama3.2:3b"},
                {"name": "qwen2.5:3b"},
                {"model": "qwen2.5:7b"},
                {"id": ""},
                "ignored",
            ]
        }
    )

    assert models == ["llama3.2:3b", "qwen2.5:3b", "qwen2.5:7b"]


def test_select_model_prefers_small_qwen_then_fallback() -> None:
    script = _load_script()

    assert script.select_model(["llama3.2:3b", "qwen2.5:3b"]) == "qwen2.5:3b"
    assert script.select_model(["llama3.2:3b"]) == "llama3.2:3b"
    assert script.select_model(["custom-model"]) == "custom-model"


def test_normalize_api_key_strips_bearer_prefix_and_quotes() -> None:
    script = _load_script()

    assert script.normalize_api_key("Bearer sk-local") == "sk-local"
    assert script.normalize_api_key('"Bearer sk-local"') == "sk-local"
    assert script.normalize_api_key("'sk-local'") == "sk-local"
