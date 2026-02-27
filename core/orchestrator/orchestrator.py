#!/usr/bin/env python3
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from common import DATA_DIR, append_memory, ensure_runtime_layout, read_task, write_task
from pm_planner import append_pm_memory, plan_pm_task

POLL_SECONDS = 5
ORCH_MEMORY = Path(__file__).resolve().parent / "memory.md"
PM_DIR = DATA_DIR / "pm"
SUPPORTED_MODES = {"ai", "command", "manual", "pm"}
PM_QA_MAX_ROUNDS = max(1, int(os.getenv("PM_QA_MAX_ROUNDS", "2")))
PM_QA_GATE_ENABLED = str(os.getenv("PM_QA_GATE_ENABLED", "1")).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

PM_PENDING_STATES = {"incoming", "queued", "in_progress", "missing"}
PM_ACTIVE_STAGES = {"qa_gate", "implementation", "qa_recheck"}

PM_FIX_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "frontend": (
        "frontend",
        "ui",
        "ux",
        "layout",
        "css",
        "react",
        "client",
        "browser",
        "button",
        "form",
        "page",
        "render",
        "интерфейс",
        "верст",
        "кнопк",
        "страниц",
        "браузер",
    ),
    "backend": (
        "backend",
        "api",
        "endpoint",
        "database",
        " db ",
        "postgres",
        "redis",
        "sql",
        "query",
        "auth",
        "jwt",
        "session",
        "token",
        "500",
        "401",
        "403",
        "база",
        "бд",
        "серверн",
        "авторизац",
    ),
    "devops": (
        "devops",
        "deploy",
        "deployment",
        "infra",
        "network",
        "dns",
        "ssl",
        "tls",
        "caddy",
        "nginx",
        "port",
        "socket",
        "connection refused",
        "timed out",
        "timeout",
        "502",
        "503",
        "504",
        "gateway",
        "host",
        "domain",
        "сервер",
        "домен",
        "порт",
        "доступ",
        "ip",
        "хост",
    ),
}


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


def normalize_child_mode(raw_mode: str, raw_command: str) -> tuple[str, str]:
    command = str(raw_command or "").strip()
    mode = str(raw_mode or "").strip().lower()
    if mode not in {"ai", "command", "manual"}:
        mode = "command" if command else "ai"
    # PM child tasks should always execute automatically.
    if mode == "manual":
        mode = "ai"
    if mode != "command":
        command = ""
    return mode, command


def _normalize_pm_subtask_template(parent_title: str, parent_description: str, idx: int, subtask: dict[str, Any]) -> dict[str, Any]:
    mode, command = normalize_child_mode(str(subtask.get("mode") or ""), str(subtask.get("command") or ""))
    role = str(subtask.get("role") or "").strip().lower()
    title = str(subtask.get("title") or f"{parent_title} / шаг {idx}")
    description = str(subtask.get("description") or parent_description or "")
    acceptance = str(subtask.get("acceptance_criteria") or "")
    return {
        "template_step": idx,
        "title": title,
        "description": description,
        "role": role,
        "mode": mode,
        "command": command,
        "acceptance_criteria": acceptance,
    }


def _build_pm_child_payload(
    parent_task: dict[str, Any],
    template: dict[str, Any],
    step: int,
    pm_stage: str,
    pm_round: int,
) -> dict[str, Any]:
    parent_id = str(parent_task.get("id") or "")
    parent_title = str(parent_task.get("title") or parent_id)
    child_id = f"task-{uuid.uuid4().hex[:8]}"

    payload = {
        "id": child_id,
        "title": str(template.get("title") or f"{parent_title} / шаг {step}"),
        "description": str(template.get("description") or parent_task.get("description") or ""),
        "role": str(template.get("role") or "").strip().lower(),
        "command": str(template.get("command") or ""),
        "workdir": str(parent_task.get("workdir") or ""),
        "mode": str(template.get("mode") or "ai"),
        "status": "new",
        "pm_parent_id": parent_id,
        "pm_parent_title": parent_title,
        "pm_step": step,
        "pm_stage": pm_stage,
        "pm_round": pm_round,
        "pm_acceptance": str(template.get("acceptance_criteria") or ""),
    }

    parent_change_request = parent_task.get("change_request")
    if isinstance(parent_change_request, dict):
        payload["change_request"] = parent_change_request

    return payload


