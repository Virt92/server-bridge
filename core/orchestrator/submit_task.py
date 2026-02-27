#!/usr/bin/env python3
import argparse
import json
import uuid
from typing import Any

from common import DATA_DIR, ensure_runtime_layout


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in items:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _build_change_request(args: argparse.Namespace) -> dict[str, Any] | None:
    target_paths = _dedupe(args.target_path or [])
    target_symbols = _dedupe(args.target_symbol or [])

    change_type = str(args.change_type or "").strip().lower()
    if change_type and change_type not in {"fix", "extend", "refactor"}:
        raise SystemExit("--change-type must be one of: fix, extend, refactor")

    max_files_changed = int(args.max_files_changed or 0)
    max_lines_changed = int(args.max_lines_changed or 0)

    has_payload = any(
        [
            args.ref_task_id,
            change_type,
            target_paths,
            target_symbols,
            max_files_changed > 0,
            max_lines_changed > 0,
        ]
    )
    if not has_payload:
        return None

    payload: dict[str, Any] = {
        "ref_task_id": str(args.ref_task_id or "").strip(),
        "change_type": change_type,
        "target_paths": target_paths,
        "target_symbols": target_symbols,
        "max_files_changed": max_files_changed,
        "max_lines_changed": max_lines_changed,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit task to orchestrator incoming queue")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--role", choices=["frontend", "backend", "devops", "qa"], default="")
    parser.add_argument("--command", default="")
    parser.add_argument("--workdir", default="")
    parser.add_argument("--mode", choices=["auto", "ai", "command", "manual", "pm"], default="auto")

    parser.add_argument("--ref-task", dest="ref_task_id", default="")
    parser.add_argument("--change-type", default="")
    parser.add_argument("--target-path", action="append", default=[])
    parser.add_argument("--target-symbol", action="append", default=[])
    parser.add_argument("--max-files-changed", type=int, default=0)
    parser.add_argument("--max-lines-changed", type=int, default=0)

    parser.add_argument("--ai-model", default="")
    parser.add_argument("--ai-provider", default="")
    parser.add_argument("--ai-base-url", default="")
    parser.add_argument("--ai-api-key-env", default="")
    parser.add_argument("--ai-strategy", default="")

    args = parser.parse_args()
    ensure_runtime_layout()

    mode = args.mode
    if mode == "auto":
        mode = "command" if args.command else "ai"

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {
        "id": task_id,
        "title": args.title,
        "description": args.description,
        "role": args.role,
        "command": args.command,
        "workdir": args.workdir,
        "mode": mode,
        "status": "new",
    }

    change_request = _build_change_request(args)
    if change_request is not None:
        payload["change_request"] = change_request

    if args.ai_model:
        payload["ai_model"] = str(args.ai_model).strip()
    if args.ai_provider:
        payload["ai_provider"] = str(args.ai_provider).strip().lower()
    if args.ai_base_url:
        payload["ai_base_url"] = str(args.ai_base_url).strip()
    if args.ai_api_key_env:
        payload["ai_api_key_env"] = str(args.ai_api_key_env).strip()
    if args.ai_strategy:
        payload["ai_strategy"] = str(args.ai_strategy).strip().lower()

    target = DATA_DIR / "incoming" / f"{task_id}.json"
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"submitted {task_id}")
    print(target)


if __name__ == "__main__":
    main()
