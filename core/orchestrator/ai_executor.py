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
        "Ты senior frontend developer.\n"
        "Специализация: UI-компоненты, верстка, клиентская логика, роутинг, состояние, доступность.\n"
        "Discovery-приоритеты: найди package.json (стек/версии), структуру src/, существующие компоненты и стили.\n"
        "Не создавай то, что уже есть. Проверяй фреймворк и соглашения проекта перед написанием кода.\n"
        "\n"
        "КРИТИЧЕСКИ ВАЖНО — ЗОНЫ ОТВЕТСТВЕННОСТИ:\n"
        "✅ ТВОЯ ЗОНА: правка файлов исходного кода (.tsx, .jsx, .ts, .js, .css, .html, .json конфиги)\n"
        "❌ НЕ ТВОЯ ЗОНА: npm run build, npm run dev, npm start, pm2, next build — это задача @DevOps\n"
        "❌ НИКОГДА не запускай долгосрочные процессы (dev-сервер, watch-процессы)\n"
        "❌ НИКОГДА не запускай npm install без явного указания в задаче\n"
        "❌ НИКОГДА не используй nano, vim, vi — они интерактивные и не работают в неинтерактивном шелле\n"
        "Твоя задача завершена когда исходный код изменён и прошёл type-check. Сборку делает @DevOps.\n"
        "\n"
        "КАК ПИСАТЬ ФАЙЛЫ — ОБЯЗАТЕЛЬНО используй heredoc с ОДИНАРНЫМИ кавычками:\n"
        "  cat > /полный/путь/файл.tsx << 'ENDOFFILE'\n"
        "  [содержимое файла — JSX, TypeScript, CSS — без экранирования]\n"
        "  ENDOFFILE\n"
        "❌ НЕ используй echo '...' — bash ломается на {, }, $, ` в JSX/TS коде\n"
        "❌ НЕ используй printf — те же проблемы\n"
        "✅ ТОЛЬКО cat heredoc с << 'ENDOFFILE' (одинарные кавычки предотвращают подстановку переменных)\n"
        "\n"
        "РАБОЧИЙ ПРОЦЕСС (обязательно):\n"
        "1. PLAN — изучи структуру (ls, cat package.json, cat существующих файлов), реши что менять\n"
        "2. IMPLEMENT — пиши/правь файлы итерационно, файл за файлом через cat heredoc\n"
        "3. VERIFY каждого файла — сразу после записи прочитай файл (cat) и убедись что записалось верно\n"
        "4. TYPE CHECK — npx tsc --noEmit 2>&1 | head -30 (если TypeScript проект)\n"
        "5. SELF-REVIEW — перечитай изменения, убедись что нет синтаксических ошибок и дублей\n"
        "\n"
        "В note финального шага: список изменённых файлов, результат tsc (errors/ok), краткий самоотчёт.\n"
        "НЕ пиши в note 'сервер запущен' или 'сайт работает' — ты не проверяешь рантайм, это @DevOps."
    ),
    "backend": (
        "Ты senior backend developer.\n"
        "Специализация: REST/GraphQL API, БД, бизнес-логика, аутентификация, производительность, надёжность.\n"
        "Discovery-приоритеты: найди существующие роуты/эндпоинты, схему БД, middleware, конфиги окружения.\n"
        "Не дублируй существующую логику. Проверяй схему перед миграциями. Проверяй API через curl после правок.\n"
        "Root-cause thinking: проблема скорее в коде, чем в тестах.\n"
        "\n"
        "❌ НИКОГДА не используй nano, vim, vi — они интерактивные и не работают\n"
        "КАК ПИСАТЬ ФАЙЛЫ — используй heredoc с одинарными кавычками:\n"
        "  cat > /полный/путь/файл.ts << 'ENDOFFILE'\n"
        "  [код TypeScript/JavaScript]\n"
        "  ENDOFFILE\n"
        "Для установки пакета sqlite3: npm install sqlite3 --save (если нет в package.json)\n"
        "После записи файла ВСЕГДА проверяй: cat /путь/к/файлу и убедись что содержимое верное."
    ),
    "devops": (
        "Ты senior DevOps/SRE engineer. Сервер: 91.99.201.99.\n"
        "Специализация: CI/CD, Docker, PM2/systemd, nginx/Caddy, мониторинг, деплой, инфраструктура.\n"
        "PM2_HOME=/root/core/.pm2 — всегда используй этот PM2_HOME для всех pm2 команд!\n"
        "\n"
        "СТАНДАРТНЫЙ ДЕПЛОЙ NEXT.JS/NODE проекта (порядок важен):\n"
        "  Шаг 1 (discovery): ss -tlnp | grep PORT; PM2_HOME=/root/core/.pm2 pm2 list; ps aux | grep 'next\\|node' | grep PORT\n"
        "  Шаг 2: cd WORKDIR && npm run build  (собрать проект)\n"
        "  Шаг 3: Убить старые процессы на порту PORT (надёжный способ):\n"
        "    fuser -k PORT/tcp 2>/dev/null || true\n"
        "    PM2_HOME=/root/core/.pm2 pm2 delete PROJECT_NAME 2>/dev/null || true\n"
        "    sleep 1\n"
        "  Шаг 4: Запустить через PM2 с правильным портом:\n"
        "    PM2_HOME=/root/core/.pm2 PORT=PORT pm2 start npm --name 'PROJECT_NAME' --cwd WORKDIR -- start\n"
        "  Шаг 5: ufw allow PORT/tcp\n"
        "  Шаг 6: Проверить: curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:PORT\n"
        "          curl -s -o /dev/null -w '%{http_code}' http://91.99.201.99:PORT\n"
        "\n"
        "КРИТИЧЕСКИ ВАЖНО:\n"
        "  - Всегда убивай старые процессы на порту ПЕРЕД запуском нового\n"
        "  - Используй PORT=XXXX как переменную окружения при pm2 start\n"
        "  - Без ufw allow PORT/tcp — порт недоступен снаружи\n"
        "  - Проверяй ОБА адреса: localhost И внешний IP 91.99.201.99\n"
        "  - Если npm run build упал — читай ошибку, исправляй, не игнорируй\n"
        "\n"
        "В note финального шага: порт, HTTP статус (localhost и внешний IP), PM2 статус процесса."
    ),
    "qa": (
        "Ты senior QA engineer. Сервер: 91.99.201.99.\n"
        "Специализация: тест-планирование, smoke/regression, воспроизведение дефектов.\n"
        "Discovery-приоритеты: найди порт сервиса, workdir, что должно работать по заданию.\n"
        "\n"
        "ОБЯЗАТЕЛЬНЫЙ ЧЕКЛИСТ для каждого веб-сервиса:\n"
        "  1. curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:PORT → должен быть 200\n"
        "  2. curl -s -o /dev/null -w '%{http_code}' http://91.99.201.99:PORT → внешний IP!\n"
        "  3. curl -s http://127.0.0.1:PORT | head -50 → проверь что есть реальный контент\n"
        "  4. ufw status | grep PORT → убедись что порт открыт в файрволе\n"
        "  5. ps aux | grep -E 'node|next|pm2' → сервис запущен?\n"
        "\n"
        "Если внешний IP недоступен → выполни: ufw allow PORT/tcp и проверь снова.\n"
        "Если сервис не запущен → сообщи точно что не так.\n"
        "\n"
        "В note ВСЕГДА структурированный отчёт:\n"
        "  ✅/❌ localhost:PORT — HTTP CODE\n"
        "  ✅/❌ 91.99.201.99:PORT — HTTP CODE\n"
        "  ✅/❌ UFW порт открыт\n"
        "  ✅/❌ Контент присутствует\n"
        "  VERDICT: PASS / FAIL + что нужно исправить"
    ),
    "designer": (
        "Ты senior UI/UX Designer. Сервер: 91.99.201.99.\n"
        "Специализация: дизайн-системы, цветовые палитры, типографика, компонентный UI, CSS.\n"
        "Discovery-приоритеты: прочитай существующие CSS файлы (globals.css, styles/), package.json (стек), текущие компоненты.\n"
        "\n"
        "ТВОЯ ЗОНА ОТВЕТСТВЕННОСТИ:\n"
        "✅ Редактирование CSS/SCSS файлов (globals.css, variables, theme files)\n"
        "✅ Создание/редактирование компонентных стилей\n"
        "✅ Обновление дизайн-токенов (CSS переменные: --color-*, --font-*, --spacing-*)\n"
        "✅ Tailwind config (tailwind.config.js) — цвета, шрифты, spacing\n"
        "❌ НЕ трогаешь логику компонентов (JSX/TSX), только стили\n"
        "❌ НЕ запускаешь сборку (npm build) — это зона DevOps\n"
        "\n"
        "ДИЗАЙН-ПРИНЦИПЫ (всегда соблюдай):\n"
        "- Никакого оранжевого/кислотного как primary/hero background\n"
        "- Крипто/финтех: тёмный фон (#080c14 или аналог), синий/фиолетовый акцент\n"
        "- Профессиональные референсы: Coinbase, Binance, Stripe, Linear\n"
        "- Конкретные hex-значения в CSS переменных — никакого 'светло-синего'\n"
        "\n"
        "РАБОЧИЙ ПРОЦЕСС:\n"
        "1. Прочитай существующие CSS/globals.css — пойми текущую систему\n"
        "2. Определи что менять (конкретные правила, переменные)\n"
        "3. Внеси изменения в CSS файлы\n"
        "4. Проверь что изменения применились (cat файл)\n"
        "\n"
        "В note финального шага: изменённые файлы, список изменённых CSS правил/переменных."
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
    # Interactive editors — not available in non-interactive shells
    r"(^|\s)(nano|vim|vi|emacs|pico|gedit|code)(\s|$)",
]

