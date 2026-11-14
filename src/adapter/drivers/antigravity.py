"""Antigravity driver: where Antigravity puts plugin data and settings, and how its SessionStart hook delivers pages.

Measured on Antigravity CLI 1.5.9 (PLAN section 12):

- ``hooks.json`` at the plugin root runs ``py adapter/hook.py || python3 adapter/hook.py || python adapter/hook.py``
  once per new conversation (``sh -c`` on macOS/Linux, ``cmd /c`` on Windows, in the plugin directory). One process
  prints every page, each one a ``systemMessage`` step of ``{"injectSteps": [...]}``; Antigravity cuts a single system
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

PLUGIN_ROOT = Path(os.path.abspath(__file__)).parent.parent
REAL_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK_BYTE_LIMIT = 48000  # Antigravity truncates a system message beyond 49,152 bytes, its own ~230-byte wrapper included
BRIDGE_WAIT = 5.0  # seconds the hook waits for the MCP server's first bridge file
FRESH_ERROR = 15.0  # seconds: a bridge error newer than this came from the MCP server starting with this hook
APP_DIRS = ("antigravity-cli", "antigravity", "antigravity-ide")  # ~/.gemini/<app>: CLI, Antigravity 2.0, IDE
STAGE_WRITES_WARNING = "stage_writes_warning.txt"
COLD_START_HINT = (" (If the MindSlice MCP tools `manifest`, `search`, `read`, `write` are available in this "
                   "conversation, the MCP server finished starting after the startup hook: call `manifest` with "
                   "`include_always=true` before you reply.)")


def _clean(value: str | None) -> str | None:
    """A setting, or None when empty or left unsubstituted (``${workspace}``). Callers read each variable by its
    literal name."""
    value = (value or "").strip()
    return value if value and "${" not in value else None


def home_dir() -> Path | None:
    """The user's home, read by its literal variable name (USERPROFILE on Windows, else HOME)."""
    value = _clean(os.environ.get("USERPROFILE")) if os.name == "nt" else _clean(os.environ.get("HOME"))
    return Path(value) if value else None


def _dir_names() -> tuple[str, ...]:
    names = [PLUGIN_ROOT.name]
    for extra in (REAL_PLUGIN_ROOT.name, "mindslice"):
        if extra not in names:
            names.append(extra)
    return tuple(names)


def plugin_data_dir() -> Path:
    # Hooks and the MCP server: PLUGIN_DATA (installed plugins only). The agent's terminal tool: the app's data
    # directory when an installed plugin has used it, else the cache directory a workspace plugin uses. The user's
    # own terminal: the data directory that holds the newest bridge file.
    data = _clean(os.environ.get("PLUGIN_DATA")) or _clean(os.environ.get("MINDSLICE_PLUGIN_DATA"))
    if data:
        return Path(data)
    home = home_dir()
    cache = home / ".cache" / "mindslice-plugin" / NAME if home is not None else None
    app = _clean(os.environ.get("ANTIGRAVITY_APP_DATA_DIR"))
    if app:
        app_base = Path(app) / "plugin_data"
        dirs = [app_base / name for name in _dir_names()]
        newest = _newest_bridge_dir(dirs)
        if newest is not None:
            return newest
        for candidate in dirs:
            if candidate.is_dir():
                return candidate
        if cache is not None and (cache / "active_workspace.json").is_file():
            return cache
        return dirs[0]
    if cache is None:
        raise OSError("mindslice plugin: no plugin data directory (PLUGIN_DATA) and no home directory")
    candidates = [home / ".gemini" / app_dir / "plugin_data" / name
                  for app_dir in APP_DIRS for name in _dir_names()] + [cache]
    return _newest_bridge_dir(candidates) or cache


def _newest_bridge_dir(candidates: list[Path]) -> Path | None:
    """The candidate whose bridge file was written last (several can exist: an old install folder name, a
    workspace plugin's cache directory)."""
    found = []
    for candidate in candidates:
        try:
            found.append(((candidate / "active_workspace.json").stat().st_mtime, str(candidate), candidate))
        except OSError:
            pass
    return max(found)[2] if found else None


def _invalid_workspace_message(raw: str, reason: str) -> str:
    return (f"The configured MindSlice memory workspace {raw!r} {reason}. The plugin loaded no memory. "
            "Set \"Memory workspace\" in the plugin's settings (/plugin in the CLI, or the plugin's page in the "
            "Antigravity app) to an absolute path outside the plugin folder (for example ~/mindslice), then start "
            "a new conversation.")


def _validate_workspace(value: str) -> tuple[Path | None, str | None]:
    import core

    expanded = core.expand_home(value)
    if not Path(expanded).is_absolute():
        why = ("uses an unexpanded shell variable (use ~/... or a full path instead)"
               if value.startswith(("$", "%")) else "is a relative path, not an absolute path")
        return None, _invalid_workspace_message(value, why)
    path = Path(os.path.abspath(expanded))
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    roots = [(PLUGIN_ROOT, "is inside the plugin installation folder (which plugin updates replace)"),
             (REAL_PLUGIN_ROOT, "is inside the plugin installation folder (which plugin updates replace)")]
    try:
        data_dir = plugin_data_dir()
        roots += [(data_dir, "is inside the plugin's internal data folder"),
                  (data_dir.resolve(), "is inside the plugin's internal data folder")]
    except OSError:
        pass
    for root, why in roots:
        for candidate in (path, resolved):
            if candidate == root or root in candidate.parents:
                return None, _invalid_workspace_message(value, why)
    return path, None


