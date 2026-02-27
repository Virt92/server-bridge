#!/usr/bin/env python3
import argparse
import json
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import DATA_DIR, append_memory, ensure_runtime_layout, read_task, write_task

SERVICE_MEMORY = Path(__file__).resolve().parent / "memory.md"
ALLOWED_MODES = {"ai", "command", "manual", "pm", "auto"}
ALLOWED_CHANGE_TYPES = {"fix", "extend", "refactor"}
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def normalize_change_request(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ApiError(422, "INVALID_CHANGE_REQUEST", "change_request must be an object")

    change_type = str(raw.get("change_type") or "").strip().lower()
    if change_type and change_type not in ALLOWED_CHANGE_TYPES:
        raise ApiError(
            422,
            "INVALID_CHANGE_TYPE",
            "change_type must be one of: fix, extend, refactor",
        )

    target_paths = dedupe(list(raw.get("target_paths") or []))
    target_symbols = dedupe(list(raw.get("target_symbols") or []))

    max_files_changed = int(raw.get("max_files_changed") or 0)
    max_lines_changed = int(raw.get("max_lines_changed") or 0)
    max_files_changed = max(0, max_files_changed)
    max_lines_changed = max(0, max_lines_changed)

    ref_task_id = str(raw.get("ref_task_id") or "").strip()

    has_payload = any(
        [
            ref_task_id,
            change_type,
            target_paths,
            target_symbols,
            max_files_changed > 0,
            max_lines_changed > 0,
        ]
    )
    if not has_payload:
        return None

    return {
        "ref_task_id": ref_task_id,
        "change_type": change_type,
        "target_paths": target_paths,
        "target_symbols": target_symbols,
        "max_files_changed": max_files_changed,
        "max_lines_changed": max_lines_changed,
    }


def sanitize_submit_payload(raw: dict[str, Any], roles: dict[str, Any]) -> dict[str, Any]:
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ApiError(422, "VALIDATION_ERROR", "title is required")

    role = str(raw.get("role") or "").strip().lower()
    if role and role not in roles:
        raise ApiError(422, "INVALID_ROLE", f"role must be one of: {', '.join(roles.keys())}")

    command = str(raw.get("command") or "").strip()
    mode = str(raw.get("mode") or "auto").strip().lower()
    if mode not in ALLOWED_MODES:
        raise ApiError(422, "INVALID_MODE", "mode must be one of: auto, ai, command, manual, pm")
    if mode == "auto":
        mode = "command" if command else "ai"

    change_request = normalize_change_request(raw.get("change_request"))

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    task_payload: dict[str, Any] = {
        "id": task_id,
        "title": title,
        "description": str(raw.get("description") or ""),
        "role": role,
        "command": command,
        "workdir": str(raw.get("workdir") or ""),
        "mode": mode,
        "status": "new",
    }

    if change_request is not None:
        task_payload["change_request"] = change_request

    for field in ("ai_model", "ai_provider", "ai_base_url", "ai_api_key_env", "ai_strategy"):
        value = str(raw.get(field) or "").strip()
        if value:
            task_payload[field] = value.lower() if field in {"ai_provider", "ai_strategy"} else value

    return task_payload


def find_task(task_id: str, role_names: list[str]) -> tuple[str, str, Path] | None:
    if not task_id or not TASK_ID_PATTERN.match(task_id) or "/" in task_id:
        return None

    direct_candidates = [
        ("incoming", "", DATA_DIR / "incoming" / f"{task_id}.json"),
        ("pm", "", DATA_DIR / "pm" / f"{task_id}.json"),
        ("failed_root", "", DATA_DIR / "failed" / f"{task_id}.json"),
    ]
    for bucket, role, path in direct_candidates:
        if path.exists():
            return bucket, role, path

    for role in role_names:
        for bucket in ("queue", "done", "failed"):
            folder = "queues" if bucket == "queue" else bucket
            path = DATA_DIR / folder / role / f"{task_id}.json"
            if path.exists():
                return bucket, role, path

    return None


def runtime_status(bucket: str, task: dict[str, Any]) -> str:
    if bucket == "incoming":
        return "incoming"
    if bucket == "queue":
        status = str(task.get("status") or "").strip().lower()
        return "in_progress" if status == "in_progress" else "queued"
    if bucket == "done":
        return "done"
    if bucket in {"failed", "failed_root"}:
        return "failed"
    if bucket == "pm":
        return str(task.get("status") or "planned").strip().lower() or "planned"
    return "unknown"


def task_public_view(task: dict[str, Any], bucket: str, role: str) -> dict[str, Any]:
    current_status = runtime_status(bucket, task)
    return {
        "id": str(task.get("id") or ""),
        "title": str(task.get("title") or ""),
        "role": str(task.get("role") or role or ""),
        "mode": str(task.get("mode") or ""),
        "status": current_status,
        "bucket": bucket,
        "created_at": str(task.get("created_at") or ""),
        "assigned_at": str(task.get("assigned_at") or ""),
        "started_at": str(task.get("started_at") or ""),
        "completed_at": str(task.get("completed_at") or ""),
    }


def build_handler(max_body_bytes: int):
    class Handler(BaseHTTPRequestHandler):
        server_version = "core-orchestrator-api/0.1"

        def _request_id(self) -> str:
            return str(self.headers.get("x-request-id") or uuid.uuid4())

        def _send_json(self, status_code: int, payload: dict[str, Any], request_id: str) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-Id", request_id)
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, request_id: str, status_code: int, code: str, message: str, details: Any = None) -> None:
            self._send_json(
                status_code,
                {"error": {"code": code, "message": message, "details": details}, "request_id": request_id},
                request_id,
            )

        def _read_json_body(self) -> dict[str, Any]:
            raw_len = self.headers.get("Content-Length", "0").strip()
            try:
                content_length = int(raw_len)
            except ValueError as exc:
                raise ApiError(400, "INVALID_CONTENT_LENGTH", "invalid Content-Length header") from exc

            if content_length < 0:
                raise ApiError(400, "INVALID_CONTENT_LENGTH", "invalid Content-Length header")
            if content_length > max_body_bytes:
                raise ApiError(413, "PAYLOAD_TOO_LARGE", f"body exceeds {max_body_bytes} bytes")

            raw = self.rfile.read(content_length) if content_length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ApiError(400, "INVALID_JSON", "invalid JSON body") from exc
            if not isinstance(payload, dict):
                raise ApiError(422, "VALIDATION_ERROR", "JSON body must be an object")
            return payload

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self._handle_request()

        def do_POST(self) -> None:
            self._handle_request()

        def _handle_request(self) -> None:
            request_id = self._request_id()
            parsed = urlparse(self.path)
            path = parsed.path
            started = time.time()
            status_code = 500

            try:
                roles = ensure_runtime_layout()
                role_names = list(roles.keys())

                if self.command == "GET" and path == "/healthz":
                    status_code = 200
                    self._send_json(
                        200,
                        {"status": "ok", "service": "core-orchestrator-api", "time": now_iso(), "request_id": request_id},
                        request_id,
                    )
                    return

                if self.command == "GET" and path == "/readyz":
                    checks = {
                        "roles_loaded": bool(role_names),
                        "incoming_dir": (DATA_DIR / "incoming").exists(),
                        "pm_dir": (DATA_DIR / "pm").exists(),
                    }
                    ready = all(checks.values())
                    status_code = 200 if ready else 503
                    self._send_json(
                        status_code,
                        {
                            "status": "ready" if ready else "not_ready",
                            "service": "core-orchestrator-api",
                            "time": now_iso(),
                            "checks": checks,
                            "request_id": request_id,
                        },
                        request_id,
                    )
                    return

                if self.command == "POST" and path == "/v1/tasks/submit":
                    body = self._read_json_body()
                    task = sanitize_submit_payload(body, roles)
                    task["created_at"] = now_iso()
                    target = DATA_DIR / "incoming" / f"{task['id']}.json"
                    write_task(target, task)
                    status_code = 201
                    self._send_json(
                        201,
                        {
                            "task_id": task["id"],
                            "status": "incoming",
                            "bucket": "incoming",
                            "path": str(target),
                            "request_id": request_id,
                        },
                        request_id,
                    )
                    return

                match = re.fullmatch(r"/v1/tasks/([^/]+)/status", path)
                if self.command == "GET" and match:
                    task_id = match.group(1)
                    located = find_task(task_id, role_names)
                    if not located:
                        raise ApiError(404, "TASK_NOT_FOUND", "task not found", {"task_id": task_id})
                    bucket, role, task_path = located
                    task = read_task(task_path)
                    view = task_public_view(task, bucket, role)
                    status_code = 200
                    self._send_json(
                        200,
                        {
                            "task_id": task_id,
                            "status": view["status"],
                            "bucket": bucket,
                            "role": view["role"],
                            "task": view,
                            "request_id": request_id,
                        },
                        request_id,
                    )
                    return

                match = re.fullmatch(r"/v1/tasks/([^/]+)/result", path)
                if self.command == "GET" and match:
                    task_id = match.group(1)
                    located = find_task(task_id, role_names)
                    if not located:
                        raise ApiError(404, "TASK_NOT_FOUND", "task not found", {"task_id": task_id})
                    bucket, role, task_path = located
                    task = read_task(task_path)
                    state = runtime_status(bucket, task)
                    if state not in {"done", "failed"}:
                        raise ApiError(409, "TASK_NOT_FINISHED", "task is not finished yet", {"status": state})
                    status_code = 200
                    self._send_json(
                        200,
                        {
                            "task_id": task_id,
                            "status": state,
                            "bucket": bucket,
                            "role": str(task.get("role") or role or ""),
                            "result": task,
                            "request_id": request_id,
                        },
                        request_id,
                    )
                    return

                raise ApiError(404, "NOT_FOUND", "route not found", {"method": self.command, "path": path})
            except ApiError as exc:
                status_code = exc.status_code
                self._send_error(request_id, exc.status_code, exc.code, exc.message, exc.details)
            except Exception as exc:
                status_code = 500
                self._send_error(request_id, 500, "INTERNAL_ERROR", "unhandled server error", str(exc))
            finally:
                append_memory(
                    SERVICE_MEMORY,
                    "done" if status_code < 500 else "error",
                    f"api {self.command} {path} status={status_code} duration_ms={int((time.time() - started) * 1000)}",
                )

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Core orchestrator HTTP API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--max-body-bytes", type=int, default=1024 * 1024)
    args = parser.parse_args()

    ensure_runtime_layout()
    handler = build_handler(max(1024, int(args.max_body_bytes)))
    server = ThreadingHTTPServer((args.host, int(args.port)), handler)
    append_memory(SERVICE_MEMORY, "doing", f"core api started on {args.host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        append_memory(SERVICE_MEMORY, "done", "core api stopped")


if __name__ == "__main__":
    main()
