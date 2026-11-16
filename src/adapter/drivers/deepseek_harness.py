"""DeepSeek Harness driver: plugin data directory, settings.json, and SystemPrompt payload.

Built for DeepSeek Harness (Desktop / Web / CLI) as a zero-dependency Node ESM Cordis bundle
(``dsh-mindslice``):

- ``adapter/plugin.js`` registers the stdio MCP server with ``ctx.mcpManager``, registers the
  MindSlice skills with ``ctx.skills``, and contributes the standing memory pages through
  ``system-prompt/assemble`` (cached per session and refreshed after ``compaction/summary``).
- Like Codex, DeepSeek Harness Desktop has no auto-generated config form for third-party plugins, so
  ``workspace`` and ``stage_writes`` live in ``settings.json`` in the plugin data directory
  (written by ``mindslice plugin-config``), with optional overrides from ``cordis.patch.yml``
  forwarded via ``MINDSLICE_PLUGIN_OPTION_WORKSPACE`` and ``MINDSLICE_PLUGIN_STAGE_WRITES``.
- ``adapter/hook.py`` runs ``entry.py hook 1`` and returns JSON
  ``{"systemPromptSections": [...], "cliBin": "...", "workspace": "..."}`` so the Node plugin can
  insert each page into ``system-prompt/assemble`` with ``interpolate: false``.
- The agent's shell tool (``pwsh`` on Windows, ``bash`` on POSIX) does not put the plugin on PATH,
  so the hook writes a stable launcher in ``<plugin data>/bin/`` and the startup preamble (plus
  optional ``DSH_MINDSLICE_BIN`` via ``ctx.shellEnv``) gives its exact path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

NAME = "deepseek-harness"
reinjects_on_compact = True  # system/message stays at node 0 and refreshes after compaction/summary
options_reach_hooks = True  # settings.json (and optional cordis.patch.yml env) reach both hook and MCP
REVIEW_COMMAND = "the mindslice-review skill (/mindslice-review)"
SETTINGS = "settings.json"

PLUGIN_ROOT = Path(os.path.abspath(__file__)).parent.parent

PERMISSION_HINT = ("DeepSeek Harness's sandbox keeps shell commands from writing outside the project, and the "
                   "memory workspace and plugin data folder lie outside it: rerun this `mindslice` command with "
                   "the wider sandbox/escalation approval DeepSeek Harness prompts for.")


def _clean(value: str | None) -> str | None:
    """A value, or None when empty or left unsubstituted (``${...}``). Callers read each variable by its literal
    name."""
    value = (value or "").strip()
    return value if value and "${" not in value else None


def home_dir() -> Path | None:
    """The user's home, read by its literal variable name (USERPROFILE on Windows, else HOME)."""
    value = _clean(os.environ.get("USERPROFILE")) if os.name == "nt" else _clean(os.environ.get("HOME"))
    return Path(value) if value else None


def _dsh_home() -> Path | None:
    raw = _clean(os.environ.get("DSH_HOME"))
    if raw:
        return Path(raw)
    home = home_dir()
    return home / ".dsh" if home is not None else None


def _newest_data_dir(candidates: list[Path]) -> Path | None:
    found: list[tuple[float, str, Path]] = []
    for candidate in candidates:
        for marker in (SETTINGS, "active_workspace.json"):
            try:
                st = (candidate / marker).stat()
                found.append((st.st_mtime, str(candidate), candidate))
            except OSError:
                pass
    return max(found)[2] if found else None