def _clear_bridge() -> None:
    import core

    try:
        core.bridge_path().unlink(missing_ok=True)
    except OSError:
        pass


def _bridge_error() -> str | None:
    import core

    try:
        value = json.loads(core.bridge_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    err = value.get("error") if isinstance(value, dict) else None
    return err if isinstance(err, str) and err else None


def configured_workspace() -> str | None:
    # the MCP server's copy of the "workspace" variable (mcp_config.json); hooks never have it
    raw = os.environ.get("MINDSLICE_PLUGIN_OPTION_WORKSPACE")
    if raw is None:
        return None
    value = _clean(raw)
    if value is None:
        # An empty or unsubstituted setting means the plugin is unconfigured (e.g. after reinstall): drop any bridge
        # left in plugin_data from an earlier install so hooks do not keep delivering memory without the MCP tools.
        _clear_bridge()
        return None
    return _record_setting(value)


def _record_setting(value: str) -> str:
    """Point the bridge file at the setting as soon as the MCP server reads it, before the workspace is checked:
    the server refuses an invalid or occupied folder and exits, and the hook must then report that setting, not
    keep delivering the workspace an earlier setting named.

    An invalid setting raises instead of returning None: resolve() would otherwise fall through to
    MINDSLICE_WORKSPACE and silently serve (and record in the bridge) a workspace the user did not choose."""
    import core

    path, err = _validate_workspace(value)
    if err is not None or path is None:
        try:
            core.atomic_write(core.bridge_path(),
                              json.dumps({"invalid_workspace": value, "error": err}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        raise core.PluginError(err)
    if core.read_bridge() != str(path):
        core.write_bridge(path)
    return value


def stage_writes_enabled() -> bool:
    import core

    cleaned = _clean(os.environ.get("MINDSLICE_PLUGIN_STAGE_WRITES"))
    low = (cleaned or "").lower()
    if low in ("", "0", "false", "no", "off"):
        _set_stage_warning(None)
        return False
    if low in ("1", "true", "yes", "on"):
        _set_stage_warning(None)
        return True
    note = (f"Note: when the MindSlice MCP server last started, the plugin setting \"Review every write\" "
            f"(`stage_writes`) was {cleaned!r}, which is not `true` or `false`, so it stages every write for safety "
            "until the user sets it to `true` or `false` (if they already have, this note disappears from the next "
            "conversation).")
    sys.stderr.write(f"mindslice plugin: {note}\n")
    _set_stage_warning(note)
    return True


def _set_stage_warning(note: str | None) -> None:
    import core

    try:
        target = plugin_data_dir() / STAGE_WRITES_WARNING
        if note is None:
            target.unlink(missing_ok=True)
        else:
            core.atomic_write(target, note + "\n")
    except OSError:
        pass


def startup_notes() -> list[str]:
    try:
        text = (plugin_data_dir() / STAGE_WRITES_WARNING).read_text(encoding="utf-8").strip()
    except OSError:
        return []
    return [text] if text else []


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
    """The MCP server writes the bridge file once it has read the workspace setting; at the very first session it may
    still be starting (or installing the engine) when the hook runs."""
    import core

    if core.resolve("hook").state != core.UNSET:
        return
    # An error the MCP server recorded at an earlier start may be stale: the user may have fixed the setting since,
    # and this conversation's server is about to replace it. Only an error written just now (by the server starting
    # alongside this hook) ends the wait early.
    fresh_after = time.time() - FRESH_ERROR
    deadline = time.monotonic() + BRIDGE_WAIT
    while core.read_bridge() is None and not _fresh_bridge_error(fresh_after):
        if time.monotonic() >= deadline:
            return
        time.sleep(0.1)


def _fresh_bridge_error(after: float) -> bool:
    import core

    if _bridge_error() is None:
        return False
    try:
        return core.bridge_path().stat().st_mtime >= after
    except OSError:
        return False


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
    session = str(info.get("conversationId") or _clean(os.environ.get("ANTIGRAVITY_CONVERSATION_ID"))
                  or f"ppid-{os.getppid()}")
    _await_bridge()
    err = _bridge_error()
    state = core.resolve("hook").state
    if err is not None and state == core.UNSET:
        pages = [f"[MindSlice plugin: memory not loaded] {err}" + COLD_START_HINT]
    else:
        result = core.hook_pages(session, int(cfg["page_limit"]), int(cfg["hook_slots"]))
        pages = list(result.pages)
        if state == core.UNSET and pages:
            pages[0] = pages[0] + COLD_START_HINT
    sys.stdout.buffer.write((json.dumps(inject(pages), ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0
