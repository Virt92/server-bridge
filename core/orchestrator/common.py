import json
import time
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
DEVELOPERS_DIR = BASE_DIR / "developers"
DEFAULT_ROLES = ("frontend", "backend", "devops", "qa")

def now_utc() -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

def load_roles() -> Dict[str, Any]:
    roles_path = CONFIG_DIR / "roles.json"
    with roles_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_data_layout(role_names: list[str] | None = None) -> None:
    roles = [str(x).strip() for x in (role_names or list(DEFAULT_ROLES)) if str(x).strip()]
    if not roles:
        roles = list(DEFAULT_ROLES)

    (DATA_DIR / "incoming").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "pm").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "failed").mkdir(parents=True, exist_ok=True)

    for role in roles:
        (DATA_DIR / "queues" / role).mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "done" / role).mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "failed" / role).mkdir(parents=True, exist_ok=True)
        (DEVELOPERS_DIR / role / "logs").mkdir(parents=True, exist_ok=True)


def ensure_runtime_layout() -> Dict[str, Any]:
    roles = load_roles()
    ensure_data_layout(list(roles.keys()))
    return roles

def append_memory(path: Path, status: str, note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"## {now_utc()}\n")
        fh.write(f"- status: {status}\n")
        fh.write(f"- note: {note}\n\n")

def read_task(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)

def write_task(path: Path, task: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(task, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