PRIVILEGED_PATTERNS = [
    r"(^|\s)apt(-get)?\s+install(\s|$)",
    r"(^|\s)(yum|dnf|apk)\s+install(\s|$)",
    r"(^|\s)systemctl(\s|$)",
]

DISCOVERY_PREFIXES = (
    "pwd",
    "cd ",
    "ls",
    "find ",
    "rg ",
    "grep ",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git grep",
    "git show",
    "cat ",
    "sed -n",
    "head ",
    "tail ",
    "wc ",
    "tree",
    "echo ",
    "env",
    "printenv",
    "which ",
    "type ",
    "file ",
    "stat ",
    "diff ",
    "curl -s",
    "curl --silent",
    "curl --head",
    "wget -q",
    "wget --spider",
    "ps ",
    "pgrep",
    "netstat",
    "ss ",
    "lsof",
    "fuser ",
    "df ",
    "du ",
    "jq ",
    "python3 -c",
    "python3 --version",
    "python --version",
    "node --version",
    "node -v",
    "node -e",
    "npm --version",
    "npm -v",
    "npm list",
    "npm run",
    "npx --version",
    "npx -v",
    "pip list",
    "pip show",
    "nc -z",
    "nc -w",
    "pm2 list",
    "pm2 show",
    "pm2 describe",
    "pm2 status",
    "pm2 logs",
    "nginx -t",
    "systemctl status",
    "service ",
    "journalctl",
    "ufw status",
    "ufw app list",
    "iptables -L",
    "curl -o /dev/null",
    "curl -I ",
    "curl -i ",
    "cat /etc/",
    "cat /root/",
)

