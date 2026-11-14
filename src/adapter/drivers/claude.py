"""Claude Code driver: where Claude puts plugin data and options, and how its SessionStart hooks deliver pages.

Hooks: ``hooks/hooks.json`` runs ``sh bin/mindslice hook <slot>`` for slots 1..K in one matcher-less
``SessionStart`` group (startup, resume, clear, compact); the shim picks a Python (``py`` first on Windows), so
hooks need no configuration. Claude runs them in parallel (``sh -c`` on macOS/Linux, Git Bash on Windows) and
adds each one's plain-text stdout to the context (up to 10,000 characters each), so slot ``i`` prints page ``i``
of one shared snapshot. Slot 1 also exports ``MINDSLICE_PLUGIN_WORKSPACE`` and ``MINDSLICE_PLUGIN_PYTHON`` (the
verified interpreter) and ``MINDSLICE_PLUGIN_DATA`` through ``$CLAUDE_ENV_FILE`` for the Bash tool.

The MCP server is started directly by Claude with the ``python`` plugin option (default ``python3``): on Windows,
where ``python3`` is usually missing or the Microsoft Store placeholder, the user sets it to ``py``.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "claude"
reinjects_on_compact = True  # SessionStart fires again with source "compact"
options_reach_hooks = True  # user-set options arrive as $CLAUDE_PLUGIN_OPTION_<KEY> (only defaults do not)
REVIEW_COMMAND = "/mindslice:review"
CLI_HINT = ("The `mindslice` CLI is on the Bash tool's PATH and uses this workspace by default (pass -w for "
            "another one); management commands (status, diff, apply, discard, mount, bake, doctor) are CLI-only. "
            "Run `mindslice apply` or `discard` only when the user approves it explicitly (see /mindslice:review).")


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value if value and "${" not in value else None


def plugin_data_dir() -> Path:
    # Claude sets CLAUDE_PLUGIN_DATA for hooks and the MCP server, not for the Bash tool: there the CLI uses the
    # MINDSLICE_PLUGIN_DATA that slot 1 exported, so it shares the engine copy and the bridge file.
    data = _env("CLAUDE_PLUGIN_DATA") or _env("MINDSLICE_PLUGIN_DATA")
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


def env_lines(workspace: Path) -> str:
    """What slot 1 adds to ``$CLAUDE_ENV_FILE``: plain ``export NAME='value'`` lines (forward slashes, so Git Bash
    on Windows can run the interpreter path as is)."""
    python = Path(sys.executable).as_posix()
    lines = (f"export MINDSLICE_PLUGIN_WORKSPACE={shlex.quote(str(workspace))}\n"
             f"export MINDSLICE_PLUGIN_PYTHON={shlex.quote(python)}\n")
    data = _env("CLAUDE_PLUGIN_DATA")
    if data:  # namespaced: the Bash tool's environment is shared by every plugin
        lines += f"export MINDSLICE_PLUGIN_DATA={shlex.quote(Path(data).as_posix())}\n"
    return lines


def _export_env(workspace: Path) -> None:
    env_file = _env("CLAUDE_ENV_FILE")
    if not env_file:
        return
    block = env_lines(workspace)
    try:
        target = Path(env_file)
        if target.is_file() and target.read_text(encoding="utf-8").endswith(block):
            return
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError:
        pass


def _python_ok(command: str) -> bool:
    exe = shutil.which(command)
    if not exe:
        return False
    try:
        return subprocess.run([exe, "-c", "import sys; sys.exit(sys.version_info < (3, 8))"], timeout=10,
                              stdin=subprocess.DEVNULL, capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def startup_notes() -> list[str]:
    """Windows only: the MCP server is started with the ``python`` option (default ``python3``), which usually
    does not exist there. Say how to fix it if the tools are missing (the option may be set without the hook
    seeing it, so the note is conditional)."""
    if os.name != "nt" or _env("CLAUDE_PLUGIN_OPTION_PYTHON") or _python_ok("python3"):
        return []
    return ["On Windows the plugin's MCP server starts with the \"Python command\" plugin option, which defaults "
            "to `python3`, and `python3` does not run here. If the mcp__plugin_mindslice_mindslice__* tools are "
            "missing in this session, tell the user to set that option to `py` (or the full path of python.exe) "
            "via /plugin and start a new session."]


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
        _export_env(result.workspace)
    if slot <= len(result.pages):
        out = result.pages[slot - 1]
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.flush()
    return 0
