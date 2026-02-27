#!/usr/bin/env python3
import argparse
import json
import sys
from typing import Any

from ai_role_config import KNOWN_ROLES, load_role_ai_config, save_role_ai_config


def _validate_role(role: str) -> str:
    role_name = (role or "").strip().lower()
    if role_name not in KNOWN_ROLES:
        raise SystemExit(f"Unknown role: {role}. Allowed: {', '.join(KNOWN_ROLES)}")
    return role_name


def _print_list(data: dict[str, Any]) -> None:
    if not data:
        print("No role AI overrides. Defaults from env are used.")
        return

    print("role\tprovider\tmodel\tstrategy\tbase_url\tapi_key_env")
    for role in sorted(data.keys()):
        cfg = data.get(role) if isinstance(data.get(role), dict) else {}
        provider = str(cfg.get("provider") or "openai")
        model = str(cfg.get("model") or "")
        strategy = str(cfg.get("strategy") or "default")
        base_url = str(cfg.get("base_url") or "")
        api_key_env = str(cfg.get("api_key_env") or "")
        print(f"{role}\t{provider}\t{model}\t{strategy}\t{base_url}\t{api_key_env}")


def cmd_list(_: argparse.Namespace) -> None:
    _print_list(load_role_ai_config())


def cmd_show(args: argparse.Namespace) -> None:
    role = _validate_role(args.role)
    data = load_role_ai_config()
    cfg = data.get(role, {})
    print(json.dumps({role: cfg}, ensure_ascii=False, indent=2))


def cmd_set(args: argparse.Namespace) -> None:
    role = _validate_role(args.role)
    data = load_role_ai_config()
    cfg_raw = data.get(role, {})
    cfg = cfg_raw if isinstance(cfg_raw, dict) else {}

    if args.provider is not None:
        cfg["provider"] = args.provider.strip().lower()
    if args.model is not None:
        cfg["model"] = args.model.strip()
    if args.base_url is not None:
        cfg["base_url"] = args.base_url.strip()
    if args.api_key_env is not None:
        cfg["api_key_env"] = args.api_key_env.strip()
    if args.strategy is not None:
        strategy = args.strategy.strip().lower()
        if strategy not in {"default", "apply_only"}:
            raise SystemExit("strategy must be one of: default, apply_only")
        cfg["strategy"] = strategy

    data[role] = cfg
    save_role_ai_config(data)
    print(f"saved role AI config for {role}")
    print(json.dumps({role: cfg}, ensure_ascii=False, indent=2))


def cmd_reset(args: argparse.Namespace) -> None:
    role = _validate_role(args.role)
    data = load_role_ai_config()
    if role in data:
        data.pop(role)
        save_role_ai_config(data)
    print(f"reset role AI config for {role}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage per-role AI model/provider routing")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="List role AI overrides")
    p_list.set_defaults(fn=cmd_list)

    p_show = sub.add_parser("show", help="Show one role AI override")
    p_show.add_argument("role", help=f"one of: {', '.join(KNOWN_ROLES)}")
    p_show.set_defaults(fn=cmd_show)

    p_set = sub.add_parser("set", help="Set role AI override")
    p_set.add_argument("role", help=f"one of: {', '.join(KNOWN_ROLES)}")
    p_set.add_argument("--provider", default=None, help="e.g. openai")
    p_set.add_argument("--model", default=None, help="e.g. gpt-4.1-mini / codex-like model")
    p_set.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    p_set.add_argument("--api-key-env", default=None, help="Env var name containing API key")
    p_set.add_argument("--strategy", default=None, help="default | apply_only")
    p_set.set_defaults(fn=cmd_set)

    p_reset = sub.add_parser("reset", help="Reset role AI override")
    p_reset.add_argument("role", help=f"one of: {', '.join(KNOWN_ROLES)}")
    p_reset.set_defaults(fn=cmd_reset)

    return parser


def main() -> None:
    parser = build_parser()
    if len(sys.argv) == 1:
        cmd_list(argparse.Namespace())
        return

    args = parser.parse_args()
    fn = getattr(args, "fn", None)
    if fn is None:
        parser.print_help()
        raise SystemExit(2)
    fn(args)


if __name__ == "__main__":
    main()
