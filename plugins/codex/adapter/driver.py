"""Codex driver: where Codex puts plugin data, where the plugin keeps its settings, and how its SessionStart hooks
deliver pages.

Measured on Codex CLI 0.169.0:

- ``hooks/hooks.json`` runs ``python3 "${PLUGIN_ROOT}/adapter/hook.py" <slot>`` (``py`` and ``python`` as
  fallbacks) for slots 1..K in one matcher-less ``SessionStart`` group (sources startup, resume, clear, compact,
  fork). Codex substitutes ``${PLUGIN_ROOT}`` itself, runs the commands concurrently in the session's working
  directory and gives them ``PLUGIN_ROOT`` and ``PLUGIN_DATA`` (``<CODEX_HOME>/plugins/data/<plugin>-<marketplace>``)
  plus the ``CLAUDE_PLUGIN_*`` copies. Each slot prints ``{"hookSpecificOutput": {"hookEventName": "SessionStart",
  "additionalContext": <page>}}``: plain text that starts with "[" (as every page does) is parsed as JSON and fails
  the hook. A hook's context is cut at about 2,500 tokens unless ``additionalContextLimit`` raises it, which
  hooks.json does.
- Plugin hooks are skipped until the user trusts them (``/hooks`` in the TUI; ``--dangerously-bypass-hook-trust``
  for one ``codex exec``), so the MCP tools may work in a session that received no pages: the server's
  instructions say to call ``manifest`` then.
- The MCP server (``.mcp.json``: ``./adapter/mcp`` run in the plugin folder) gets a filtered environment (only
  what ``env_vars`` names passes through: ``MINDSLICE_PLUGIN_ISOLATE``): no ``PLUGIN_ROOT``/``PLUGIN_DATA``, and
  ``${...}`` in ``env``, ``args`` or ``cwd`` is not substituted. The driver
  therefore derives the data directory from the plugin folder's place in Codex's cache
  (``<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>``), the same one the hooks are given. Tools
  annotated ``readOnlyHint`` run without an approval prompt; ``write`` asks (the user can allow it for good).
- There are no plugin options: the workspace and "review every write" live in ``settings.json`` in the data
  directory, written by ``mindslice plugin-config``. Hooks read it too (``options_reach_hooks``).
- The shell tool's PATH holds nothing of the plugin's, and Codex's sandbox keeps its commands from writing outside
  the project. Slot 1 writes a stable launcher, ``<plugin data>/bin/mindslice``, and the startup pages give its
  absolute path; workspace commands need the user's approval to run outside the sandbox (``PERMISSION_HINT``).
- After compaction Codex fires ``SessionStart`` with source ``compact``, so the pages arrive again
  (``reinjects_on_compact``).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

NAME = "codex"
reinjects_on_compact = True  # SessionStart fires again with source "compact"
options_reach_hooks = True  # the settings file is read by hooks and the MCP server alike
REVIEW_COMMAND = "the mindslice:review skill ($mindslice:review)"
SETTINGS = "settings.json"

PLUGIN_ROOT = Path(os.path.abspath(__file__)).parent.parent

# Codex runs a tool without asking when it declares itself read-only; write stays behind Codex's approval prompt.
TOOL_ANNOTATIONS = {
    "manifest": {"readOnlyHint": True, "openWorldHint": False},
    "search": {"readOnlyHint": True, "openWorldHint": False},
    "read": {"readOnlyHint": True, "openWorldHint": False},
}

PERMISSION_HINT = ("Codex's sandbox does not let shell commands write outside the project, and the memory "
                   "workspace and the plugin's data folder lie outside it: rerun this `mindslice` command with "
                   "escalated permissions (outside the sandbox); Codex asks the user to approve it.")


def _clean(value: str | None) -> str | None:
    """A value, or None when empty or left unsubstituted (``${...}``). Callers read each variable by its literal
    name."""
    value = (value or "").strip()
    return value if value and "${" not in value else None


def home_dir() -> Path | None:
    """The user's home, read by its literal variable name (USERPROFILE on Windows, else HOME)."""
    value = _clean(os.environ.get("USERPROFILE")) if os.name == "nt" else _clean(os.environ.get("HOME"))
    return Path(value) if value else None


