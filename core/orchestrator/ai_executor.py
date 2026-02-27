#!/usr/bin/env python3
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ai_role_config import resolve_role_ai_settings
from common import DATA_DIR

DEFAULT_MODEL = os.getenv("AI_MODEL", "gpt-4.1-mini")
DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
MAX_STEPS = int(os.getenv("AI_MAX_STEPS", "5"))
MAX_COMMANDS_PER_STEP = int(os.getenv("AI_MAX_COMMANDS_PER_STEP", "3"))
MAX_OUTPUT_CHARS = int(os.getenv("AI_CMD_OUTPUT_CHARS", "4000"))
DEFAULT_COMMAND_TIMEOUT = int(os.getenv("AI_COMMAND_TIMEOUT_SEC", "180"))
MAX_ROLE_PROFILE_CHARS = int(os.getenv("AI_ROLE_PROFILE_CHARS", "12000"))
ALLOW_PRIVILEGED_CMDS = str(os.getenv("AI_ALLOW_PRIVILEGED_CMDS", "0")).strip().lower() in {"1", "true", "yes", "on"}

BASE_DIR = Path(__file__).resolve().parent.parent
ROLE_PROFILE_ROOT = BASE_DIR / "developers"

ROLE_BRIEF = {
    "frontend": (
        "Ты senior frontend developer. Фокус: UI, верстка, компоненты, состояние, доступность."
    ),
    "backend": (
        "Ты senior backend developer. Фокус: API, БД, безопасность, производительность и стабильность."
    ),
    "devops": (
        "Ты senior devops engineer. Фокус: CI/CD, контейнеры, запуск, мониторинг, инфраструктура."
    ),
    "qa": (
        "Ты senior QA engineer. Фокус: тесты, регрессия, воспроизводимость дефектов, покрытие."
    ),
}

ALWAYS_DANGEROUS_PATTERNS = [
    r"(^|\s)rm(\s|$)",
    r"(^|\s)sudo(\s|$)",
    r"(^|\s)reboot(\s|$)",
    r"(^|\s)shutdown(\s|$)",
    r"(^|\s)poweroff(\s|$)",
    r"(^|\s)halt(\s|$)",
    r"(^|\s)mkfs(\s|$)",
    r"(^|\s)fdisk(\s|$)",
    r"(^|\s)dd(\s|$)",
    r"git\s+reset\s+--hard",
    r"git\s+checkout\s+--",
    r"curl.+\|\s*(sh|bash)",
    r"wget.+\|\s*(sh|bash)",
]

PRIVILEGED_PATTERNS = [
    r"(^|\s)apt(-get)?\s+install(\s|$)",
    r"(^|\s)(yum|dnf|apk)\s+install(\s|$)",
    r"(^|\s)systemctl(\s|$)",
]

DISCOVERY_PREFIXES = (
    "pwd",
    "ls",
    "find ",
    "rg ",
    "grep ",
    "git status",
    "git grep",
    "cat ",
    "sed -n",
    "head ",
    "tail ",
    "wc ",
    "tree",
)

DISCOVERY_FORBIDDEN_TOKENS = (
    ">",
    "| tee",
    " mv ",
    " cp ",
    " rm ",
    " touch ",
    " mkdir ",
    " sed -i",
    " perl -i",
    "git add",
    "git commit",
    "npm install",
    "pnpm add",
    "yarn add",
    "pip install",
)


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return f"{text[:MAX_OUTPUT_CHARS]}\n...[truncated]..."


def _is_safe_command(cmd: str) -> tuple[bool, str]:
    patterns = list(ALWAYS_DANGEROUS_PATTERNS)
    if not ALLOW_PRIVILEGED_CMDS:
        patterns.extend(PRIVILEGED_PATTERNS)

    for pattern in patterns:
        if re.search(pattern, cmd, flags=re.IGNORECASE):
            return False, pattern
    return True, ""


def _looks_like_discovery_command(cmd: str) -> bool:
    lowered = str(cmd or "").strip().lower()
    if not lowered:
        return False

    if "&&" in lowered or ";" in lowered:
        return False

    if any(token in lowered for token in DISCOVERY_FORBIDDEN_TOKENS):
        return False

    return lowered.startswith(DISCOVERY_PREFIXES)


