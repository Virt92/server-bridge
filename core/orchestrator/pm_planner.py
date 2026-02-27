#!/usr/bin/env python3
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEFAULT_MODEL = os.getenv("PM_MODEL", os.getenv("AI_MODEL", "gpt-4.1-mini"))
DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MAX_PM_SUBTASKS = int(os.getenv("PM_MAX_SUBTASKS", "6"))

VALID_ROLES = {"frontend", "backend", "devops", "qa"}
VALID_MODES = {"ai", "command", "manual"}

ROLE_HEURISTIC_TEMPLATES = {
    "frontend": {
        "title": "Frontend реализация",
        "description": "Сделать UI/UX часть задачи, клиентскую логику и базовую доступность.",
        "acceptance": "Интерфейс работает в браузере, ключевые пользовательские сценарии покрыты.",
    },
    "backend": {
        "title": "Backend реализация",
        "description": "Сделать API/серверную логику, обработку ошибок и базовую устойчивость.",
        "acceptance": "Функционал реализован, сценарии ошибок обработаны, базовые проверки проходят.",
    },
    "devops": {
        "title": "DevOps настройка",
        "description": "Подготовить запуск/деплой, конфигурацию окружения и наблюдаемость.",
        "acceptance": "Есть воспроизводимый запуск и понятная инструкция/конфигурация для окружения.",
    },
    "qa": {
        "title": "QA проверка",
        "description": "Проверить изменения, прогнать smoke/regression и зафиксировать результаты.",
        "acceptance": "Отчет о проверке готов, критические дефекты либо исправлены, либо явно задокументированы.",
    },
}


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


def _call_openai(messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    request = urllib.request.Request(
        f"{DEFAULT_BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
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
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {payload}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI connection error: {exc}") from exc

    content = data["choices"][0]["message"]["content"]
    return _parse_json_maybe(content)


def _normalize_mode(mode: str, command: str) -> str:
    normalized = (mode or "").strip().lower()
    if normalized not in VALID_MODES:
        normalized = "command" if command else "ai"
    if normalized == "command" and not command:
        normalized = "ai"
    return normalized


def _normalize_tasks(raw_tasks: list[Any], task: dict[str, Any], roles: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for idx, raw in enumerate(raw_tasks[:MAX_PM_SUBTASKS], start=1):
        if not isinstance(raw, dict):
            continue

        role = str(raw.get("role", "")).strip().lower()
        if role not in roles or role not in VALID_ROLES:
            continue

        title = str(raw.get("title", "")).strip()
        if not title:
            role_label = roles.get(role, {}).get("label", role)
            title = f"{role_label}: {task.get('title', f'Шаг {idx}') }"

        description = str(raw.get("description", "")).strip()
        if not description:
            description = str(task.get("description") or task.get("title") or "")

        command = str(raw.get("command", "")).strip()
        mode = _normalize_mode(str(raw.get("mode", "")), command)
        if mode != "command":
            command = ""

        acceptance = str(raw.get("acceptance_criteria") or raw.get("acceptance") or "").strip()

        key = (role, title.lower())
        if key in seen:
            continue
        seen.add(key)

        normalized.append(
            {
                "title": title,
                "description": description,
                "role": role,
                "mode": mode,
                "command": command,
                "acceptance_criteria": acceptance,
            }
        )

    return normalized


def _match_roles_by_keywords(task: dict[str, Any], roles: dict[str, Any]) -> list[str]:
    corpus = " ".join(
        [
            str(task.get("title", "")),
            str(task.get("description", "")),
            str(task.get("tags", "")),
        ]
    ).lower()

    matched: list[str] = []
    for role, cfg in roles.items():
        keywords = [str(k).lower() for k in cfg.get("keywords", [])]
        if any(kw and kw in corpus for kw in keywords):
            matched.append(role)

    if not matched:
        matched = ["backend", "qa"]

    if len(matched) == 1 and matched[0] != "qa":
        matched.append("qa")

    ordered = [r for r in ["frontend", "backend", "devops", "qa"] if r in matched]
    return ordered[:MAX_PM_SUBTASKS]


def _heuristic_plan(task: dict[str, Any], roles: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    selected_roles = _match_roles_by_keywords(task, roles)
    tasks: list[dict[str, Any]] = []

    for role in selected_roles:
        tpl = ROLE_HEURISTIC_TEMPLATES.get(role, ROLE_HEURISTIC_TEMPLATES["backend"])
        title = f"{tpl['title']}: {task.get('title', 'Новая задача')}"
        description = (
            f"Контекст: {str(task.get('description') or task.get('title') or '').strip()}\n"
            f"Роль: {role}. {tpl['description']}"
        ).strip()
        tasks.append(
            {
                "title": title,
                "description": description,
                "role": role,
                "mode": "ai",
                "command": "",
                "acceptance_criteria": tpl["acceptance"],
            }
        )

    summary = "Heuristic PM plan generated without OpenAI"
    return summary, tasks


def _plan_with_ai(task: dict[str, Any], roles: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    role_items = {
        role: {
            "label": cfg.get("label", role),
            "keywords": cfg.get("keywords", []),
        }
        for role, cfg in roles.items()
    }

    system_prompt = (
        "Ты технический project manager/директор разработки. "
        "Нужно декомпозировать одну входную задачу на подзадачи для ролей frontend/backend/devops/qa.\n"
        "Правила:\n"
        "- Верни только JSON.\n"
        "- Максимум 6 подзадач.\n"
        "- Выбирай только доступные роли.\n"
        "- По возможности делай параллельные подзадачи по разным ролям.\n"
        "- mode обычно ai. mode=command указывай только если есть конкретная безопасная команда.\n"
        "- Для каждой подзадачи дай четкий title/description/acceptance_criteria.\n"
    )

    payload = {
        "task": task,
        "available_roles": role_items,
        "expected_json_schema": {
            "summary": "short summary",
            "tasks": [
                {
                    "title": "...",
                    "description": "...",
                    "role": "frontend|backend|devops|qa",
                    "mode": "ai|command|manual",
                    "command": "optional shell command",
                    "acceptance_criteria": "...",
                }
            ],
        },
    }

    decision = _call_openai(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
    )

    raw_tasks = decision.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raw_tasks = []

    tasks = _normalize_tasks(raw_tasks, task, roles)
    if not tasks:
        raise RuntimeError("PM planner returned no valid subtasks")

    summary = str(decision.get("summary", "")).strip() or "AI PM plan generated"
    return summary, tasks


def plan_pm_task(task: dict[str, Any], roles: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
    errors: list[str] = []

    try:
        summary, tasks = _plan_with_ai(task, roles)
        return (
            "planned",
            f"AI планирование: {summary}",
            tasks,
            {
                "source": "ai",
                "model": DEFAULT_MODEL,
                "errors": errors,
                "summary": summary,
            },
        )
    except Exception as exc:
        errors.append(str(exc))

    summary, tasks = _heuristic_plan(task, roles)
    tasks = _normalize_tasks(tasks, task, roles)
    if not tasks:
        return (
            "blocked",
            "PM не смог сгенерировать подзадачи",
            [],
            {
                "source": "none",
                "model": DEFAULT_MODEL,
                "errors": errors,
                "summary": summary,
            },
        )

    return (
        "planned",
        f"Fallback-планирование: {summary}",
        tasks,
        {
            "source": "heuristic",
            "model": DEFAULT_MODEL,
            "errors": errors,
            "summary": summary,
        },
    )
