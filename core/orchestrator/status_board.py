#!/usr/bin/env python3
from pathlib import Path

from common import DATA_DIR, ensure_runtime_layout, read_task

ROLES = ["frontend", "backend", "devops", "qa"]


def count_files(path: Path) -> int:
    return len(list(path.glob("*.json"))) if path.exists() else 0


def pm_stats() -> tuple[int, int, int, int, list[str]]:
    pm_dir = DATA_DIR / "pm"
    if not pm_dir.exists():
        return 0, 0, 0, 0, []

    total = 0
    active = 0
    done = 0
    failed = 0
    active_lines: list[str] = []

    for pm_file in sorted(pm_dir.glob("*.json")):
        total += 1
        try:
            task = read_task(pm_file)
        except Exception:
            failed += 1
            continue

        status = str(task.get("status") or "").strip().lower()
        title = str(task.get("title") or pm_file.stem)
        task_id = str(task.get("id") or pm_file.stem)
        progress = task.get("pm_progress") or {}
        done_cnt = int(progress.get("done") or 0)
        total_cnt = int(progress.get("total") or 0)

        if status in {"done"}:
            done += 1
        elif status in {"failed"}:
            failed += 1
        else:
            active += 1
            active_lines.append(f"{task_id} status={status or 'planned'} progress={done_cnt}/{total_cnt} title={title}")

    return total, active, done, failed, active_lines[:5]


def main() -> None:
    ensure_runtime_layout()
    incoming = count_files(DATA_DIR / "incoming")
    failed_root = DATA_DIR / "failed"
    failed_generic = count_files(failed_root)

    pm_total, pm_active, pm_done, pm_failed, pm_active_lines = pm_stats()

    print(f"incoming: {incoming}")
    print(f"failed:   {failed_generic}")
    print(f"pm:       total={pm_total:3} active={pm_active:3} done={pm_done:3} failed={pm_failed:3}")
    print("--- queues ---")

    for role in ROLES:
        q = count_files(DATA_DIR / "queues" / role)
        d = count_files(DATA_DIR / "done" / role)
        f = count_files(failed_root / role)
        print(f"{role:8} queue={q:3} done={d:3} failed={f:3}")

    if pm_active_lines:
        print("--- pm active ---")
        for line in pm_active_lines:
            print(line)


if __name__ == "__main__":
    main()
