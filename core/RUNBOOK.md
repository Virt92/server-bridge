# Runbook

## HTTP service
- `python3 orchestrator/api_server.py --host 0.0.0.0 --port 8080`
- Проверка:
  - `curl -sS http://127.0.0.1:8080/healthz`
  - `curl -sS http://127.0.0.1:8080/readyz`

## Старт
- `cd /root/core`
- `export OPENAI_API_KEY=...`
- `./pm2-core start ecosystem.config.cjs`
- `./pm2-core save`

## Мониторинг
- `./pm2-core ls` (интерактивная таблица)
- `./pm2-core jlist` (JSON-статус для скриптов/неинтерактивного режима)
- `./pm2-core logs orch-main`
- `./pm2-core logs agent-frontend`
- `python3 orchestrator/status_board.py`

## Отправить задачу
- `python3 orchestrator/submit_task.py --title "Сделать страницу" --description "Новый лендинг" --role frontend --mode ai --workdir /root/my-project`
- `python3 orchestrator/submit_task.py --title "API login" --description "POST /api/login" --role backend --mode ai --workdir /root/my-project`
- `python3 orchestrator/submit_task.py --title "Прогнать API тесты" --role backend --mode command --command "npm run test:api" --workdir /root/my-project`

## Данные и память
- Оркестратор: `orchestrator/memory.md`
- Агенты: `developers/<role>/memory.md`
- Выполненные задачи: `data/done/<role>/`
- Ошибки/блокировки: `data/failed/<role>/`
- Логи команд агента: `developers/<role>/logs/`
- AI-транскрипты: `developers/<role>/logs/<task-id>.ai.json`

## Остановка
- `./pm2-core stop ecosystem.config.cjs`
- `./pm2-core delete ecosystem.config.cjs`

## Команда `agent`
- `agent` — убедиться, что стек оркестратора запущен, и показать статус
- `agent status` — статус очередей + PM2
- `agent task ...` — отправить задачу в `incoming`
- `agent logs [proc]` — логи PM2
- `agent down` — остановка/удаление PM2 процессов оркестратора

## Docker Compose (из монорепо)
- `cd /root/codex-workspaces/default/server-bridge`
- `docker compose up -d --build`
- `docker compose ps`
- Логи:
  - `docker compose logs -f core-api`
  - `docker compose logs -f core-orchestrator`
  - `docker compose logs -f core-agent-backend`

## PM-декомпозиция (директорский режим)
- Отправка одной верхнеуровневой задачи:
  - `agent pm --title "..." --description "..." --workdir /root/my-project`
- Оркестратор планирует и раздаёт подзадачи агентам по ролям.
- Если в плане есть `qa` + роли реализации, оркестратор работает фазами:
  - `qa_gate` -> `implementation` -> `qa_recheck`.
  - При неуспешном re-check возможен повторный круг фиксов (до `PM_QA_MAX_ROUNDS`).
- Статус смотреть:
  - `agent status`
  - `python3 orchestrator/status_board.py`
  - `ls -la data/pm`

## Секреты и профили
- Секреты/AI env для команды `agent` хранятся в `/root/core/.agent.env` (chmod 600).
- Роль-профили: `developers/<role>/profile.md` (frontend, backend, qa и devops уже настроены).

## Delta-доработки (не переписывать все)
- Отправляй follow-up через `agent amend ...` или `submit_task.py` с полями scope:
  - `--ref-task task-...`
  - `--target-path <path>` (можно несколько)
  - `--target-symbol <symbol>` (можно несколько)
  - `--max-files-changed <N>`
- Воркер проверяет diff после выполнения и блокирует задачу при выходе за scope.
- Проверка diff требует git workdir; иначе `change_guard.status=skipped_no_git`.

## Роутинг моделей по ролям
- Список overrides: `agent ai list`
- Настройка роли: `agent ai set <role> --model <model> [--strategy apply_only] [--base-url ...] [--api-key-env ...]`
- Сброс роли: `agent ai reset <role>`
- Роли: `frontend`, `backend`, `devops`, `qa`, `pm`
