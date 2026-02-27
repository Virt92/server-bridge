import http from "node:http";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";

const DEFAULT_HOST = process.env.HOST || "0.0.0.0";
const DEFAULT_PORT = Number(process.env.PORT || 3000);
const DEFAULT_MAX_BODY_BYTES = Number(process.env.MAX_BODY_BYTES || 1024 * 1024);
const DEFAULT_CORE_API_BASE_URL = process.env.CORE_API_BASE_URL || "http://127.0.0.1:8080";
const DEFAULT_CORE_API_TIMEOUT_MS = Number(process.env.CORE_API_TIMEOUT_MS || 10000);

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function sendError(res, statusCode, code, message, details = null) {
  return sendJson(res, statusCode, {
    error: { code, message, details },
  });
}

function readJsonBody(req, maxBodyBytes) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];

    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > maxBodyBytes) {
        const err = new Error(`Body exceeds ${maxBodyBytes} bytes`);
        err.code = "BODY_TOO_LARGE";
        reject(err);
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });

    req.on("end", () => {
      if (chunks.length === 0) {
        resolve({});
        return;
      }

      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(JSON.parse(raw));
      } catch (_err) {
        const err = new Error("Invalid JSON body");
        err.code = "INVALID_JSON";
        reject(err);
      }
    });

    req.on("error", (err) => reject(err));
  });
}

function logRequest(entry) {
  console.log(
    JSON.stringify({
      ts: new Date().toISOString(),
      service: "server-bridge",
      ...entry,
    }),
  );
}

