# server-bridge

Monorepo with:
- `server-bridge` HTTP service (root)
- `core/` orchestrator and multi-agent runtime

## Endpoints

- `GET /healthz` - liveness probe
- `GET /readyz` - readiness probe (checks `core-api`)
- `POST /v1/bridge/echo` - echoes JSON payload with request metadata
- `POST /v1/bridge/tasks/submit` - submit task to orchestrator
- `GET /v1/bridge/tasks/:taskId/status` - task runtime state
- `GET /v1/bridge/tasks/:taskId/result` - final task payload when done/failed

## Quick Start

Requirements: Node.js 20+

```bash
npm install
npm test
npm start
```

Default server URL: `http://127.0.0.1:3000`

## Docker Compose (Bridge + Core)

```bash
docker compose up -d --build
docker compose ps
```

Services:
- `bridge` - public HTTP bridge (`:3000`)
- `core-api` - orchestrator API (`:8080`)
- `core-orchestrator` + `core-agent-*` - task router and workers

## Repository Layout

- `src/`, `test/` - bridge service code and tests
- `core/` - orchestrator codebase imported from runtime environment (without secrets/runtime state)

## Example Request

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/bridge/echo \
  -H "Content-Type: application/json" \
  -d '{"message":"hello"}'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/bridge/tasks/submit \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke task","description":"demo","role":"backend","mode":"manual","workdir":"/workspace"}'
```