def _child_plan_item(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(payload.get("id") or ""),
        "step": int(payload.get("pm_step") or 0),
        "role": str(payload.get("role") or ""),
        "mode": str(payload.get("mode") or ""),
        "title": str(payload.get("title") or ""),
        "acceptance_criteria": str(payload.get("pm_acceptance") or ""),
        "stage": str(payload.get("pm_stage") or ""),
        "round": int(payload.get("pm_round") or 1),
    }


def _enqueue_pm_child(parent_task: dict[str, Any], template: dict[str, Any], pm_stage: str, pm_round: int) -> dict[str, Any]:
    children = [str(item).strip() for item in parent_task.get("pm_children", []) if str(item).strip()]
    step = len(children) + 1

    payload = _build_pm_child_payload(
        parent_task=parent_task,
        template=template,
        step=step,
        pm_stage=pm_stage,
        pm_round=pm_round,
    )

    child_path = DATA_DIR / "incoming" / f"{payload['id']}.json"
    write_task(child_path, payload)

    parent_task["pm_children"] = children + [payload["id"]]
    plan_items = list(parent_task.get("pm_plan") or [])
    plan_items.append(_child_plan_item(payload))
    parent_task["pm_plan"] = plan_items
    return payload


def _should_enable_pm_qa_gate(templates: list[dict[str, Any]]) -> bool:
    if not PM_QA_GATE_ENABLED:
        return False
    has_qa = any(str(item.get("role") or "").strip().lower() == "qa" for item in templates)
    has_impl = any(str(item.get("role") or "").strip().lower() in {"frontend", "backend", "devops"} for item in templates)
    return has_qa and has_impl


def _workflow_history_add(workflow: dict[str, Any], event: str, details: dict[str, Any] | None = None) -> None:
    history = workflow.get("history")
    if not isinstance(history, list):
        history = []
    entry = {"at": now_iso(), "event": event}
    if details:
        entry.update(details)
    history.append(entry)
    workflow["history"] = history[-50:]


def _infer_fix_roles_from_qa_states(stage_states: list[dict[str, Any]]) -> list[str]:
    if not stage_states:
        return []

    text_blob = " ".join(
        [
            str(item.get("title") or "")
            + " "
            + str(item.get("note") or "")
            + " "
            + str(item.get("description") or "")
            for item in stage_states
        ]
    ).lower()

    if not text_blob.strip():
        return []

    # Stronger signals for infra/network incidents.
    if re.search(r"(connection refused|timed out|timeout|dns|502|503|504|gateway|port|socket|host|domain)", text_blob):
        return ["devops"]

    scores: dict[str, int] = {}
    for role, keywords in PM_FIX_ROLE_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.strip() and keyword.lower() in text_blob:
                score += 1
        if score > 0:
            scores[role] = score

    if not scores:
        return []

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_score = ordered[0][1]
    selected = [role for role, score in ordered if score == best_score]
    # Preserve deterministic order by priority.
    return [role for role in ["devops", "backend", "frontend"] if role in selected]


def _filter_implementation_templates(templates: list[dict[str, Any]], roles: list[str]) -> list[dict[str, Any]]:
    if not templates:
        return []
    wanted = [str(role).strip().lower() for role in roles if str(role).strip()]
    if not wanted:
        return list(templates)

    filtered = [item for item in templates if str(item.get("role") or "").strip().lower() in wanted]
    return filtered or list(templates)


