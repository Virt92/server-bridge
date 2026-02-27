# server-bridge

Minimal HTTP bridge service with health endpoints and a JSON echo route.

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

## Example Request

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/bridge/echo \
  -H "Content-Type: application/json" \
  -d '{"message":"hello"}'
```
