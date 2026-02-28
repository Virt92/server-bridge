#!/usr/bin/env python3
import datetime
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL = os.getenv("PM_MODEL", os.getenv("AI_MODEL", "gpt-4.1-mini"))
DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_PROVIDER = os.getenv("PM_PROVIDER", os.getenv("AI_PROVIDER", "openai")).strip().lower()
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
MAX_PM_SUBTASKS = int(os.getenv("PM_MAX_SUBTASKS", "6"))

VALID_ROLES = {"frontend", "backend", "devops", "qa"}
VALID_MODES = {"ai", "command", "manual"}

PM_MEMORY_PATH = Path(__file__).resolve().parent / "pm_memory.md"
PM_MEMORY_MAX_ENTRIES = int(os.getenv("PM_MEMORY_MAX_ENTRIES", "30"))
PM_MEMORY_MAX_CHARS = int(os.getenv("PM_MEMORY_MAX_CHARS", "1200"))

ROLE_PROFILE_ROOT = Path(__file__).resolve().parent.parent / "developers"
PM_TEAM_PROFILE_MAX_CHARS = int(os.getenv("PM_TEAM_PROFILE_MAX_CHARS", "2400"))
PROJECTS_ROOT = os.getenv("PROJECTS_ROOT", "/root/projects")


def _read_pm_memory() -> str:
    """Load recent PM memory entries for injection into system prompt."""
    if not PM_MEMORY_PATH.exists():
        return ""
    try:
        text = PM_MEMORY_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if not text:
        return ""
    if len(text) > PM_MEMORY_MAX_CHARS:
        text = text[-PM_MEMORY_MAX_CHARS:]
        newline_idx = text.find("\n")
        if newline_idx > 0:
            text = text[newline_idx + 1:]
    return text