def plugin_data_dir() -> Path:
    # 1. Explicit PLUGIN_DATA / MINDSLICE_PLUGIN_DATA (set by adapter/plugin.js for hook and MCP)
    data = _clean(os.environ.get("PLUGIN_DATA")) or _clean(os.environ.get("MINDSLICE_PLUGIN_DATA"))
    if data:
        return Path(data)
    # 2. DSH_PROFILE_DIR (injected by dsh-shell-env into bash/pwsh tools)
    profile_dir = _clean(os.environ.get("DSH_PROFILE_DIR"))
    if profile_dir:
        return Path(profile_dir) / "plugin_data" / "mindslice"
    # 3. User's own terminal: scan $DSH_HOME/profiles/*/plugin_data/mindslice
    dsh_home = _dsh_home()
    if dsh_home is not None:
        profiles = dsh_home / "profiles"
        candidates: list[Path] = []
        try:
            for child in sorted(profiles.iterdir()):
                if child.is_dir():
                    candidates.append(child / "plugin_data" / "mindslice")
        except OSError:
            pass
        newest = _newest_data_dir(candidates)
        if newest is not None:
            return newest
        desktop = profiles / "desktop"
        if desktop.is_dir():
            return desktop / "plugin_data" / "mindslice"
    home = home_dir()
    if home is None:
        raise OSError("mindslice plugin: no plugin data directory (PLUGIN_DATA) and no home directory")
    return home / ".cache" / "mindslice-plugin" / NAME


# ---------------------------------------------------------------------------
# settings (stored in settings.json; cordis.patch.yml config may override via env)
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
    cleaned = _clean(value) if isinstance(value, str) else None
    return cleaned or _clean(os.environ.get("MINDSLICE_PLUGIN_OPTION_WORKSPACE"))


def stage_writes_enabled() -> bool:
    stored = load_settings().get("stage_writes")
    if isinstance(stored, bool):
        return stored
    raw = _clean(os.environ.get("MINDSLICE_PLUGIN_STAGE_WRITES"))
    return (raw or "").lower() in ("1", "true", "yes", "on")


def setup_hint() -> str:
    """How the user names the workspace (completes "To choose one, ..." and "Point the plugin at ... (...)")."""
    return (f"run `{_cli()} plugin-config --workspace <absolute path>` (approve outside-project access if "
            "prompted), or run `/mindslice-setup` in DeepSeek Harness")


def run_config(argv: list[str]) -> int:
    """``mindslice plugin-config``: show or change the plugin's settings (the workspace, "review every write")."""
    import core

    parser = argparse.ArgumentParser(prog="mindslice plugin-config",
                                     description="show or change the MindSlice plugin's settings for DeepSeek Harness")
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
            sys.stdout.write("Saved. The MCP server and startup memory read these settings when a new session "
                             "starts (or after disabling/enabling the plugin): start a new session.\n")
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
    return (f"The `mindslice` CLI is not on your shell's PATH: run it as `{_cli()}` (or `$env:DSH_MINDSLICE_BIN` "
            "in PowerShell / `\"$DSH_MINDSLICE_BIN\"` in bash when available; below, `mindslice` means that "
            "command). It uses this workspace by default (pass -w for another one); management commands (status, "
            "diff, apply, discard, mount, bake, doctor) are CLI-only. DeepSeek Harness's sandbox may block writes "
            "outside the project, so approve wider access if prompted. Run `mindslice apply` or `discard` only when "
            "the user approves it explicitly (see /mindslice-review).")


# ---------------------------------------------------------------------------
# the hook
# ---------------------------------------------------------------------------
def hook_output(pages: list[str], workspace: Path | None = None) -> str:
    """Standing memory pages plus the stable CLI path for ``adapter/plugin.js``."""
    return json.dumps({
        "systemPromptSections": pages,
        "cliBin": _cli(),
        "workspace": str(workspace) if workspace else None,
    }, ensure_ascii=False)


def run_hook(args: list[str]) -> int:
    import core

    try:  # before the pages, so the CLI hint names the stable launcher; also when isolated
        core.write_launchers()
    except OSError:
        pass
    if core.isolated():  # no memory, no output
        return 0
    cfg = core.target_config()
    session = str(core.hook_input().get("session_id") or f"ppid-{os.getppid()}")
    result = core.hook_pages(session, int(cfg["page_limit"]), int(cfg["hook_slots"]))
    if result.pages:
        sys.stdout.buffer.write((hook_output(result.pages, result.workspace) + "\n").encode("utf-8"))
        sys.stdout.flush()
    return 0
