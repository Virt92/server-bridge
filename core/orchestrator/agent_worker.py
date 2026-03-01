#!/usr/bin/env python3
import argparse
import fnmatch
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_executor import run_ai_task, save_task_lesson
from common import DATA_DIR, DEVELOPERS_DIR, append_memory, ensure_runtime_layout, read_task, write_task

POLL_SECONDS = 3

QA_NEGATIVE_PATTERNS = (
    r"\berror\b",
    r"\bcurl error\b",
    r"\bunreachable\b",
    r"\bnot found\b",
    r"\btimeout\b",
    r"\brefused\b",
    r"\bhttp\s*(?:status\s*)?[45]\d\d\b",
    r"\b5\d\d\b",
    r"не работает",
    r"не отвечает",
    r"недоступен",
    r"таймаут",
)

QA_POSITIVE_PATTERNS = (
    r"all checks passed",
    r"no issues",
    r"no bugs",
    r"checks passed",
    r"успешно",
    r"корректно",
    r"ошибок не",
    r"багов не",
)


def run_command(command: str, workdir: str | None, log_path: Path) -> tuple[int, str]:
    cwd = Path(workdir) if workdir else Path("/root")
    cwd.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        command,
        shell=True,
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(f"$ {command}\n")
        fh.write(f"cwd: {cwd}\n\n")
        fh.write(result.stdout)
        if result.stderr:
            fh.write("\n[stderr]\n")
            fh.write(result.stderr)
    return result.returncode, str(cwd)


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=20,
        )
    except Exception:
        return 1, ""
    return result.returncode, result.stdout


def detect_git_root(workdir: Path) -> Path | None:
    code, out = _run_git(["rev-parse", "--show-toplevel"], workdir)
    if code != 0:
        return None
    root = out.strip()
    if not root:
        return None
    path = Path(root)
    return path if path.exists() else None


def git_changed_files(git_root: Path | None) -> set[str]:
    if git_root is None:
        return set()

    code, out = _run_git(["status", "--porcelain"], git_root)
    if code != 0:
        return set()

    files: set[str] = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        payload = line[3:] if len(line) > 3 else ""
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        path = payload.strip().replace("\\", "/")
        if path:
            files.add(path)
    return files


