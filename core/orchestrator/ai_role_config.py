#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
ROLE_AI_CONFIG_PATH = BASE_DIR / "config" / "role_ai.json"

KNOWN_ROLES = ("frontend", "backend", "devops", "qa", "pm")


def _first_non_empty(values: list[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def load_role_ai_config() -> dict[str, Any]:
    if not ROLE_AI_CONFIG_PATH.exists():
        return {}
    try:
        with ROLE_AI_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_role_ai_config(data: dict[str, Any]) -> None:
    ROLE_AI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ROLE_AI_CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def resolve_role_ai_settings(
    role: str,
    task: dict[str, Any] | None,
    *,
    default_model: str,
    default_base_url: str,
    default_provider: str = "openai",
    default_strategy: str = "default",
) -> dict[str, str]:
    role_name = (role or "").strip().lower()
    role_upper = role_name.upper()
    task = task or {}

    config = load_role_ai_config()
    role_cfg_raw = config.get(role_name, {})
    role_cfg = role_cfg_raw if isinstance(role_cfg_raw, dict) else {}

    provider = _first_non_empty(
        [
            task.get("ai_provider"),
            os.getenv(f"AI_PROVIDER_{role_upper}"),
            role_cfg.get("provider"),
            os.getenv("AI_PROVIDER"),
            default_provider,
        ]
    ).lower()

    model = _first_non_empty(
        [
            task.get("ai_model"),
            os.getenv(f"AI_MODEL_{role_upper}"),
            role_cfg.get("model"),
            default_model,
        ]
    )

    base_url = _first_non_empty(
        [
            task.get("ai_base_url"),
            os.getenv(f"OPENAI_BASE_URL_{role_upper}"),
            role_cfg.get("base_url"),
            os.getenv("OPENAI_BASE_URL"),
            default_base_url,
        ]
    )

    strategy = _first_non_empty(
        [
            task.get("ai_strategy"),
            os.getenv(f"AI_STRATEGY_{role_upper}"),
            role_cfg.get("strategy"),
            default_strategy,
        ]
    ).lower()
    if strategy not in {"default", "apply_only"}:
        strategy = default_strategy

    task_api_key = _first_non_empty([task.get("ai_api_key")])
    if task_api_key:
        api_key = task_api_key
        api_key_source = "task.ai_api_key"
        api_key_env = ""
    else:
        api_key_env = _first_non_empty(
            [
                task.get("ai_api_key_env"),
                role_cfg.get("api_key_env"),
            ]
        )

        if api_key_env and os.getenv(api_key_env):
            api_key = os.getenv(api_key_env, "")
            api_key_source = api_key_env
        elif os.getenv(f"OPENAI_API_KEY_{role_upper}"):
            env_name = f"OPENAI_API_KEY_{role_upper}"
            api_key = os.getenv(env_name, "")
            api_key_source = env_name
            api_key_env = env_name
        else:
            api_key = os.getenv("OPENAI_API_KEY", "")
            api_key_source = "OPENAI_API_KEY"
            if not api_key_env:
                api_key_env = "OPENAI_API_KEY"

    return {
        "role": role_name,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "strategy": strategy,
        "api_key": api_key,
        "api_key_env": api_key_env,
        "api_key_source": api_key_source,
    }
