"""Claude Code driver: where Claude puts plugin data and options, and how its SessionStart hooks deliver pages.

Hooks: ``hooks/hooks.json`` runs ``entry.py hook <slot>`` for slots 1..K in one matcher-less ``SessionStart``
group (startup, resume, clear, compact). Claude runs them in parallel and adds each one's plain-text stdout to
the context (up to 10,000 characters each), so slot ``i`` prints page ``i`` of one shared snapshot. Slot 1 also
exports ``MINDSLICE_PLUGIN_WORKSPACE`` through ``$CLAUDE_ENV_FILE`` for the Bash tool.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

NAME = "claude"
reinjects_on_compact = True  # SessionStart fires again with source "compact"
REVIEW_COMMAND = "/mindslice:review"
CLI_HINT = ("The `mindslice` CLI is on the Bash tool's PATH and uses this workspace by default (pass -w for "
            "another one); management commands (status, diff, apply, discard, mount, bake, doctor) are CLI-only. "
            "Run `mindslice apply` or `discard` only when the user approves it explicitly (see /mindslice:review).")


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value if value and "${" not in value else None


def plugin_data_dir() -> Path:
    data = _env("CLAUDE_PLUGIN_DATA")
    return Path(data) if data else Path.home() / ".cache" / "mindslice-plugin" / NAME


def configured_workspace() -> str | None:
    return _env("CLAUDE_PLUGIN_OPTION_WORKSPACE")


def stage_writes_enabled() -> bool:
    for name in ("MINDSLICE_PLUGIN_STAGE_WRITES", "CLAUDE_PLUGIN_OPTION_STAGE_WRITES"):
        if (_env(name) or "").lower() in ("1", "true", "yes", "on"):
            return True
    return False


def _hook_input() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        value = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _export_workspace(path: Path) -> None:
    env_file = _env("CLAUDE_ENV_FILE")
    if not env_file:
        return
    line = f"export MINDSLICE_PLUGIN_WORKSPACE={shlex.quote(str(path))}\n"
    try:
        target = Path(env_file)
        if target.is_file() and target.read_text(encoding="utf-8").endswith(line):
            return
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def run_hook(args: list[str]) -> int:
    import core

    if core.isolated():
        return 0
    cfg = core.target_config()
    slots = int(cfg["hook_slots"])
    try:
        slot = int(args[0]) if args else 1
    except ValueError:
        slot = 0
    if not 1 <= slot <= slots:
        sys.stderr.write(f"mindslice plugin: hook slot must be 1..{slots}\n")
        return 1
    info = _hook_input()
    session = str(info.get("session_id") or f"ppid-{os.getppid()}")
    result = core.hook_pages(session, int(cfg["page_limit"]), slots)
    if slot == 1 and result.workspace is not None:
        _export_workspace(result.workspace)
    if slot <= len(result.pages):
        out = result.pages[slot - 1]
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.flush()
    return 0
