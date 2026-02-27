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

test("POST /v1/bridge/tasks/submit proxies to core API", async (t) => {
  const fetchCalls = [];
  const server = createServer({
    coreApiBaseUrl: "http://core-api:8080",
    fetchImpl: async (input, init) => {
      fetchCalls.push({ input, init });
      return new Response(
        JSON.stringify({ task_id: "task-123", status: "incoming", bucket: "incoming" }),
        { status: 201, headers: { "content-type": "application/json" } },
      );
    },
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const res = await fetch(`${baseUrl(server)}/v1/bridge/tasks/submit`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ title: "Test task", role: "backend" }),
  });
  assert.equal(res.status, 201);
  const body = await res.json();
  assert.equal(body.task_id, "task-123");
  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].input, "http://core-api:8080/v1/tasks/submit");
  assert.equal(fetchCalls[0].init.method, "POST");
});

test("GET /v1/bridge/tasks/:id/status proxies to core API", async (t) => {
  const server = createServer({
    coreApiBaseUrl: "http://core-api:8080",
    fetchImpl: async (input) => {
      assert.equal(input, "http://core-api:8080/v1/tasks/task-777/status");
      return new Response(
        JSON.stringify({ task_id: "task-777", status: "queued" }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const res = await fetch(`${baseUrl(server)}/v1/bridge/tasks/task-777/status`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.status, "queued");
});

test("GET /readyz returns ready when core API is ready", async (t) => {
  const server = createServer({
    coreApiBaseUrl: "http://core-api:8080",
    fetchImpl: async (input) => {
      assert.equal(input, "http://core-api:8080/readyz");
      return new Response(
        JSON.stringify({ status: "ready" }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const res = await fetch(`${baseUrl(server)}/readyz`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.status, "ready");
});