def cache_data_dir(root: Path = PLUGIN_ROOT) -> Path | None:
    """The data directory Codex gives this plugin's hooks, derived from where it installed the plugin:
    ``<home>/plugins/cache/<marketplace>/<plugin>/<version>`` -> ``<home>/plugins/data/<plugin>-<marketplace>``."""
    parts = root.parts
    if len(parts) < 6 or parts[-4] != "cache" or parts[-5] != "plugins":
        return None
    return Path(*parts[:-4]) / "data" / f"{parts[-2]}-{parts[-3]}"


def plugin_data_dir() -> Path:
    # Hooks: PLUGIN_DATA. The MCP server, the shell tool and the user's terminal: derived from the plugin folder
    # (all of them run this file from it). A plugin run from a checkout: a cache directory under the home.
    data = _clean(os.environ.get("PLUGIN_DATA"))
    if data:
        return Path(data)
    derived = cache_data_dir()
    if derived is not None:
        return derived
    home = home_dir()
    if home is None:
        raise OSError("mindslice plugin: no plugin data directory (PLUGIN_DATA) and no home directory")
    return home / ".cache" / "mindslice-plugin" / NAME


# ---------------------------------------------------------------------------
# settings (Codex has no plugin options)
# ---------------------------------------------------------------------------
def settings_path() -> Path:
    return plugin_data_dir() / SETTINGS