async function callCoreApi(fetchImpl, baseUrl, timeoutMs, method, pathname, body = null) {
  const targetUrl = `${baseUrl.replace(/\/+$/, "")}${pathname}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetchImpl(targetUrl, {
      method,
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const rawText = await response.text();
    let payload = {};
    if (rawText.trim()) {
      try {
        payload = JSON.parse(rawText);
      } catch (_err) {
        payload = { raw: rawText };
      }
    }

    return {
      status: response.status,
      payload,
    };
  } catch (err) {
    if (err?.name === "AbortError") {
      const timeoutError = new Error(`Core API timeout after ${timeoutMs}ms`);
      timeoutError.code = "CORE_TIMEOUT";
      throw timeoutError;
    }
    const networkError = new Error("Core API unavailable");
    networkError.code = "CORE_UNAVAILABLE";
    networkError.details = String(err?.message || err);
    throw networkError;
  } finally {
    clearTimeout(timer);
  }
}

export function createServer(options = {}) {
  const maxBodyBytes = Number(options.maxBodyBytes || DEFAULT_MAX_BODY_BYTES);
  const coreApiBaseUrl = String(options.coreApiBaseUrl || DEFAULT_CORE_API_BASE_URL);
  const coreApiTimeoutMs = Number(options.coreApiTimeoutMs || DEFAULT_CORE_API_TIMEOUT_MS);
  const fetchImpl = options.fetchImpl || fetch;

  return http.createServer(async (req, res) => {
    const started = Date.now();
    const requestId = req.headers["x-request-id"] || randomUUID();
    res.setHeader("x-request-id", requestId);

    const host = req.headers.host || "localhost";
    const url = new URL(req.url || "/", `http://${host}`);
    const method = req.method || "GET";

    try {
      if (method === "GET" && url.pathname === "/healthz") {
        sendJson(res, 200, {
          status: "ok",
          service: "server-bridge",
          time: new Date().toISOString(),
        });
      } else if (method === "GET" && url.pathname === "/readyz") {
        const coreReady = await callCoreApi(
          fetchImpl,
          coreApiBaseUrl,
          coreApiTimeoutMs,
          "GET",
          "/readyz",
        );
        const isReady =
          coreReady.status >= 200 &&
          coreReady.status < 300 &&
          coreReady.payload &&
          coreReady.payload.status === "ready";

        sendJson(res, isReady ? 200 : 503, {
          status: isReady ? "ready" : "not_ready",
          service: "server-bridge",
          time: new Date().toISOString(),
          dependencies: {
            core_api: {
              base_url: coreApiBaseUrl,
              http_status: coreReady.status,
              response_status: coreReady.payload?.status || "unknown",
            },
          },
        });
      } else if (method === "POST" && url.pathname === "/v1/bridge/echo") {
        const payload = await readJsonBody(req, maxBodyBytes);
        sendJson(res, 200, {
          request_id: requestId,
          received_at: new Date().toISOString(),
          payload,
        });
      } else if (method === "POST" && url.pathname === "/v1/bridge/tasks/submit") {
        const payload = await readJsonBody(req, maxBodyBytes);
        const proxied = await callCoreApi(
          fetchImpl,
          coreApiBaseUrl,
          coreApiTimeoutMs,
          "POST",
          "/v1/tasks/submit",
          payload,
        );
        sendJson(res, proxied.status, proxied.payload);
      } else if (method === "GET" && /^\/v1\/bridge\/tasks\/[^/]+\/status$/.test(url.pathname)) {
        const taskId = decodeURIComponent(url.pathname.split("/")[4] || "");
        const proxied = await callCoreApi(
          fetchImpl,
          coreApiBaseUrl,
          coreApiTimeoutMs,
          "GET",
          `/v1/tasks/${encodeURIComponent(taskId)}/status`,
        );
        sendJson(res, proxied.status, proxied.payload);
      } else if (method === "GET" && /^\/v1\/bridge\/tasks\/[^/]+\/result$/.test(url.pathname)) {
        const taskId = decodeURIComponent(url.pathname.split("/")[4] || "");
        const proxied = await callCoreApi(
          fetchImpl,
          coreApiBaseUrl,
          coreApiTimeoutMs,
          "GET",
          `/v1/tasks/${encodeURIComponent(taskId)}/result`,
        );
        sendJson(res, proxied.status, proxied.payload);
      } else {
        sendError(res, 404, "NOT_FOUND", "Route not found", {
          method,
          path: url.pathname,
        });
      }
    } catch (err) {
      if (err.code === "INVALID_JSON") {
        sendError(res, 400, "INVALID_JSON", err.message);
      } else if (err.code === "BODY_TOO_LARGE") {
        sendError(res, 413, "PAYLOAD_TOO_LARGE", err.message, {
          max_body_bytes: maxBodyBytes,
        });
      } else if (err.code === "CORE_TIMEOUT") {
        sendError(res, 504, "CORE_TIMEOUT", err.message, {
          core_api_base_url: coreApiBaseUrl,
        });
      } else if (err.code === "CORE_UNAVAILABLE") {
        sendError(res, 503, "CORE_UNAVAILABLE", err.message, {
          core_api_base_url: coreApiBaseUrl,
          reason: err.details || null,
        });
      } else {
        sendError(res, 500, "INTERNAL_ERROR", "Unhandled server error");
      }
    } finally {
      logRequest({
        request_id: requestId,
        method,
        path: url.pathname,
        status_code: res.statusCode,
        duration_ms: Date.now() - started,
      });
    }
  });
}

export function startServer(options = {}) {
  const host = options.host || DEFAULT_HOST;
  const port = Number(options.port || DEFAULT_PORT);
  const server = createServer(options);

  server.listen(port, host, () => {
    console.log(
      JSON.stringify({
        ts: new Date().toISOString(),
        service: "server-bridge",
        event: "listening",
        host,
        port,
      }),
    );
  });

  const shutdown = (signal) => {
    console.log(
      JSON.stringify({
        ts: new Date().toISOString(),
        service: "server-bridge",
        event: "shutdown",
        signal,
      }),
    );
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(1), 5000).unref();
  };

  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  return server;
}

const isDirectRun =
  process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isDirectRun) {
  startServer();
}