def append_pm_memory(title: str, roles: list, outcome: str) -> None:
    """Append a compact one-line entry to PM memory file, keeping last N entries."""
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    roles_str = ",".join(str(r) for r in roles) if roles else "?"
    entry = f"{ts} | {title[:60]} | {roles_str} | {outcome}"
    try:
        existing: list[str] = []
        if PM_MEMORY_PATH.exists():
            existing = [
                ln for ln in PM_MEMORY_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
        if len(existing) >= PM_MEMORY_MAX_ENTRIES:
            existing = existing[-(PM_MEMORY_MAX_ENTRIES - 1):]
        existing.append(entry)
        PM_MEMORY_PATH.write_text("\n".join(existing) + "\n", encoding="utf-8")
    except Exception:
        pass


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

INCIDENT_DEVOPS_HINTS = (
    "http://",
    "https://",
    "ip",
    "host",
    "domain",
    "dns",
    "deploy",
    "down",
    "uptime",
    "port",
    "caddy",
    "nginx",
    "502",
    "503",
    "504",
    "timeout",
    "доступ",
    "сервер",
    "домен",
    "порт",
    "деплой",
)


def _load_team_capabilities() -> str:
    """Extract Tech Stack sections from developer profiles for PM context."""
    parts: list[str] = []
    for role in ("frontend", "backend", "devops", "qa"):
        profile_path = ROLE_PROFILE_ROOT / role / "profile.md"
        if not profile_path.exists():
            continue
        try:
            text = profile_path.read_text(encoding="utf-8")
        except Exception:
            continue
        section_lines: list[str] = []
        in_section = False
        for line in text.splitlines():
            if re.match(r"^#{1,3}\s+Tech Stack", line):
                in_section = True
                continue
            if in_section:
                if re.match(r"^#{1,3}\s+", line):
                    break
                section_lines.append(line)
        stack = "\n".join(section_lines).strip()
        if not stack and text:
            stack = text.strip()[:400]
        if stack:
            parts.append(f"[{role.upper()}]\n{stack}")
    result = "\n\n".join(parts)
    if len(result) > PM_TEAM_PROFILE_MAX_CHARS:
        result = result[:PM_TEAM_PROFILE_MAX_CHARS] + "\n...[truncated]"
    return result


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


def _resolve_openai_auth(base_url: str) -> tuple[str, str]:
    base_lower = base_url.lower()
    fal_key = os.getenv("FAL_KEY", "").strip()

    if "fal.run" in base_lower and fal_key:
        api_key = fal_key
    else:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("OpenAI-compatible API key is not set")

    auth_scheme = os.getenv("OPENAI_AUTH_SCHEME", "").strip()
    if not auth_scheme:
        auth_scheme = "Key" if "fal.run/openrouter/router/openai" in base_lower else "Bearer"

    return auth_scheme, api_key


def _call_openai(messages: list[dict[str, str]]) -> dict[str, Any]:
    auth_scheme, api_key = _resolve_openai_auth(DEFAULT_BASE_URL)

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
            "Authorization": f"{auth_scheme} {api_key}",
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


def _call_anthropic(messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY_PM")
        or os.getenv("OPENAI_API_KEY", "")
    ).strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    system_content = ""
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_content = msg.get("content", "")
        else:
            user_messages.append({"role": msg["role"], "content": msg["content"]})

    pm_payload: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "max_tokens": 4096,
        "temperature": 0.1,
        "messages": user_messages,
    }
    if system_content:
        pm_payload["system"] = system_content

    request = urllib.request.Request(
        f"{ANTHROPIC_BASE_URL}/messages",
        data=json.dumps(pm_payload).encode("utf-8"),
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
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic connection error: {exc}") from exc

    content = data["content"][0]["text"]
    return _parse_json_maybe(content)


def _call_ai(messages: list[dict[str, str]]) -> dict[str, Any]:
    if DEFAULT_PROVIDER == "anthropic":
        return _call_anthropic(messages)
    return _call_openai(messages)


def _normalize_mode(mode: str, command: str) -> str:
    normalized = (mode or "").strip().lower()
    if normalized not in VALID_MODES:
        normalized = "command" if command else "ai"
    if normalized == "command" and not command:
        normalized = "ai"
    # PM child tasks must be executable by agents; manual mode skips real execution.
    if normalized == "manual":
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

        # Sequential pipeline fields
        template_id = str(raw.get("id") or f"t{idx}").strip()
        depends_on = [str(d).strip() for d in (raw.get("depends_on") or []) if str(d).strip()]

        key = (role, title.lower())
        if key in seen:
            continue
        seen.add(key)

        normalized.append(
            {
                "id": template_id,
                "title": title,
                "description": description,
                "role": role,
                "mode": mode,
                "command": command,
                "acceptance_criteria": acceptance,
                "depends_on": depends_on,
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

    # For QA-only incident checks we still need an implementation role for follow-up fixes.
    if matched == ["qa"]:
        if any(hint in corpus for hint in INCIDENT_DEVOPS_HINTS):
            matched.append("devops")
        else:
            matched.append("backend")

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

    tasks = _ensure_fix_role_for_qa_only(tasks, task, roles)
    summary = "Heuristic PM plan generated without OpenAI"
    return summary, tasks


def _ensure_fix_role_for_qa_only(
    tasks: list[dict[str, Any]],
    task: dict[str, Any],
    roles: dict[str, Any],
) -> list[dict[str, Any]]:
    if not tasks:
        return tasks

    role_set = {str(item.get("role") or "").strip().lower() for item in tasks}
    if role_set != {"qa"}:
        return tasks

    corpus = " ".join(
        [
            str(task.get("title", "")),
            str(task.get("description", "")),
            str(task.get("tags", "")),
        ]
    ).lower()

    candidate_order = ["devops", "backend", "frontend"]
    preferred = "devops" if any(hint in corpus for hint in INCIDENT_DEVOPS_HINTS) else "backend"
    if preferred in candidate_order:
        candidate_order.remove(preferred)
    candidate_order.insert(0, preferred)

    target_role = next((role for role in candidate_order if role in roles and role in VALID_ROLES), "")
    if not target_role:
        return tasks

    tpl = ROLE_HEURISTIC_TEMPLATES.get(target_role, ROLE_HEURISTIC_TEMPLATES["backend"])
    title = f"{tpl['title']}: {task.get('title', 'Новая задача')}"
    description = (
        f"Контекст: {str(task.get('description') or task.get('title') or '').strip()}\n"
        f"Роль: {target_role}. {tpl['description']}"
    ).strip()
    tasks.append(
        {
            "title": title,
            "description": description,
            "role": target_role,
            "mode": "ai",
            "command": "",
            "acceptance_criteria": tpl["acceptance"],
        }
    )
    return tasks[:MAX_PM_SUBTASKS]


def _plan_with_ai(task: dict[str, Any], roles: dict[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    role_items = {
        role: {
            "label": cfg.get("label", role),
            "keywords": cfg.get("keywords", []),
        }
        for role, cfg in roles.items()
    }

    team_caps = _load_team_capabilities()
    team_block = f"\n## Возможности команды (Tech Stack по ролям)\n{team_caps}\n" if team_caps else ""

    memory_block = _read_pm_memory()
    memory_section = (
        f"\n## Память PM (прошлые задачи — дата|название|роли|итог)\n{memory_block}\n"
        if memory_block
        else ""
    )

    system_prompt = (
        "Ты технический Project Manager и директор разработки.\n"
        "Твоя задача: декомпозировать входную задачу, выбрать tech stack, назначить workdir и создать граф задач с зависимостями.\n"
        f"{team_block}"
        "\n## Обязательные шаги планирования\n"
        "1. **Workdir**: придумай slug проекта (kebab-case, до 30 символов) и сформируй путь: "
        f'workdir="{PROJECTS_ROOT}/{{slug}}". Например: "{PROJECTS_ROOT}/landing-agency-2024".\n'
        "2. **Tech Stack**: выбери стек для каждой роли исходя из возможностей команды выше и типа задачи. "
        "Укажи в `tech_stack` и **вставь явно в description каждой задачи** — агент должен знать на чём писать.\n"
        "3. **Граф зависимостей**: присвой каждой задаче уникальный `id` (t1, t2...) и заполни `depends_on`.\n"
        "   Типовой порядок:\n"
        "   - devops_setup: depends_on=[] (параллельно с frontend scaffold)\n"
        "   - frontend_scaffold: depends_on=[]\n"
        "   - backend: depends_on=[frontend_scaffold_id] (знает структуру фронта)\n"
        "   - frontend_integrate: depends_on=[backend_id] (подключает API)\n"
        "   - qa: depends_on=[frontend_integrate_id, devops_setup_id] (тестирует всё вместе)\n"
        "4. **Описание задач**: каждая задача должна содержать: стек, workdir, что конкретно реализовать, "
        "что ожидается от роли-зависимости.\n"
        "\n## Правила\n"
        "- Верни только JSON.\n"
        "- Максимум 6 подзадач.\n"
        "- Выбирай только доступные роли.\n"
        "- mode=ai (по умолчанию), mode=command только для конкретной безопасной shell-команды.\n"
        "- Не используй mode=manual.\n"
        f"{memory_section}"
    )

    payload = {
        "task": task,
        "available_roles": role_items,
        "projects_root": PROJECTS_ROOT,
        "expected_json_schema": {
            "workdir": f"{PROJECTS_ROOT}/project-slug",
            "tech_stack": {
                "frontend": "React + Vite + Tailwind",
                "backend": "Node.js Express",
                "devops": "PM2 + nginx",
                "qa": "curl + bash scripts",
            },
            "summary": "краткое описание плана",
            "tasks": [
                {
                    "id": "t1",
                    "title": "...",
                    "description": "Стек: React+Vite+Tailwind. Workdir: /root/projects/slug. Реализовать...",
                    "role": "frontend|backend|devops|qa",
                    "mode": "ai|command",
                    "command": "optional",
                    "depends_on": [],
                    "acceptance_criteria": "...",
                }
            ],
        },
    }

    decision = _call_ai(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
    )

    raw_tasks = decision.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raw_tasks = []

    tasks = _normalize_tasks(raw_tasks, task, roles)
    tasks = _ensure_fix_role_for_qa_only(tasks, task, roles)
    if not tasks:
        raise RuntimeError("PM planner returned no valid subtasks")

    summary = str(decision.get("summary", "")).strip() or "AI PM plan generated"
    workdir = str(decision.get("workdir", "")).strip()
    tech_stack = decision.get("tech_stack") if isinstance(decision.get("tech_stack"), dict) else {}
    extra = {"workdir": workdir, "tech_stack": tech_stack}
    return summary, tasks, extra


def plan_pm_task(task: dict[str, Any], roles: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
    errors: list[str] = []

    try:
        summary, tasks, extra = _plan_with_ai(task, roles)
        return (
            "planned",
            f"AI планирование: {summary}",
            tasks,
            {
                "source": "ai",
                "model": DEFAULT_MODEL,
                "errors": errors,
                "summary": summary,
                "workdir": extra.get("workdir", ""),
                "tech_stack": extra.get("tech_stack", {}),
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
                "workdir": "",
                "tech_stack": {},
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
            "workdir": "",
            "tech_stack": {},
        },
    )
