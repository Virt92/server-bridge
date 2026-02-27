# Core Orchestrator

Multi-agent оркестратор с 4 ролями, отдельными очередями и AI-режимом выполнения.

## Роли
- `frontend` — UI, страницы, стили, клиентская логика
- `backend` — API, БД, серверная логика
- `devops` — деплой, CI/CD, инфраструктура
- `qa` — тесты, регрессии, проверка качества

## Быстрый старт
1. Запусти PM2 (изолированно от глобального PM2): `./pm2-core start ecosystem.config.cjs`
2. Отправь задачу:
   `python3 orchestrator/submit_task.py --title "Сверстать лендинг" --description "Hero + CTA" --role frontend --mode ai --workdir /root/my-project`
3. Смотри статус:
   - `python3 orchestrator/status_board.py`
   - `tail -f developers/frontend/memory.md`
   - `./pm2-core logs`
   - `./pm2-core jlist`

## PM2 изоляция
- Используй `./pm2-core ...` вместо `pm2 ...`.
- Скрипт фиксирует `PM2_HOME=/root/core/.pm2`, чтобы процессы оркестратора не конфликтовали с уже запущенными сервисами в `/root/.pm2`.

## AI-переменные окружения
- `OPENAI_API_KEY` — обязателен для AI-режима
- `OPENAI_BASE_URL` — опционально (по умолчанию `https://api.openai.com/v1`)
- `AI_MODEL` — модель (по умолчанию `gpt-4.1-mini`)
- `AI_MAX_STEPS` — лимит итераций агента (по умолчанию `5`)
- `AI_COMMAND_TIMEOUT_SEC` — таймаут одной команды (по умолчанию `180`)

Пример:
`export OPENAI_API_KEY=... && export AI_MODEL=gpt-4.1-mini`

- Для постоянного запуска через `agent`: можно хранить секреты и AI-параметры в `/root/core/.agent.env` (файл загружается автоматически).

## Формат задачи
```json
{
  "title": "Сделать endpoint login",
  "description": "POST /api/login c JWT",
  "role": "backend",
  "mode": "ai",
  "workdir": "/root/my-project",
  "command": ""
}
```

`mode`:
- `ai` — агент сам планирует и выполняет команды
- `command` — выполнить конкретную команду из поля `command`
- `manual` — только зарегистрировать задачу без автозапуска

Если `role` не указан, оркестратор выбирает роль по ключевым словам.

## Команда `agent`
- Быстрый вход в режим оркестратора: просто запусти `agent`.
- Это поднимет/проверит `orch-main` и всех агентов и покажет текущий статус очередей.
- Полезные подкоманды:
  - `agent status`
  - `agent task --title "..." --description "..." --role frontend --mode ai --workdir /root/my-project`
  - `agent amend --title "fix ..." --role frontend --workdir /root/my-project --ref-task task-abc123 --target-path src/components --max-files-changed 3`
  - `agent ai list`
  - `agent ai set frontend --model codex-code --strategy apply_only`
  - `agent logs orch-main`

## Режим PM (директор)
- Отправь одну верхнеуровневую задачу в режиме `pm`, и оркестратор сам разложит её на подзадачи по ролям.
- Подзадачи ставятся в `incoming`, затем автоматически уходят в очереди ролей и выполняются агентами параллельно по ролям.
- Прогресс PM-задач хранится в `data/pm/*.json`.

Пример:
`agent pm --title "Релиз новой функции" --description "UI + API + deploy + smoke tests" --workdir /root/my-project`

В JSON-формате задачи также доступно:
`"mode": "pm"`

## Профили ролей
- Оркестратор загружает роль-специфику из `developers/<role>/profile.md` и добавляет ее в системный промпт AI-агента.
- Сейчас заполнены `developers/frontend/profile.md`, `developers/backend/profile.md`, `developers/qa/profile.md` и `developers/devops/profile.md`.

## Scoped доработки (delta workflow)
- Для правок существующего функционала отправляй задачу как delta, а не как "переписать заново".
- Используй поля: `--ref-task`, `--change-type`, `--target-path`, `--target-symbol`, `--max-files-changed`.
- Агент делает discovery первым шагом и получает guard по scope: если diff слишком широкий или вне target_paths, задача помечается failed.
- Guard diff работает в git-репозитории; вне git будет статус `skipped_no_git`.

Пример:
`agent amend --title "Fix checkout total" --description "Исправить rounding" --role backend --workdir /root/my-project --ref-task task-1234abcd --target-path src/checkout --target-symbol calculateTotal --max-files-changed 2`

## Роутинг AI по ролям
- По умолчанию все роли используют общий OpenAI runtime.
- Для отдельной роли можно задать отдельную модель/стратегию/endpoint:
  - `agent ai list`
  - `agent ai set frontend --model codex-code --strategy apply_only`
  - `agent ai set backend --model gpt-4.1-mini`
  - `agent ai reset frontend`
- Конфиг хранится в `config/role_ai.json`.