def _collect_pm_children_state(
    child_ids: list[str],
    location_index: dict[str, tuple[str, Path]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    counts = {
        "incoming": 0,
        "queued": 0,
        "in_progress": 0,
        "done": 0,
        "failed": 0,
        "missing": 0,
    }
    child_states: list[dict[str, Any]] = []

    for child_id in child_ids:
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
                "description": child_task.get("description", ""),
                "role": child_task.get("role", ""),
                "mode": child_task.get("mode", ""),
                "status": state,
                "note": str(note_raw),
                "stage": child_task.get("pm_stage", ""),
                "round": child_task.get("pm_round", 1),
            }
        )

    return counts, child_states


def _advance_pm_workflow(parent_task: dict[str, Any], child_states: list[dict[str, Any]]) -> tuple[bool, str]:
    workflow = parent_task.get("pm_workflow")
    if not isinstance(workflow, dict) or not workflow.get("enabled"):
        return False, ""

    stage = str(workflow.get("stage") or "").strip().lower()
    stage_child_ids = [str(item).strip() for item in workflow.get("current_stage_child_ids", []) if str(item).strip()]
    if stage not in PM_ACTIVE_STAGES:
        return False, ""
    if not stage_child_ids:
        parent_task["status"] = "failed"
        parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
        _workflow_history_add(workflow, "workflow_invalid", {"reason": "current_stage_child_ids is empty"})
        parent_task["pm_workflow"] = workflow
        return True, "workflow_invalid"

    by_id = {str(item.get("id") or ""): item for item in child_states}
    stage_states = [by_id.get(child_id, {"id": child_id, "status": "missing"}) for child_id in stage_child_ids]
    if any(str(item.get("status") or "") in PM_PENDING_STATES for item in stage_states):
        return False, ""

    stage_failed = any(str(item.get("status") or "") == "failed" for item in stage_states)
    current_round = int(workflow.get("round") or 1)
    max_rounds = max(1, int(workflow.get("max_rounds") or PM_QA_MAX_ROUNDS))
    impl_templates = list(workflow.get("implementation_templates") or [])

    if stage == "qa_gate":
        if not stage_failed:
            workflow["stage"] = "completed"
            workflow["current_stage_child_ids"] = []
            _workflow_history_add(workflow, "qa_gate_passed", {"round": current_round})
            parent_task["status"] = "done"
            parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
            parent_task["pm_workflow"] = workflow
            return True, "qa_gate_passed"

        inferred_roles = _infer_fix_roles_from_qa_states(stage_states)
        selected_impl = _filter_implementation_templates(impl_templates, inferred_roles)
        if not selected_impl:
            workflow["stage"] = "failed"
            workflow["current_stage_child_ids"] = []
            _workflow_history_add(
                workflow,
                "qa_gate_failed_no_fix_templates",
                {"round": current_round, "inferred_roles": inferred_roles},
            )
            parent_task["status"] = "failed"
            parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
            parent_task["pm_workflow"] = workflow
            return True, "qa_gate_failed_no_fix_templates"

        new_children = [
            _enqueue_pm_child(parent_task, template=item, pm_stage="implementation", pm_round=current_round)
            for item in selected_impl
        ]
        workflow["stage"] = "implementation"
        workflow["selected_fix_roles"] = [str(item.get("role") or "") for item in selected_impl]
        workflow["current_stage_child_ids"] = [str(item.get("id") or "") for item in new_children]
        _workflow_history_add(
            workflow,
            "implementation_queued",
            {
                "round": current_round,
                "children": workflow["current_stage_child_ids"],
                "inferred_roles": inferred_roles,
            },
        )
        parent_task["status"] = "in_progress"
        parent_task["pm_workflow"] = workflow
        return True, "implementation_queued"

    if stage == "implementation":
        if stage_failed:
            workflow["stage"] = "failed"
            workflow["current_stage_child_ids"] = []
            _workflow_history_add(workflow, "implementation_failed", {"round": current_round})
            parent_task["status"] = "failed"
            parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
            parent_task["pm_workflow"] = workflow
            return True, "implementation_failed"

        qa_template = workflow.get("qa_recheck_template")
        if not isinstance(qa_template, dict):
            qa_template = workflow.get("qa_gate_template")
        if not isinstance(qa_template, dict):
            workflow["stage"] = "failed"
            workflow["current_stage_child_ids"] = []
            _workflow_history_add(workflow, "qa_recheck_template_missing", {"round": current_round})
            parent_task["status"] = "failed"
            parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
            parent_task["pm_workflow"] = workflow
            return True, "qa_recheck_template_missing"

        qa_child = _enqueue_pm_child(parent_task, template=qa_template, pm_stage="qa_recheck", pm_round=current_round)
        workflow["stage"] = "qa_recheck"
        workflow["current_stage_child_ids"] = [str(qa_child.get("id") or "")]
        _workflow_history_add(
            workflow,
            "qa_recheck_queued",
            {"round": current_round, "children": workflow["current_stage_child_ids"]},
        )
        parent_task["status"] = "in_progress"
        parent_task["pm_workflow"] = workflow
        return True, "qa_recheck_queued"

    if stage == "qa_recheck":
        if not stage_failed:
            workflow["stage"] = "completed"
            workflow["current_stage_child_ids"] = []
            _workflow_history_add(workflow, "qa_recheck_passed", {"round": current_round})
            parent_task["status"] = "done"
            parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
            parent_task["pm_workflow"] = workflow
            return True, "qa_recheck_passed"

        if current_round >= max_rounds:
            workflow["stage"] = "failed"
            workflow["current_stage_child_ids"] = []
            _workflow_history_add(
                workflow,
                "qa_recheck_failed_max_rounds",
                {"round": current_round, "max_rounds": max_rounds},
            )
            parent_task["status"] = "failed"
            parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
            parent_task["pm_workflow"] = workflow
            return True, "qa_recheck_failed_max_rounds"

        next_round = current_round + 1
        inferred_roles = _infer_fix_roles_from_qa_states(stage_states)
        prev_roles = [str(item).strip() for item in workflow.get("selected_fix_roles", []) if str(item).strip()]
        reuse_roles = inferred_roles or prev_roles
        selected_impl = _filter_implementation_templates(impl_templates, reuse_roles)
        if not selected_impl:
            workflow["stage"] = "failed"
            workflow["current_stage_child_ids"] = []
            _workflow_history_add(
                workflow,
                "qa_recheck_failed_no_fix_templates",
                {"round": current_round, "inferred_roles": inferred_roles},
            )
            parent_task["status"] = "failed"
            parent_task["completed_at"] = parent_task.get("completed_at") or now_iso()
            parent_task["pm_workflow"] = workflow
            return True, "qa_recheck_failed_no_fix_templates"

        new_children = [
            _enqueue_pm_child(parent_task, template=item, pm_stage="implementation", pm_round=next_round)
            for item in selected_impl
        ]
        workflow["stage"] = "implementation"
        workflow["round"] = next_round
        workflow["selected_fix_roles"] = [str(item.get("role") or "") for item in selected_impl]
        workflow["current_stage_child_ids"] = [str(item.get("id") or "") for item in new_children]
        _workflow_history_add(
            workflow,
            "implementation_requeued",
            {"round": next_round, "children": workflow["current_stage_child_ids"], "inferred_roles": inferred_roles},
        )
        parent_task["status"] = "in_progress"
        parent_task["pm_workflow"] = workflow
        return True, "implementation_requeued"

    return False, ""


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