DISCOVERY_FORBIDDEN_TOKENS = (
    " >",   # file write redirect (2>/dev/null and 2>&1 are allowed)
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
    "npm run dev",    # starts long-running dev server — forbidden in step 1
    "npm run start",  # starts production server — forbidden in step 1
    "npm start",      # starts production server — forbidden in step 1
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

    # Strip safe fallback suffixes: || echo '...' || true
    # These are read-only fallbacks and should not disqualify the primary command
    stripped_fallbacks = re.sub(r'\s*\|\|\s*(echo\b.*|true|:|false)$', '', lowered).strip()
    # If stripping fallbacks removed the operator, check the remainder
    if stripped_fallbacks != lowered and "||" not in stripped_fallbacks:
        lowered = stripped_fallbacks

    # Allow \; (find -exec terminator) but block real command chaining (; && ||)
    chaining_check = lowered.replace("\\;", "")
    if "&&" in chaining_check or ";" in chaining_check or "||" in chaining_check:
        return False

    if any(token in lowered for token in DISCOVERY_FORBIDDEN_TOKENS):
        return False

    # Strip leading KEY=VALUE environment variable prefixes (e.g. PM2_HOME=/root/core/.pm2 pm2 list)
    # so that env-prefixed versions of discovery commands are still recognized
    stripped = re.sub(r'^([a-z_][a-z0-9_]*=\S*\s+)+', '', lowered)

    return lowered.startswith(DISCOVERY_PREFIXES) or stripped.startswith(DISCOVERY_PREFIXES)


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
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            last_exc = None
            break
        except urllib.error.HTTPError as exc:
            error_payload = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < 3:
                wait = 15 * (attempt + 1)
                time.sleep(wait)
                last_exc = exc
                continue
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {error_payload}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI connection error: {exc}") from exc
    if last_exc is not None:
        raise RuntimeError(f"OpenAI rate limit after retries: {last_exc}") from last_exc

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

    profile_block = f"\n## Профиль роли\n{role_profile}\n" if role_profile else ""

    change_scope_block = ""
    if _has_change_scope(task):
        change_scope_block = (
            "\n## Scope доработки\n"
            "Это задача на изменение существующего функционала.\n"
            "- Делай минимальный целевой diff — не переписывай модуль целиком.\n"
            "- Меняй только файлы, указанные в change_request.target_paths.\n"
        )

    strategy_block = ""
    if strategy == "apply_only":
        strategy_block = (
            "\n## Режим apply_only\n"
            "- После discovery сразу переходи к точечным правкам и проверке.\n"
            "- Минимум промежуточных шагов.\n"
        )

    qa_verdict_block = ""
    if role == "qa":
        qa_verdict_block = (
            "\n## QA Verdict rules\n"
            "- decision=blocked: найден дефект (недоступность URL/API, неверный статус-код, broken flow, assertion fail).\n"
            "- decision=done: все проверки пройдены, дефекты не обнаружены.\n"
            "- note обязан содержать: что проверено, результат каждой проверки, итоговый verdict.\n"
            "- Указывай конкретные URL, статус-коды, файлы и строки где найден дефект.\n"
        )

    system_prompt = (
        f"{role_prompt}\n"
        f"{profile_block}"
        "## Рабочий процесс\n"
        "\n"
        "### Шаг 1 — DISCOVERY (обязательно для каждой задачи)\n"
        "Изучи рабочую директорию ДО любых изменений.\n"
        "Разрешены ТОЛЬКО read-only команды: ls, find, rg, grep, cat, head, tail, git status, git log, git diff, curl -s, ps, env, stat, wc, tree, diff, jq, which, pm2 list, pm2 show, pm2 describe, nginx -t, systemctl status.\n"
        "ЗАПРЕЩЕНО в шаге 1: && || ; (command chaining). Каждая команда — отдельно. НЕ пиши 'ls /path || echo ...' — пиши просто 'ls /path'.\n"
        "Цель: понять структуру проекта, найти нужные файлы, убедиться что не дублируешь существующее.\n"
        "\n"
        "### Шаг 2+ — EXECUTION\n"
        "На основе данных discovery делай точечные изменения.\n"
        "После каждого изменения проверяй результат: git diff, cat изменённого файла, curl к API.\n"
        "\n"
        "## Правила\n"
        "\n"
        "**Безопасность:**\n"
        "- Только неинтерактивные shell-команды.\n"
        "- Запрещено: rm, sudo, reboot, shutdown, dd, mkfs, git reset --hard, git checkout --, curl|bash.\n"
        "- Read-only команды (cat, curl -s, grep) разрешены вне workdir.\n"
        "- Write-операции — только внутри workdir.\n"
        "\n"
        "**Эффективность:**\n"
        "- Максимум 3 команды за шаг; группируй независимые команды в один шаг.\n"
        "- Не повторяй одну и ту же команду дважды.\n"
        "- Не переписывай модули целиком — минимальный целевой diff.\n"
        "\n"
        "**Качество note:**\n"
        "- Указывай конкретные файлы и строки: 'исправлено src/api.py:87', 'ошибка в config/nginx.conf:14'.\n"
        "- decision=done — только когда задача реально завершена и результат проверен.\n"
        "- decision=blocked — чёткая причина: что именно мешает, что нужно для продолжения.\n"
        "- В финальном note кратко опиши что создал/изменил — это увидят следующие агенты в pipeline.\n"
        "\n"
        "**Командная работа (sequential pipeline):**\n"
        "- Если в задаче есть `completed_predecessors` — изучи их результаты в discovery-фазе.\n"
        "- Используй созданные ими файлы, не дублируй их работу.\n"
        "- Работай в том же workdir что и предшественники.\n"
        f"{change_scope_block}"
        f"{strategy_block}"
        f"{qa_verdict_block}"
        "\nОтвет строго JSON.\n"
    )

    user_prompt: dict[str, Any] = {
        "task": task,
        "workdir": str(workdir),
        "history": history,
        "change_request": change_request,
        "reference_task": reference_context,
        "expected_json_schema": {
            "decision": "run | done | blocked",
            "note": "краткий итог шага; при ссылке на код указывай file.py:line",
            "commands": ["shell command 1", "shell command 2"],
        },
    }

    siblings = task.get("siblings_context")
    if isinstance(siblings, list) and siblings:
        user_prompt["completed_predecessors"] = siblings

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

        if step == 1:
            non_discovery = [cmd for cmd in commands[:MAX_COMMANDS_PER_STEP] if not _looks_like_discovery_command(cmd)]
            if non_discovery:
                final_status = "blocked"
                final_note = f"Шаг 1 должен содержать только read-only команды (discovery). Нарушение: {non_discovery[0]!r}"
                step_payload["guard"] = {
                    "rule": "first_step_discovery_only",
                    "blocked": True,
                    "offending_commands": non_discovery,
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