def load_settings() -> dict:
    try:
        value = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_settings(settings: dict) -> Path:
    import core

    path = settings_path()
    core.atomic_write(path, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    return path


def configured_workspace() -> str | None:
    value = load_settings().get("workspace")
    return _clean(value) if isinstance(value, str) else None


def stage_writes_enabled() -> bool:
    if load_settings().get("stage_writes") is True:
        return True
    return (_clean(os.environ.get("MINDSLICE_PLUGIN_STAGE_WRITES")) or "").lower() in ("1", "true", "yes", "on")


def _setup_hint() -> str:
    return (f"run `{_cli()} plugin-config --workspace <absolute path>` (outside Codex's sandbox: it writes the "
            "plugin's settings file), or ask Codex for $mindslice:setup")


def unset_message() -> str:
    return ("The MindSlice plugin has no memory workspace configured yet, so no memory is loaded in this session. "
            f"To choose one, {_setup_hint()}; an existing MindSlice workspace is used as is, a new or empty folder "
            "is initialized. Then start a new session.")


def occupied_message(path: Path) -> str:
    return (f"The configured MindSlice memory workspace {path} is not empty and is not a MindSlice workspace "
            "(no mounts.toml). The plugin left it untouched and loaded no memory. Point the plugin at an empty "
            f"folder, a new path or an existing MindSlice workspace ({_setup_hint()}), then start a new session. "
            "Do not initialize a workspace inside that folder.")


def _validate_workspace(value: str) -> tuple[Path | None, str | None]:
    import core

    expanded = core.expand_home(value)
    if not Path(expanded).is_absolute():
        why = ("uses an unexpanded shell variable (use ~/... or a full path instead)"
               if value.startswith(("$", "%")) else "is a relative path, not an absolute path")
        return None, f"{value!r} {why}"
    path = Path(os.path.abspath(expanded))
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    roots = [(PLUGIN_ROOT, "is inside the plugin installation folder (which plugin updates replace)")]
    try:
        roots.append((plugin_data_dir(), "is inside the plugin's internal data folder"))
    except OSError:
        pass
    for root, why in roots:
        for r in {root, root.resolve()}:
            for candidate in (path, resolved):
                if candidate == r or r in candidate.parents:
                    return None, f"{value!r} {why}"
    if core.classify(path) == core.OCCUPIED:
        return None, (f"{path} is not empty and is not a MindSlice workspace (no mounts.toml); choose an empty "
                      "folder, a new path or an existing workspace")
    return path, None


def run_config(argv: list[str]) -> int:
    """``mindslice plugin-config``: show or change the plugin's settings (the workspace, "review every write")."""
    import core

    parser = argparse.ArgumentParser(prog="mindslice plugin-config",
                                     description="show or change the MindSlice plugin's settings for Codex")
    parser.add_argument("--workspace", help="absolute path of the memory workspace (a MindSlice workspace, or a "
                                            "new or empty folder, initialized at the next session start)")
    parser.add_argument("--unset-workspace", action="store_true", help="disconnect the workspace")
    parser.add_argument("--stage-writes", choices=("true", "false"),
                        help="true: every write waits in staging for the user's review")
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    settings = load_settings()
    changed = False
    if ns.workspace is not None and ns.unset_workspace:
        parser.error("--workspace and --unset-workspace exclude each other")
    if ns.workspace is not None:
        path, err = _validate_workspace(ns.workspace)
        if err is not None or path is None:
            sys.stderr.write(f"mindslice plugin-config: the workspace {err}. Nothing was changed.\n")
            return 1
        settings["workspace"] = str(path)
        changed = True
    if ns.unset_workspace:
        settings.pop("workspace", None)
        changed = True
    if ns.stage_writes is not None:
        settings["stage_writes"] = ns.stage_writes == "true"
        changed = True
    if changed:
        save_settings(settings)
        if ns.unset_workspace:
            try:
                core.bridge_path().unlink(missing_ok=True)
            except OSError:
                pass
    report = {"settings_file": str(settings_path()), "workspace": settings.get("workspace"),
              "stage_writes": bool(settings.get("stage_writes", False)), "changed": changed}
    if ns.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(f"settings: {report['settings_file']}\n"
                         f"workspace: {report['workspace'] or '(not configured)'}\n"
                         f"stage_writes: {str(report['stage_writes']).lower()}\n")
        if changed:
            sys.stdout.write("Saved. The MCP server and the startup hooks read these settings when a session "
                             "starts: start a new Codex session.\n")
    return 0


# ---------------------------------------------------------------------------
# the CLI launcher
# ---------------------------------------------------------------------------
def launcher_dir() -> Path:
    import core

    return core.plugin_data_dir() / "bin"


def _cli() -> str:
    """The command the agent and the user run: the stable launcher once slot 1 has written it, else the plugin's
    own ``bin/`` (whose path changes with every version)."""
    name = "mindslice.cmd" if os.name == "nt" else "mindslice"
    try:
        stable = launcher_dir() / name
        if stable.is_file():
            return str(stable)
    except OSError:
        pass
    return str(PLUGIN_ROOT / "bin" / name)


def cli_hint() -> str:
    return (f"The `mindslice` CLI is not on your shell's PATH: run it as `{_cli()}` (below, `mindslice` means that "
            "command). It uses this workspace by default (pass -w for another one); management commands (status, "
            "diff, apply, discard, mount, bake, doctor) are CLI-only. Codex's sandbox keeps shell commands from "
            "writing outside the project, so run `mindslice` commands that use the workspace with escalated "
            "permissions. Run `mindslice apply` or `discard` only when the user approves it explicitly (see "
            "$mindslice:review).")


def _write_if_changed(path: Path, text: str, newline: str = "\n") -> None:
    import core

    data = text.replace("\n", newline)
    try:
        if path.read_text(encoding="utf-8") == data:
            return
    except OSError:
        pass
    core.atomic_write(path, data)


def write_launchers() -> Path:
    """``<plugin data>/bin/mindslice`` (and ``mindslice.cmd`` on Windows): stable paths that run the plugin version
    installed now with the interpreter this hook runs on (already checked to be 3.12+), refreshed at every session
    start, so links to them survive plugin updates."""
    import core

    d = launcher_dir()
    entry = core.PLUGIN_ROOT / "adapter" / "entry.py"
    python = Path(sys.executable)
    sh = d / "mindslice"
    _write_if_changed(sh, "#!/bin/sh\n# Written by the MindSlice plugin at session start: runs the installed plugin's CLI.\n"
                          f"exec {shlex.quote(python.as_posix())} {shlex.quote(entry.as_posix())} \"$@\"\n")
    sh.chmod(0o755)
    if os.name == "nt":
        _write_if_changed(d / "mindslice.cmd", "@echo off\nrem Written by the MindSlice plugin at session start.\n"
                                               f"\"{python}\" \"{entry}\" %*\nexit /b %ERRORLEVEL%\n",
                          newline="\r\n")
    return d


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------
def _hook_input() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        value = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def hook_output(page: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": page}},
                      ensure_ascii=False)


def run_hook(args: list[str]) -> int:
    import core

    if core.isolated():  # no memory, no output; the command stays available (Forge calls it with -w)
        if args[:1] == ["1"]:
            try:
                write_launchers()
            except OSError:
                pass
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
    if slot == 1:
        try:  # before the pages, so the CLI hint names the stable launcher
            write_launchers()
        except OSError:
            pass
    info = _hook_input()
    session = str(info.get("session_id") or f"ppid-{os.getppid()}")
    result = core.hook_pages(session, int(cfg["page_limit"]), slots)
    if slot <= len(result.pages):
        sys.stdout.buffer.write((hook_output(result.pages[slot - 1]) + "\n").encode("utf-8"))
        sys.stdout.flush()
    return 0
