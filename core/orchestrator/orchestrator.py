#!/usr/bin/env python3
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from common import DATA_DIR, append_memory, load_roles, read_task, write_task
from pm_planner import plan_pm_task

POLL_SECONDS = 5
ORCH_MEMORY = Path(__file__).resolve().parent / "memory.md"
PM_DIR = DATA_DIR / "pm"
SUPPORTED_MODES = {"ai", "command", "manual", "pm"}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def choose_role(task: dict[str, Any], roles: dict[str, Any]) -> str:
    explicit_role = (task.get("role") or "").strip().lower()
    if explicit_role in roles:
        return explicit_role

    corpus = " ".join(
        [
            str(task.get("title", "")),
            str(task.get("description", "")),
            str(task.get("tags", "")),
        ]
    ).lower()

    best_role = "backend"
    best_score = -1

    for role, cfg in roles.items():
        score = sum(1 for kw in cfg.get("keywords", []) if str(kw).lower() in corpus)
        if score > best_score:
            best_score = score
            best_role = role
    return best_role


def normalize_mode(task: dict[str, Any]) -> str:
    mode = str(task.get("mode") or "").strip().lower()
    if mode in SUPPORTED_MODES:
        return mode
    return "command" if task.get("command") else "ai"


def queue_standard_task(task_file: Path, task: dict[str, Any], roles: dict[str, Any]) -> None:
    role = choose_role(task, roles)
    mode = normalize_mode(task)

    task["role"] = role
    task["mode"] = mode
    task["status"] = "assigned"
    task["assigned_at"] = now_iso()
    task["orchestrator_note"] = f"Assigned to {role} (mode={mode})"

    write_task(task_file, task)
    queue_path = DATA_DIR / "queues" / role / task_file.name
    shutil.move(str(task_file), queue_path)

    title = task.get("title", task_file.stem)
    append_memory(ORCH_MEMORY, "done", f"Распределил задачу '{title}' -> {role} (mode={mode})")


def queue_pm_parent_task(task_file: Path, task: dict[str, Any], roles: dict[str, Any]) -> None:
    parent_id = str(task.get("id") or task_file.stem)
    parent_title = str(task.get("title") or parent_id)

    task["id"] = parent_id
    task["mode"] = "pm"
    task["status"] = "planning"
    task["started_at"] = now_iso()

    plan_status, plan_note, subtasks, plan_meta = plan_pm_task(task, roles)

    planned_children: list[dict[str, Any]] = []
    parent_change_request = task.get("change_request") if isinstance(task.get("change_request"), dict) else None
    for idx, subtask in enumerate(subtasks, start=1):
        child_id = f"task-{uuid.uuid4().hex[:8]}"
        child_command = str(subtask.get("command") or "").strip()
        child_mode = str(subtask.get("mode") or "").strip().lower()
        if child_mode not in {"ai", "command", "manual"}:
            child_mode = "command" if child_command else "ai"
        if child_mode != "command":
            child_command = ""

        child_payload = {
            "id": child_id,
            "title": str(subtask.get("title") or f"{parent_title} / шаг {idx}"),
            "description": str(subtask.get("description") or task.get("description") or ""),
            "role": str(subtask.get("role") or "").strip().lower(),
            "command": child_command,
            "workdir": str(task.get("workdir") or ""),
            "mode": child_mode,
            "status": "new",
            "pm_parent_id": parent_id,
            "pm_parent_title": parent_title,
            "pm_step": idx,
            "pm_acceptance": str(subtask.get("acceptance_criteria") or ""),
        }

        if parent_change_request is not None:
            child_payload["change_request"] = parent_change_request

        child_path = DATA_DIR / "incoming" / f"{child_id}.json"
        write_task(child_path, child_payload)

        planned_children.append(
            {
                "id": child_id,
                "step": idx,
                "role": child_payload["role"],
                "mode": child_payload["mode"],
                "title": child_payload["title"],
                "acceptance_criteria": child_payload["pm_acceptance"],
            }
        )

    task["pm_note"] = plan_note
    task["pm_plan_status"] = plan_status
    task["pm_plan_source"] = str(plan_meta.get("source") or "unknown")
    task["pm_plan_meta"] = plan_meta
    task["pm_children"] = [item["id"] for item in planned_children]
    task["pm_plan"] = planned_children
    task["assigned_at"] = now_iso()
    task["status"] = "planned" if planned_children else "failed"

    PM_DIR.mkdir(parents=True, exist_ok=True)
    parent_path = PM_DIR / task_file.name
    if task_file.exists():
        shutil.move(str(task_file), parent_path)
    write_task(parent_path, task)

    if planned_children:
        append_memory(
            ORCH_MEMORY,
            "done",
            f"PM: декомпозировал '{parent_title}' на {len(planned_children)} задач и поставил в incoming",
        )
    else:
        append_memory(ORCH_MEMORY, "error", f"PM: не удалось декомпозировать '{parent_title}': {plan_note}")


def build_task_location_index(role_names: list[str]) -> dict[str, tuple[str, Path]]:
    index: dict[str, tuple[str, Path]] = {}

    for task_file in (DATA_DIR / "incoming").glob("*.json"):
        index[task_file.stem] = ("incoming", task_file)

    for role in role_names:
        for task_file in (DATA_DIR / "queues" / role).glob("*.json"):
            index[task_file.stem] = ("queue", task_file)
        for task_file in (DATA_DIR / "done" / role).glob("*.json"):
            index[task_file.stem] = ("done", task_file)
        for task_file in (DATA_DIR / "failed" / role).glob("*.json"):
            index[task_file.stem] = ("failed", task_file)

    return index


