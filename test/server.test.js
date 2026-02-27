import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "../src/server.js";

function baseUrl(server) {
  const addr = server.address();
  return `http://127.0.0.1:${addr.port}`;
}

test("GET /healthz returns ok", async (t) => {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const res = await fetch(`${baseUrl(server)}/healthz`);
  assert.equal(res.status, 200);

  const body = await res.json();
  assert.equal(body.status, "ok");
  assert.equal(body.service, "server-bridge");
});

test("POST /v1/bridge/echo echoes payload", async (t) => {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const payload = { job: "ping", value: 42 };
  const res = await fetch(`${baseUrl(server)}/v1/bridge/echo`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  assert.equal(res.status, 200);

  const body = await res.json();
  assert.deepEqual(body.payload, payload);
  assert.ok(body.request_id);
  assert.ok(body.received_at);
});

test("invalid JSON returns 400", async (t) => {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const res = await fetch(`${baseUrl(server)}/v1/bridge/echo`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{",
  });

  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.error.code, "INVALID_JSON");
});
