"""Antigravity driver: where Antigravity puts plugin data and settings, and how its SessionStart hook delivers pages.

Measured on Antigravity CLI 1.5.9 (PLAN section 12):

- ``hooks.json`` at the plugin root runs ``python3 adapter/hook.py || py adapter/hook.py`` once per new
  conversation (``sh -c`` on macOS/Linux, ``cmd /c`` on Windows, in the plugin directory). One process prints
  every page, each one a ``systemMessage`` step of ``{"injectSteps": [...]}``; Antigravity cuts a single system
  message at 48 KiB of UTF-8 (wrapper included), so a page is at most ``page_limit`` UTF-16 units (UTF-8 never
  takes more than 3 bytes per unit) and the driver checks its byte length again before printing it.
- Hooks get ``PLUGIN_ROOT`` and ``PLUGIN_DATA``, but not the user's settings: the MCP server's ``variables``
  (the workspace) reach only the MCP server, which writes the bridge file the hook reads (``options_reach_hooks``
  is False). Both start together, so the hook waits a few seconds for a bridge file that does not exist yet.
- Compaction replaces the pages with a summary and fires no hook (``reinjects_on_compact`` is False): the engine
  text keeps "call manifest() again after compaction", and ``rules/AGENTS.md`` repeats it.
- The agent's ``run_command`` has the plugin's ``bin/`` on its PATH, but neither ``PLUGIN_ROOT`` nor
  ``PLUGIN_DATA``; it has ``ANTIGRAVITY_APP_DATA_DIR``, whose ``plugin_data/<plugin folder>`` is the same data
  directory, so the CLI shares the engine copy and the bridge file with the hook and the MCP server.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

NAME = "antigravity"
reinjects_on_compact = False  # no hook fires after compaction
options_reach_hooks = False  # the workspace variable reaches only the MCP server
REVIEW_COMMAND = "/mindslice:review"
CLI_HINT = ("The `mindslice` CLI is on the PATH of your terminal tool (run_command) and uses this workspace by "
            "default (pass -w for another one); management commands (status, diff, apply, discard, mount, bake, "
            "doctor) are CLI-only. Run `mindslice apply` or `discard` only when the user approves it explicitly "
            "(see /mindslice:review).")

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK_BYTE_LIMIT = 48000  # Antigravity truncates a system message beyond 49,152 bytes, its own ~230-byte wrapper included
BRIDGE_WAIT = 5.0  # seconds the hook waits for the MCP server's first bridge file
APP_DIRS = ("antigravity-cli", "antigravity", "antigravity-ide")  # ~/.gemini/<app>: CLI, Antigravity 2.0, IDE


def _clean(value: str | None) -> str | None:
    """A setting, or None when empty or left unsubstituted (``${workspace}``). Callers read each variable by its
    literal name."""
    value = (value or "").strip()
    return value if value and "${" not in value else None


def home_dir() -> Path | None:
    """The user's home, read by its literal variable name (USERPROFILE on Windows, else HOME)."""
    value = _clean(os.environ.get("USERPROFILE")) if os.name == "nt" else _clean(os.environ.get("HOME"))
    return Path(value) if value else None


def plugin_data_dir() -> Path:
    # Hooks and the MCP server: PLUGIN_DATA (installed plugins only). The agent's terminal tool: the app's data
    # directory. The user's own terminal: the app data directory that holds this plugin's bridge file.
    data = _clean(os.environ.get("PLUGIN_DATA")) or _clean(os.environ.get("MINDSLICE_PLUGIN_DATA"))
    if data:
        return Path(data)
    app = _clean(os.environ.get("ANTIGRAVITY_APP_DATA_DIR"))
    if app:
        return Path(app) / "plugin_data" / PLUGIN_ROOT.name
    home = home_dir()
    if home is None:
        raise OSError("mindslice plugin: no plugin data directory (PLUGIN_DATA) and no home directory")
    found = []
    for app_dir in APP_DIRS:
        candidate = home / ".gemini" / app_dir / "plugin_data" / PLUGIN_ROOT.name
        try:
            found.append(((candidate / "active_workspace.json").stat().st_mtime, candidate))
        except OSError:
            pass
    if found:
        return max(found)[1]
    return home / ".cache" / "mindslice-plugin" / NAME


def configured_workspace() -> str | None:
    # the MCP server's copy of the "workspace" variable (mcp_config.json); hooks never have it
    value = _clean(os.environ.get("MINDSLICE_PLUGIN_OPTION_WORKSPACE"))
    if value:
        _record_setting(value)
    return value


def _record_setting(value: str) -> None:
    """Point the bridge file at the setting as soon as the MCP server reads it, before the workspace is checked:
    the server refuses a folder that holds other files and exits, and the hook must then report that folder, not
    keep delivering the workspace an earlier setting named."""
    import core

    path = Path(os.path.abspath(core.expand_home(value)))
    if core.read_bridge() != str(path):
        core.write_bridge(path)


def stage_writes_enabled() -> bool:
    return (_clean(os.environ.get("MINDSLICE_PLUGIN_STAGE_WRITES")) or "").lower() in ("1", "true", "yes", "on")


def launcher_dir() -> Path:
    """The plugin's ``bin/``: Antigravity puts it on the agent's PATH; the user's own terminal can use it too."""
    return PLUGIN_ROOT / "bin"


def _hook_input() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        value = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _await_bridge() -> None:
    """The MCP server writes the bridge file once it has resolved the workspace; at the very first session it may
    still be starting (or installing the engine) when the hook runs."""
    import core

    if core.resolve("hook").state != core.UNSET:
        return
    deadline = time.monotonic() + BRIDGE_WAIT
    while time.monotonic() < deadline and core.read_bridge() is None:
        time.sleep(0.1)


def inject(pages: list[str]) -> dict:
    """The SessionStart output: one system message per page, each checked against Antigravity's byte limit."""
    import core

    n = len(pages)
    steps = []
    for i, page in enumerate(pages, 1):
        if len(page.encode("utf-8")) > HOOK_BYTE_LIMIT:
            page = core.FAULT.format(i=i, n=n)
        steps.append({"systemMessage": {"systemMessage": page}})
    return {"injectSteps": steps} if steps else {}


def run_hook(args: list[str]) -> int:
    import core

    if core.isolated():  # no memory, no output
        sys.stdout.write("{}\n")
        return 0
    cfg = core.target_config()
    info = _hook_input()
    session = str(info.get("conversationId") or f"ppid-{os.getppid()}")
    _await_bridge()
    result = core.hook_pages(session, int(cfg["page_limit"]), int(cfg["hook_slots"]))
    sys.stdout.buffer.write((json.dumps(inject(result.pages), ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0
