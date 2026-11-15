"""Codex driver: where Codex puts plugin data, where the plugin keeps its settings, and how its SessionStart hook
delivers pages.

Measured on Codex CLI 0.169.0:

- ``hooks/hooks.json`` runs ``python3 "${PLUGIN_ROOT}/adapter/hook.py"`` (``py`` and ``python`` as fallbacks) as
  the one handler of a matcher-less ``SessionStart`` group (sources startup, resume, clear, compact, fork). Codex
  substitutes ``${PLUGIN_ROOT}`` itself, runs the command in the session's working directory and gives it
  ``PLUGIN_ROOT`` and ``PLUGIN_DATA`` (``<CODEX_HOME>/plugins/data/<plugin>-<marketplace>``) plus the
  ``CLAUDE_PLUGIN_*`` copies. The hook prints ``{"hookSpecificOutput": {"hookEventName": "SessionStart",
  "additionalContext": <every page>}}``: plain text that starts with "[" (as every page does) is parsed as JSON
  and fails the hook. A hook's context is cut at about 2,500 tokens unless ``additionalContextLimit`` raises it,
  which hooks.json does; the limit has no low ceiling (400,000 characters arrived whole with a limit of
  1,000,000), so one hook carries all pages. The user trusts each handler separately and again after every
  plugin update, which is one more reason to have only one.
- Plugin hooks are skipped until the user trusts them (``/hooks`` in the TUI; ``--dangerously-bypass-hook-trust``
  for one ``codex exec``), so the MCP tools may work in a session that received no pages: the server's
  instructions (Codex shows them to the model as the description of the server's tool namespace) say to call
  ``manifest`` then.
- The MCP server (``.mcp.json``: ``./adapter/mcp`` run in the plugin folder) gets a filtered environment (only
  what ``env_vars`` names passes through: ``MINDSLICE_PLUGIN_ISOLATE``): no ``PLUGIN_ROOT``/``PLUGIN_DATA``, and
  ``${...}`` in ``env``, ``args`` or ``cwd`` is not substituted. The driver therefore derives the data directory
  from the plugin folder's place in Codex's cache (``<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>``),
  the same one the hook is given. Tools annotated ``readOnlyHint`` run without an approval prompt; ``write`` asks
  (the user can allow it for good).
- There are no plugin options: the workspace and "review every write" live in ``settings.json`` in the data
  directory, written by ``mindslice plugin-config``. The hook reads it too (``options_reach_hooks``).
- The shell tool's PATH holds nothing of the plugin's, and Codex's sandbox keeps its commands from writing outside
  the project. The hook writes a stable launcher, ``<plugin data>/bin/mindslice``, and the startup pages give its
  absolute path; workspace commands need the user's approval to run outside the sandbox (``PERMISSION_HINT``).
- After compaction Codex fires ``SessionStart`` with source ``compact``, so the pages arrive again
  (``reinjects_on_compact``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

NAME = "codex"
reinjects_on_compact = True  # SessionStart fires again with source "compact"
options_reach_hooks = True  # the settings file is read by hooks and the MCP server alike
REVIEW_COMMAND = "the mindslice:review skill ($mindslice:review)"
SETTINGS = "settings.json"

PLUGIN_ROOT = Path(os.path.abspath(__file__)).parent.parent

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
    return load_settings().get("stage_writes") is True


def setup_hint() -> str:
    """How the user names the workspace (completes "To choose one, ..." and "Point the plugin at ... (...)")."""
    return (f"run `{_cli()} plugin-config --workspace <absolute path>` (outside Codex's sandbox: it writes the "
            "plugin's settings file), or ask Codex for $mindslice:setup")


def run_config(argv: list[str]) -> int:
    """``mindslice plugin-config``: show or change the plugin's settings (the workspace, "review every write")."""
    import core

    parser = argparse.ArgumentParser(prog="mindslice plugin-config",
                                     description="show or change the MindSlice plugin's settings for Codex")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--workspace", help="absolute path of the memory workspace (a MindSlice workspace, or a "
                                           "new or empty folder, initialized at the next session start)")
    where.add_argument("--unset-workspace", action="store_true", help="disconnect the workspace")
    parser.add_argument("--stage-writes", choices=("true", "false"),
                        help="true: every write waits in staging for the user's review")
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    core.ensure_utf8_stdio()
    settings = load_settings()
    changed = False
    if ns.workspace is not None:
        path, why = core.check_workspace_setting(ns.workspace)
        if path is not None and core.classify(path) == core.OCCUPIED:
            path, why = None, f"is not empty and is not a MindSlice workspace (no {core.MOUNTS_FILE})"
        if path is None:
            sys.stderr.write(f"mindslice plugin-config: the workspace {ns.workspace!r} {why}. Nothing was "
                             "changed.\n")
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
              "stage_writes": settings.get("stage_writes") is True, "changed": changed}
    if ns.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(f"settings: {report['settings_file']}\n"
                         f"workspace: {report['workspace'] or '(not configured)'}\n"
                         f"stage_writes: {str(report['stage_writes']).lower()}\n")
        if changed:
            sys.stdout.write("Saved. The MCP server and the startup hook read these settings when a session "
                             "starts: start a new Codex session.\n")
    return 0


# ---------------------------------------------------------------------------
# the CLI launcher
# ---------------------------------------------------------------------------
def launcher_dir() -> Path:
    """Where ``core.write_launchers`` puts the command: a path that stays the same across plugin versions."""
    import core

    return core.plugin_data_dir() / "bin"


def _cli() -> str:
    """The command the agent and the user run: the stable launcher once the hook has written it, else the plugin's
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


# ---------------------------------------------------------------------------
# the hook
# ---------------------------------------------------------------------------
def hook_output(pages: list[str]) -> str:
    """Every page in one additional context (hooks.json raises its limit), in order."""
    import core

    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                              "additionalContext": core.SEP.join(pages)}}, ensure_ascii=False)


def run_hook(args: list[str]) -> int:
    import core

    try:  # before the pages, so the CLI hint names the stable launcher; also when isolated (Forge calls it with -w)
        core.write_launchers()
    except OSError:
        pass
    if core.isolated():  # no memory, no output
        return 0
    cfg = core.target_config()
    session = str(core.hook_input().get("session_id") or f"ppid-{os.getppid()}")
    result = core.hook_pages(session, int(cfg["page_limit"]), int(cfg["hook_slots"]))
    if result.pages:
        sys.stdout.buffer.write((hook_output(result.pages) + "\n").encode("utf-8"))
        sys.stdout.flush()
    return 0