def _write_pm_memory_entry(pm_task: dict[str, Any], title: str, counts: dict[str, Any], status: str) -> None:
    templates = pm_task.get("pm_plan_templates") or []
    roles_used = sorted({
        str(t.get("role") or "").strip().lower()
        for t in templates
        if str(t.get("role") or "").strip()
    })
    total = counts.get("done", 0) + counts.get("failed", 0)
    outcome = f"{status}:{counts.get('done', 0)}/{total}"
    append_pm_memory(title, roles_used, outcome)


def queue_pm_parent_task(task_file: Path, task: dict[str, Any], roles: dict[str, Any]) -> None:
    parent_id = str(task.get("id") or task_file.stem)
    parent_title = str(task.get("title") or parent_id)

    task["id"] = parent_id
    task["mode"] = "pm"
    task["status"] = "planning"
    task["started_at"] = now_iso()

    plan_status, plan_note, subtasks, plan_meta = plan_pm_task(task, roles)

    templates = [
        _normalize_pm_subtask_template(
            parent_title=parent_title,
            parent_description=str(task.get("description") or ""),
            idx=idx,
            subtask=subtask,
        )
        for idx, subtask in enumerate(subtasks, start=1)
    ]

    task["pm_plan_templates"] = templates
    task["pm_children"] = []
    task["pm_plan"] = []

    planned_children: list[dict[str, Any]] = []
    if _should_enable_pm_qa_gate(templates):
        qa_templates = [item for item in templates if str(item.get("role") or "").strip().lower() == "qa"]
        impl_templates = [item for item in templates if str(item.get("role") or "").strip().lower() in {"frontend", "backend", "devops"}]
        qa_gate_template = qa_templates[0]
        qa_recheck_template = qa_templates[1] if len(qa_templates) > 1 else qa_templates[0]

        child = _enqueue_pm_child(task, template=qa_gate_template, pm_stage="qa_gate", pm_round=1)
        planned_children.append(_child_plan_item(child))

        task["pm_workflow"] = {
            "type": "qa_gate_v1",
            "enabled": True,
            "stage": "qa_gate",
            "round": 1,
            "max_rounds": PM_QA_MAX_ROUNDS,
            "qa_gate_template": qa_gate_template,
            "qa_recheck_template": qa_recheck_template,
            "implementation_templates": impl_templates,
            "selected_fix_roles": [],
            "current_stage_child_ids": [str(child.get("id") or "")],
            "history": [{"at": now_iso(), "event": "qa_gate_queued", "children": [str(child.get("id") or "")]}],
        }
    else:
        for template in templates:
            child = _enqueue_pm_child(task, template=template, pm_stage="parallel", pm_round=1)
            planned_children.append(_child_plan_item(child))

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

        counts, child_states = _collect_pm_children_state(children, location_index)

        workflow_changed, workflow_event = _advance_pm_workflow(pm_task, child_states)
        if workflow_changed:
            location_index = build_task_location_index(list(roles.keys()))
            children = [str(item).strip() for item in pm_task.get("pm_children", []) if str(item).strip()]
            counts, child_states = _collect_pm_children_state(children, location_index)

            title = pm_task.get("title", pm_file.stem)
            if workflow_event:
                append_memory(ORCH_MEMORY, "doing", f"PM workflow '{title}': {workflow_event}")

        pending = counts["incoming"] + counts["queued"] + counts["in_progress"] + counts["missing"]
        workflow = pm_task.get("pm_workflow") if isinstance(pm_task.get("pm_workflow"), dict) else {}
        workflow_stage = str(workflow.get("stage") or "").strip().lower()

        if str(pm_task.get("status") or "").strip().lower() in {"done", "failed"}:
            next_status = str(pm_task.get("status") or "").strip().lower()
        elif workflow_stage in PM_ACTIVE_STAGES:
            next_status = "in_progress"
        else:
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
                _write_pm_memory_entry(pm_task, title, counts, "done")
            else:
                append_memory(
                    ORCH_MEMORY,
                    "error",
                    f"PM-задача '{title}' завершена с ошибками: {counts['done']} done, {counts['failed']} failed",
                )
                _write_pm_memory_entry(pm_task, title, counts, "error")


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
    ensure_runtime_layout()
    ensure_memory_seed()
    append_memory(ORCH_MEMORY, "doing", "Оркестратор запущен")

    while True:
        roles = ensure_runtime_layout()
        process_incoming(roles)
        refresh_pm_status(roles)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