def _parse_json_maybe(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _call_openai(messages: list[dict[str, str]], model: str, base_url: str, api_key: str) -> dict[str, Any]:
    if not api_key.strip():
        raise RuntimeError("OpenAI API key is not set")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {error_payload}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI connection error: {exc}") from exc

    content = data["choices"][0]["message"]["content"]
    return _parse_json_maybe(content)


def _call_anthropic(messages: list[dict[str, str]], model: str, base_url: str, api_key: str) -> dict[str, Any]:
    if not api_key.strip():
        raise RuntimeError("Anthropic API key is not set")

    system_content = ""
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_content = msg.get("content", "")
        else:
            user_messages.append({"role": msg["role"], "content": msg["content"]})

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.2,
        "messages": user_messages,
    }
    if system_content:
        payload["system"] = system_content

    body = json.dumps(payload).encode("utf-8")
    effective_base = base_url.rstrip("/") if base_url.rstrip("/") != DEFAULT_BASE_URL.rstrip("/") else ANTHROPIC_BASE_URL
    request = urllib.request.Request(
        f"{effective_base}/messages",
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic HTTP {exc.code}: {error_payload}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic connection error: {exc}") from exc

    content = data["content"][0]["text"]
    return _parse_json_maybe(content)


def _load_role_profile(role: str) -> str:
    role_name = (role or "").strip().lower()
    if not role_name:
        return ""

    profile_path = ROLE_PROFILE_ROOT / role_name / "profile.md"
    if not profile_path.exists():
        return ""

    try:
        text = profile_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

    if not text:
        return ""

    if len(text) > MAX_ROLE_PROFILE_CHARS:
        return f"{text[:MAX_ROLE_PROFILE_CHARS]}\n...[profile truncated]..."

    return text


def _extract_change_request(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("change_request")
    if not isinstance(raw, dict):
        return {}

    target_paths_raw = raw.get("target_paths")
    target_symbols_raw = raw.get("target_symbols")

    target_paths = [str(x).strip() for x in (target_paths_raw if isinstance(target_paths_raw, list) else []) if str(x).strip()]
    target_symbols = [str(x).strip() for x in (target_symbols_raw if isinstance(target_symbols_raw, list) else []) if str(x).strip()]

    result = {
        "ref_task_id": str(raw.get("ref_task_id") or "").strip(),
        "change_type": str(raw.get("change_type") or "").strip().lower(),
        "target_paths": target_paths,
        "target_symbols": target_symbols,
        "max_files_changed": int(raw.get("max_files_changed") or 0),
        "max_lines_changed": int(raw.get("max_lines_changed") or 0),
    }
    return result


def _has_change_scope(task: dict[str, Any]) -> bool:
    cr = _extract_change_request(task)
    return any(
        [
            cr.get("ref_task_id"),
            cr.get("target_paths"),
            cr.get("target_symbols"),
            cr.get("max_files_changed", 0) > 0,
            cr.get("change_type"),
        ]
    )


def _find_task_file_by_id(task_id: str) -> Path | None:
    if not task_id:
        return None

    candidates: list[Path] = []
    candidates.extend((DATA_DIR / "incoming").glob(f"{task_id}.json"))
    candidates.extend((DATA_DIR / "pm").glob(f"{task_id}.json"))

    for role in ["frontend", "backend", "devops", "qa"]:
        candidates.extend((DATA_DIR / "queues" / role).glob(f"{task_id}.json"))
        candidates.extend((DATA_DIR / "done" / role).glob(f"{task_id}.json"))
        candidates.extend((DATA_DIR / "failed" / role).glob(f"{task_id}.json"))

    for path in candidates:
        if path.exists():
            return path
    return None


def _load_reference_task_context(task: dict[str, Any]) -> dict[str, Any]:
    cr = _extract_change_request(task)
    ref_task_id = str(cr.get("ref_task_id") or task.get("ref_task_id") or "").strip()
    if not ref_task_id:
        return {}

    ref_path = _find_task_file_by_id(ref_task_id)
    if ref_path is None:
        return {"ref_task_id": ref_task_id, "status": "not_found"}

    try:
        with ref_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        return {"ref_task_id": ref_task_id, "status": "read_error", "error": str(exc)}

    summary = {
        "ref_task_id": ref_task_id,
        "status": str(payload.get("status") or ""),
        "role": str(payload.get("role") or ""),
        "title": str(payload.get("title") or ""),
        "description": str(payload.get("description") or ""),
        "mode": str(payload.get("mode") or ""),
        "source_file": str(ref_path),
    }

    for key in ("worker_log", "ai_log", "command_exit_code", "ai_note", "orchestrator_note"):
        if key in payload:
            summary[key] = payload.get(key)

    return summary


def _build_messages(
    role: str,
    task: dict[str, Any],
    workdir: Path,
    history: list[dict[str, Any]],
    strategy: str,
) -> list[dict[str, str]]:
    role_prompt = ROLE_BRIEF.get(role, "Ты опытный software engineer.")
    role_profile = _load_role_profile(role)
    change_request = _extract_change_request(task)
    reference_context = _load_reference_task_context(task)

    profile_block = ""
    if role_profile:
        profile_block = f"\nПрофиль роли:\n{role_profile}\n"

    change_scope_block = ""
    if _has_change_scope(task):
        change_scope_block = (
            "\nЭто задача на доработку существующего функционала.\n"
            "- Не переписывай модуль целиком; делай минимальный целевой diff.\n"
            "- Первый шаг обязан быть discovery-only: только read-only команды (rg/find/ls/cat/git status и т.п.).\n"
            "- После discovery меняй только релевантные файлы в scope задачи.\n"
        )

    strategy_block = ""
    if strategy == "apply_only":
        strategy_block = (
            "\nРежим apply_only:\n"
            "- Минимизируй рассуждения и итерации.\n"
            "- После discovery сразу переходи к точечным правкам и проверке.\n"
        )

    qa_verdict_block = ""
    if role == "qa":
        qa_verdict_block = (
            "\nДополнительные правила QA verdict:\n"
            "- Если найден дефект (включая недоступность URL/API, неверный статус-код, broken flow), верни decision=blocked.\n"
            "- decision=done используй только когда проверки пройдены и дефекты не обнаружены.\n"
            "- В note кратко укажи что именно проверено и итоговый verdict.\n"
        )

    system_prompt = (
        f"{role_prompt}\n"
        f"{profile_block}"
        f"{change_scope_block}"
        f"{strategy_block}"
        f"{qa_verdict_block}"
        "Ты работаешь как автономный агент.\n"
        "Правила:\n"
        "- Только неинтерактивные shell-команды.\n"
        "- Работай только внутри workdir.\n"
        "- Не используй опасные команды.\n"
        "- За шаг давай максимум 3 команды.\n"
        "- Если задачу можно завершить, верни decision=done.\n"
        "- Если не можешь продолжать, верни decision=blocked и причину.\n"
        "Ответ только JSON.\n"
    )

    user_prompt = {
        "task": task,
        "workdir": str(workdir),
        "history": history,
        "change_request": change_request,
        "reference_task": reference_context,
        "expected_json_schema": {
            "decision": "run | done | blocked",
            "note": "short text",
            "commands": ["shell command 1", "shell command 2"],
        },
    }

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
    ]


def _run_command(cmd: str, workdir: Path, timeout_sec: int) -> dict[str, Any]:
    started = time.time()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(workdir),
            text=True,
            capture_output=True,
            timeout=timeout_sec,
        )
        return {
            "cmd": cmd,
            "exit_code": result.returncode,
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
            "duration_sec": round(time.time() - started, 2),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "exit_code": 124,
            "stdout": _truncate((exc.stdout or "")),
            "stderr": _truncate((exc.stderr or "")),
            "duration_sec": round(time.time() - started, 2),
            "timed_out": True,
        }