def runtime_state(bucket: str, task: dict[str, Any] | None) -> str:
    if bucket == "incoming":
        return "incoming"
    if bucket == "done":
        return "done"
    if bucket == "failed":
        return "failed"
    if bucket == "queue":
        status = str((task or {}).get("status") or "").strip().lower()
        if status == "in_progress":
            return "in_progress"
        return "queued"
    return "missing"


def refresh_pm_status(roles: dict[str, Any]) -> None:
    PM_DIR.mkdir(parents=True, exist_ok=True)
    location_index = build_task_location_index(list(roles.keys()))

    for pm_file in sorted(PM_DIR.glob("*.json")):
        try:
            pm_task = read_task(pm_file)
        except Exception as exc:
            append_memory(ORCH_MEMORY, "error", f"PM: не смог прочитать {pm_file.name}: {exc}")
            continue

        if str(pm_task.get("mode") or "").strip().lower() != "pm":
            continue

        prev_status = str(pm_task.get("status") or "").strip().lower() or "planned"
        if prev_status in {"done", "failed"}:
            continue

        children = [str(item).strip() for item in pm_task.get("pm_children", []) if str(item).strip()]
        if not children:
            pm_task["status"] = "failed"
            pm_task["completed_at"] = now_iso()
            pm_task["pm_progress"] = {"total": 0, "done": 0, "failed": 0, "pending": 0}
            write_task(pm_file, pm_task)
            append_memory(ORCH_MEMORY, "error", f"PM-задача '{pm_task.get('title', pm_file.stem)}' без подзадач")
            continue

        counts = {
            "incoming": 0,
            "queued": 0,
            "in_progress": 0,
            "done": 0,
            "failed": 0,
            "missing": 0,
        }
        child_states: list[dict[str, Any]] = []

        for child_id in children:
            location = location_index.get(child_id)
            child_task: dict[str, Any] = {}
            bucket = "missing"

            if location:
                bucket, path = location
                try:
                    child_task = read_task(path)
                except Exception:
                    child_task = {}

            state = runtime_state(bucket, child_task)
            if state not in counts:
                state = "missing"
            counts[state] += 1

            note_raw = (
                child_task.get("ai_note")
                or child_task.get("orchestrator_note")
                or child_task.get("command_exit_code")
                or ""
            )
            child_states.append(
                {
                    "id": child_id,
                    "title": child_task.get("title", child_id),
                    "role": child_task.get("role", ""),
                    "mode": child_task.get("mode", ""),
                    "status": state,
                    "note": str(note_raw),
                }
            )

        pending = counts["incoming"] + counts["queued"] + counts["in_progress"] + counts["missing"]
        next_status = "in_progress" if pending > 0 else ("failed" if counts["failed"] > 0 else "done")

        pm_task["status"] = next_status
        pm_task["pm_children_state"] = child_states
        pm_task["pm_progress"] = {
            "total": len(children),
            "done": counts["done"],
            "failed": counts["failed"],
            "pending": pending,
            "in_progress": counts["in_progress"],
            "queued": counts["queued"],
            "incoming": counts["incoming"],
            "missing": counts["missing"],
        }

        if next_status in {"done", "failed"}:
            pm_task["completed_at"] = pm_task.get("completed_at") or now_iso()

        write_task(pm_file, pm_task)

        if prev_status != next_status:
            title = pm_task.get("title", pm_file.stem)
            if next_status == "in_progress":
                append_memory(ORCH_MEMORY, "doing", f"PM-задача '{title}' перешла в исполнение")
            elif next_status == "done":
                append_memory(
                    ORCH_MEMORY,
                    "done",
                    f"PM-задача '{title}' выполнена: {counts['done']} done, {counts['failed']} failed",
                )
            else:
                append_memory(
                    ORCH_MEMORY,
                    "error",
                    f"PM-задача '{title}' завершена с ошибками: {counts['done']} done, {counts['failed']} failed",
                )


def process_incoming(roles: dict[str, Any]) -> None:
    incoming_dir = DATA_DIR / "incoming"

    for task_file in sorted(incoming_dir.glob("*.json")):
        try:
            task = read_task(task_file)
        except Exception as exc:
            append_memory(ORCH_MEMORY, "error", f"Не смог прочитать {task_file.name}: {exc}")
            failed_path = DATA_DIR / "failed" / task_file.name
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(task_file), failed_path)
            continue

        mode = normalize_mode(task)
        task["mode"] = mode

        try:
            if mode == "pm":
                queue_pm_parent_task(task_file, task, roles)
            else:
                queue_standard_task(task_file, task, roles)
        except Exception as exc:
            append_memory(ORCH_MEMORY, "error", f"Ошибка обработки '{task.get('title', task_file.stem)}': {exc}")
            failed_path = DATA_DIR / "failed" / task_file.name
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            if task_file.exists():
                shutil.move(str(task_file), failed_path)


def ensure_memory_seed() -> None:
    if not ORCH_MEMORY.exists():
        append_memory(ORCH_MEMORY, "done", "Оркестратор инициализирован")


def main() -> None:
    ensure_memory_seed()
    append_memory(ORCH_MEMORY, "doing", "Оркестратор запущен")

    while True:
        roles = load_roles()
        process_incoming(roles)
        refresh_pm_status(roles)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
