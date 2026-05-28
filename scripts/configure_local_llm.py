from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from getpass import getpass
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://ai.ahaddashboards.uk/"
DEFAULT_ENV_PATH = Path(".env")
PREFERRED_MODELS = ("qwen2.5:3b", "llama3.2:3b", "qwen2.5:7b")


def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/") + "/"
    api_key = getpass("Paste Open WebUI API key: ").strip()
    if not api_key:
        print("No API key entered; .env was not changed.", file=sys.stderr)
        return 2

    try:
        models = fetch_models(base_url, api_key)
    except urllib.error.HTTPError as exc:
        print(
            f"Open WebUI rejected the key or request: HTTP {exc.code}. .env was not changed.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"Could not reach Open WebUI: {exc}. .env was not changed.", file=sys.stderr)
        return 2

    selected_model = args.model or select_model(models)
    if not selected_model:
        print("Open WebUI returned no models; .env was not changed.", file=sys.stderr)
        return 2

    env_path = args.env_path
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updates = {
        "AGENCY_LOCAL_LLM_ENABLED": "true",
        "AGENCY_LOCAL_LLM_BASE_URL": base_url,
        "AGENCY_LOCAL_LLM_API_KEY": api_key,
        "AGENCY_LOCAL_LLM_MODEL": selected_model,
        "AGENCY_LOCAL_LLM_MODE": "shadow",
        "AGENCY_LOCAL_LLM_TIMEOUT_SECONDS": str(args.timeout_seconds),
    }
    env_path.write_text(
        "\n".join(update_env_lines(lines, updates)) + "\n",
        encoding="utf-8",
    )

    print(f"Configured Open WebUI local LLM at {base_url}")
    print(f"Selected model: {selected_model}")
    print("API key saved to .env and was not printed.")
    return 0


def fetch_models(base_url: str, api_key: str) -> list[str]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return extract_models(payload)


def extract_models(payload: Any) -> list[str]:
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    models: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model = row.get("id") or row.get("name") or row.get("model")
        if model:
            models.append(str(model))
    return models


def select_model(models: list[str]) -> str:
    for preferred in PREFERRED_MODELS:
        if preferred in models:
            return preferred
    return models[0] if models else ""


def update_env_lines(lines: list[str], updates: dict[str, str]) -> list[str]:
    output = list(lines)
    for key, value in updates.items():
        prefix = f"{key}="
        for index, line in enumerate(output):
            if line.startswith(prefix):
                output[index] = f"{key}={value}"
                break
        else:
            output.append(f"{key}={value}")
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure the agency Raspberry Pi/Open WebUI local LLM connection.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default="")
    parser.add_argument("--env-path", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
