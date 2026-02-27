# server-bridge

Monorepo with:
- `server-bridge` HTTP service (root)
- `core/` orchestrator and multi-agent runtime

## Endpoints

- `GET /healthz` - liveness probe
- `GET /readyz` - readiness probe
- `POST /v1/bridge/echo` - echoes JSON payload with request metadata

## Quick Start

Requirements: Node.js 20+

```bash
npm install
npm test
npm start
```

Default server URL: `http://127.0.0.1:3000`

## Repository Layout

- `src/`, `test/` - bridge service code and tests
- `core/` - orchestrator codebase imported from runtime environment (without secrets/runtime state)

## Example Request

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/bridge/echo \
  -H "Content-Type: application/json" \
  -d '{"message":"hello"}'
```