def run_ai_task(role: str, task: dict[str, Any], logs_dir: Path) -> tuple[str, str, str]:
    task_id = str(task.get("id", f"task-{int(time.time())}"))
    workdir = Path(task.get("workdir") or "/root")
    workdir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    ai_cfg = resolve_role_ai_settings(
        role,
        task,
        default_model=DEFAULT_MODEL,
        default_base_url=DEFAULT_BASE_URL,
    )

    provider = str(ai_cfg.get("provider") or "openai").strip().lower()
    model = str(ai_cfg.get("model") or DEFAULT_MODEL)
    base_url = str(ai_cfg.get("base_url") or DEFAULT_BASE_URL)
    strategy = str(ai_cfg.get("strategy") or "default")
    api_key = str(ai_cfg.get("api_key") or "")

    transcript: dict[str, Any] = {
        "task_id": task_id,
        "role": role,
        "model": model,
        "workdir": str(workdir),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ai": {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "strategy": strategy,
            "api_key_source": ai_cfg.get("api_key_source", ""),
            "api_key_env": ai_cfg.get("api_key_env", ""),
        },
        "steps": [],
    }
    transcript_path = logs_dir / f"{task_id}.ai.json"

    if provider not in {"openai", "anthropic"}:
        transcript["status"] = "blocked"
        transcript["final_note"] = f"AI provider '{provider}' is not supported in this runtime"
        transcript["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with transcript_path.open("w", encoding="utf-8") as fh:
            json.dump(transcript, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return "blocked", f"Неподдерживаемый AI provider: {provider}", str(transcript_path)

    if not api_key.strip():
        transcript["status"] = "blocked"
        transcript["final_note"] = f"API key is not set (expected: {ai_cfg.get('api_key_env') or 'OPENAI_API_KEY'})"
        transcript["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with transcript_path.open("w", encoding="utf-8") as fh:
            json.dump(transcript, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return "blocked", "OPENAI API key не задан для роли", str(transcript_path)

    final_status = "blocked"
    final_note = "Достигнут лимит шагов"
    has_change_scope = _has_change_scope(task)

    for step in range(1, MAX_STEPS + 1):
        history = transcript["steps"]
        messages = _build_messages(role, task, workdir, history, strategy)
        step_payload: dict[str, Any] = {"step": step, "agent": {}, "runs": []}

        try:
            if provider == "anthropic":
                decision = _call_anthropic(messages, model=model, base_url=base_url, api_key=api_key)
            else:
                decision = _call_openai(messages, model=model, base_url=base_url, api_key=api_key)
            step_payload["agent"] = decision
        except Exception as exc:
            final_status = "error"
            final_note = f"Ошибка запроса к модели: {exc}"
            step_payload["agent"] = {"decision": "blocked", "note": final_note, "commands": []}
            transcript["steps"].append(step_payload)
            break

        action = str(decision.get("decision", "")).strip().lower()
        note = str(decision.get("note", "")).strip()
        raw_commands = decision.get("commands", [])
        if not isinstance(raw_commands, list):
            raw_commands = []
        commands = [str(c).strip() for c in raw_commands if str(c).strip()]

        if action == "done":
            final_status = "done"
            final_note = note or "Задача завершена агентом"
            transcript["steps"].append(step_payload)
            break

        if action == "blocked":
            final_status = "blocked"
            final_note = note or "Агент заблокирован"
            transcript["steps"].append(step_payload)
            break

        if action != "run":
            final_status = "error"
            final_note = f"Некорректный decision: {action}"
            transcript["steps"].append(step_payload)
            break

        if not commands:
            final_status = "blocked"
            final_note = "Модель не вернула команды"
            transcript["steps"].append(step_payload)
            break

        if has_change_scope and step == 1:
            if not all(_looks_like_discovery_command(cmd) for cmd in commands[:MAX_COMMANDS_PER_STEP]):
                final_status = "blocked"
                final_note = "Для scoped-доработки первый шаг должен быть discovery-only командами"
                step_payload["guard"] = {
                    "rule": "first_step_discovery_only",
                    "blocked": True,
                    "commands": commands[:MAX_COMMANDS_PER_STEP],
                }
                transcript["steps"].append(step_payload)
                break

        blocked_by_guard = False
        for cmd in commands[:MAX_COMMANDS_PER_STEP]:
            safe, reason = _is_safe_command(cmd)
            if not safe:
                step_payload["runs"].append(
                    {
                        "cmd": cmd,
                        "blocked": True,
                        "reason": reason,
                    }
                )
                final_status = "blocked"
                final_note = f"Команда заблокирована политикой безопасности: {cmd}"
                blocked_by_guard = True
                break

            result = _run_command(cmd, workdir, DEFAULT_COMMAND_TIMEOUT)
            step_payload["runs"].append(result)

        transcript["steps"].append(step_payload)
        if blocked_by_guard:
            break

    transcript["status"] = final_status
    transcript["final_note"] = final_note
    transcript["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with transcript_path.open("w", encoding="utf-8") as fh:
        json.dump(transcript, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    return final_status, final_note, str(transcript_path)