def normalize_change_request(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("change_request")
    if not isinstance(raw, dict):
        return {}

    target_paths_raw = raw.get("target_paths")
    target_symbols_raw = raw.get("target_symbols")

    target_paths = [str(x).strip() for x in (target_paths_raw if isinstance(target_paths_raw, list) else []) if str(x).strip()]
    target_symbols = [str(x).strip() for x in (target_symbols_raw if isinstance(target_symbols_raw, list) else []) if str(x).strip()]

    return {
        "ref_task_id": str(raw.get("ref_task_id") or "").strip(),
        "change_type": str(raw.get("change_type") or "").strip().lower(),
        "target_paths": target_paths,
        "target_symbols": target_symbols,
        "max_files_changed": int(raw.get("max_files_changed") or 0),
        "max_lines_changed": int(raw.get("max_lines_changed") or 0),
    }


def _normalize_target_paths(targets: list[str], git_root: Path | None, workdir: Path) -> list[str]:
    normalized: list[str] = []
    for raw in targets:
        value = str(raw or "").strip().replace("\\", "/")
        if not value:
            continue

        p = Path(value)
        if p.is_absolute() and git_root is not None:
            try:
                rel = p.resolve().relative_to(git_root.resolve())
                value = rel.as_posix()
            except Exception:
                value = p.as_posix()

        if value.startswith("./"):
            value = value[2:]

        # If workdir is nested inside git root and target is workdir-relative, map it to repo-relative.
        if git_root is not None and not Path(value).is_absolute():
            try:
                rel_workdir = workdir.resolve().relative_to(git_root.resolve()).as_posix()
                if rel_workdir and rel_workdir != "." and not value.startswith(rel_workdir + "/"):
                    value = f"{rel_workdir}/{value}".replace("//", "/")
            except Exception:
                pass

        if value not in normalized:
            normalized.append(value)
    return normalized


def _matches_target(path: str, target: str) -> bool:
    file_path = path.replace("\\", "/")
    rule = target.replace("\\", "/").rstrip("/")
    if not rule:
        return False

    if any(ch in rule for ch in "*?[]"):
        return fnmatch.fnmatch(file_path, rule)

    return file_path == rule or file_path.startswith(rule + "/")


def evaluate_change_guard(task: dict[str, Any], workdir: Path) -> dict[str, Any]:
    cr = normalize_change_request(task)
    if not cr:
        return {
            "enabled": False,
            "status": "skipped",
            "reason": "no_change_request",
        }

    git_root = detect_git_root(workdir)
    if git_root is None:
        return {
            "enabled": True,
            "status": "skipped_no_git",
            "reason": "workdir is not a git repository",
            "workdir": str(workdir),
        }

    before_files = set(task.get("_guard_before_files") or [])
    after_files = git_changed_files(git_root)
    new_files = sorted(after_files - before_files)

    max_files = int(cr.get("max_files_changed") or 0)
    targets = _normalize_target_paths(list(cr.get("target_paths") or []), git_root, workdir)

    failures: list[str] = []
    outside_scope: list[str] = []

    if max_files > 0 and len(new_files) > max_files:
        failures.append(f"changed files limit exceeded: {len(new_files)} > {max_files}")

    if targets:
        for file_path in new_files:
            if not any(_matches_target(file_path, rule) for rule in targets):
                outside_scope.append(file_path)
        if outside_scope:
            failures.append("changed files outside target_paths scope")

    status = "ok" if not failures else "failed"
    reason = "; ".join(failures) if failures else "within scoped change limits"

    return {
        "enabled": True,
        "status": status,
        "reason": reason,
        "workdir": str(workdir),
        "git_root": str(git_root),
        "target_paths": targets,
        "max_files_changed": max_files,
        "new_files": new_files,
        "outside_scope": outside_scope,
        "before_count": len(before_files),
        "after_count": len(after_files),
    }


def qa_note_indicates_failure(note: str) -> bool:
    text = str(note or "").strip().lower()
    if not text:
        return False

    has_negative = any(re.search(pattern, text) for pattern in QA_NEGATIVE_PATTERNS)
    if not has_negative:
        return False

    has_positive = any(re.search(pattern, text) for pattern in QA_POSITIVE_PATTERNS)
    return not has_positive


def _parse_task_created_ts(task: dict[str, Any]) -> float | None:
    value = str(task.get("created_at") or "").strip()
    if not value:
        return None
    try:
        # canonical format in this project: 2026-02-28T01:49:36Z
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _queue_sort_key(task_file: Path) -> tuple[float, str]:
    # FIFO by logical task creation time; fallback to file mtime.
    created_ts = None
    try:
        task = read_task(task_file)
        created_ts = _parse_task_created_ts(task)
    except Exception:
        created_ts = None

    if created_ts is None:
        try:
            created_ts = task_file.stat().st_mtime
        except Exception:
            created_ts = 0.0

    return (created_ts, task_file.name)


def process_one(role: str) -> None:
    queue_dir = DATA_DIR / "queues" / role
    done_dir = DATA_DIR / "done" / role
    failed_dir = DATA_DIR / "failed" / role
    dev_dir = DEVELOPERS_DIR / role
    memory_path = dev_dir / "memory.md"
    logs_dir = dev_dir / "logs"
    queue_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    for task_file in sorted(queue_dir.glob("*.json"), key=_queue_sort_key):
        title = task_file.stem
        try:
            task = read_task(task_file)
            task_id = task.get("id", task_file.stem)
            title = task.get("title", task_id)
            append_memory(memory_path, "doing", f"Взял задачу '{title}'")

            command = task.get("command")
            mode = str(task.get("mode") or "").strip().lower() or ("command" if command else "ai")
            workdir = Path(task.get("workdir") or "/root")
            workdir.mkdir(parents=True, exist_ok=True)

            task["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            task["status"] = "in_progress"
            task["mode"] = mode

            git_root = detect_git_root(workdir)
            task["_guard_before_files"] = sorted(git_changed_files(git_root)) if git_root else []

            write_task(task_file, task)

            if mode == "command":
                if not command:
                    status = "error"
                    note = f"Задача '{title}' в command-режиме, но поле command пустое"
                else:
                    log_path = logs_dir / f"{task_file.stem}.log"
                    code, used_cwd = run_command(command, str(workdir), log_path)
                    task["command_exit_code"] = code
                    task["command_workdir"] = used_cwd
                    task["worker_log"] = str(log_path)
                    status = "done" if code == 0 else "error"
                    note = f"Задача '{title}' завершена, code={code}"
            elif mode == "ai":
                ai_status, ai_note, ai_log = run_ai_task(role, task, logs_dir)
                if role == "qa" and ai_status == "done" and qa_note_indicates_failure(ai_note):
                    ai_status = "blocked"
                    ai_note = f"{ai_note}; QA verdict содержит нерешенные дефекты"
                task["ai_status"] = ai_status
                task["ai_note"] = ai_note
                task["ai_log"] = ai_log
                status = "done" if ai_status == "done" else "error"
                note = f"AI-агент: {ai_note}"
            else:
                status = "done"
                note = f"Задача '{title}' в manual-режиме (без автозапуска)"

            guard_result = evaluate_change_guard(task, workdir)
            task["change_guard"] = guard_result
            if guard_result.get("enabled"):
                task["changed_files_new"] = guard_result.get("new_files", [])

            if guard_result.get("status") == "failed":
                status = "error"
                note = f"{note}; change_guard: {guard_result.get('reason')}"

            task["status"] = "done" if status == "done" else "failed"
            task["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            task.pop("_guard_before_files", None)
            write_task(task_file, task)

            append_memory(memory_path, status, note)
            # Save distilled lesson for future tasks (lightweight experience cache)
            if mode == "ai":
                save_task_lesson(role, title, ai_status, ai_note)
            destination_dir = done_dir if task["status"] == "done" else failed_dir
            shutil.move(str(task_file), destination_dir / task_file.name)
        except KeyboardInterrupt:
            # Worker interrupted by PM2 SIGINT during task processing.
            # Save task as failed so it is not retried in an infinite loop on restart.
            try:
                task["status"] = "failed"
                task["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                task["ai_note"] = task.get("ai_note", "Прервано сигналом завершения процесса")
                write_task(task_file, task)
                if task_file.exists():
                    shutil.move(str(task_file), failed_dir / task_file.name)
                append_memory(memory_path, "error", f"Задача '{title}' прервана (SIGINT)")
            except Exception:
                pass
            raise
        except Exception as exc:
            append_memory(memory_path, "error", f"Ошибка обработки '{title}': {exc}")
            if task_file.exists():
                shutil.move(str(task_file), failed_dir / task_file.name)


def seed_memory(role: str) -> None:
    memory_path = DEVELOPERS_DIR / role / "memory.md"
    if not memory_path.exists():
        append_memory(memory_path, "done", f"Инициализирован агент роли {role}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["frontend", "backend", "devops", "qa", "designer"])
    args = parser.parse_args()

    role = args.role
    ensure_runtime_layout()
    seed_memory(role)
    append_memory(DEVELOPERS_DIR / role / "memory.md", "doing", f"Агент {role} запущен")

    while True:
        process_one(role)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
