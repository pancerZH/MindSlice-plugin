"""Claude Code driver: where Claude puts plugin data and options, and how its SessionStart hooks deliver pages.

Hooks: ``hooks/hooks.json`` runs ``sh adapter/hook-<slot>`` for slots 1..K in one matcher-less
``SessionStart`` group (startup, resume, clear, compact); each launcher picks a Python (``py``, ``python3``,
``python``), so hooks need no configuration. Claude runs them in parallel (``sh -c`` on macOS/Linux, Git Bash on Windows) and
adds each one's plain-text stdout to the context (up to 10,000 characters each), so slot ``i`` prints page ``i``
of one shared snapshot.

The plugin has no top-level ``bin/`` (Claude puts it on the Bash tool's PATH, but Chat and Cowork refuse to
install a plugin that has one). Slot 1 provides the ``mindslice`` command instead: it writes a small launcher to
``<plugin data>/bin/`` that runs the verified interpreter on this plugin version's ``adapter/entry.py`` and,
through ``$CLAUDE_ENV_FILE``, puts that directory first on the Bash tool's PATH, next to ``MINDSLICE_PLUGIN_DATA``
and, once resolved, ``MINDSLICE_PLUGIN_WORKSPACE``. It does so in every state (unconfigured, isolated), since
``mindslice plugin-status`` is how setup diagnoses those states.

The MCP server's command is ``${CLAUDE_PLUGIN_ROOT}/adapter/mcp`` itself (the plugin directory refuses
commands it cannot follow, such as a configurable interpreter, and follows a script only when it uses no variable
but ``CLAUDE_PLUGIN_ROOT``): the sh launcher on macOS/Linux, ``mcp.cmd`` on Windows, where Claude's spawn
resolves the name through PATHEXT. Its workspace option arrives in the
environment (``MINDSLICE_PLUGIN_OPTION_WORKSPACE``), not on the command line.
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


def _clean(value: str | None) -> str | None:
    """An option value, or None when empty or left unsubstituted (``${user_config.x}``). Callers read each
    variable by its literal name."""
    value = (value or "").strip()
    return value if value and "${" not in value else None


def plugin_data_dir() -> Path:
    # Claude sets CLAUDE_PLUGIN_DATA for hooks and the MCP server, not for the Bash tool: there the CLI uses the
    # MINDSLICE_PLUGIN_DATA that slot 1 exported, so it shares the engine copy and the bridge file.
    data = _clean(os.environ.get("CLAUDE_PLUGIN_DATA")) or _clean(os.environ.get("MINDSLICE_PLUGIN_DATA"))
    return Path(data) if data else Path.home() / ".cache" / "mindslice-plugin" / NAME


def configured_workspace() -> str | None:
    # hooks: Claude's own variable; the MCP server: the copy plugin.json puts in its environment
    return (_clean(os.environ.get("CLAUDE_PLUGIN_OPTION_WORKSPACE"))
            or _clean(os.environ.get("MINDSLICE_PLUGIN_OPTION_WORKSPACE")))


def stage_writes_enabled() -> bool:
    values = (os.environ.get("MINDSLICE_PLUGIN_STAGE_WRITES"), os.environ.get("CLAUDE_PLUGIN_OPTION_STAGE_WRITES"))
    return any((_clean(v) or "").lower() in ("1", "true", "yes", "on") for v in values)


def _hook_input() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        value = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def launcher_dir() -> Path:
    import core

    return core.plugin_data_dir() / "bin"


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
    """``<plugin data>/bin/mindslice`` (and ``mindslice.cmd`` on Windows): stable paths that run the plugin
    version installed now with the interpreter this hook runs on (already checked to be 3.12+), refreshed at every
    session start, so links to them survive plugin updates. They run entry.py directly: the Bash tool and the
    user's terminal have no ``CLAUDE_PLUGIN_ROOT``."""
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


def path_entry(directory: Path) -> str:
    """``directory`` as an entry of the Bash tool's PATH: Git Bash on Windows needs /c/... (C:/... has a colon)."""
    if os.name != "nt":
        return str(directory)
    posix = directory.as_posix()
    cygpath = shutil.which("cygpath")
    if cygpath:
        try:
            out = subprocess.run([cygpath, "-u", posix], capture_output=True, text=True, timeout=10).stdout.strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    if len(posix) > 1 and posix[1] == ":":  # Git for Windows mounts drive C: at /c
        return "/" + posix[0].lower() + posix[2:]
    return posix


def env_lines(workspace: Path | None, launchers: Path | None = None) -> str:
    """What slot 1 adds to ``$CLAUDE_ENV_FILE``: ``export NAME='value'`` lines (forward slashes for Git Bash on
    Windows) and the PATH entry for the launcher, added once."""
    lines = ""
    data = _clean(os.environ.get("CLAUDE_PLUGIN_DATA"))
    if data:  # namespaced: the Bash tool's environment is shared by every plugin
        lines += f"export MINDSLICE_PLUGIN_DATA={shlex.quote(Path(data).as_posix())}\n"
    if launchers is not None:
        entry = shlex.quote(path_entry(launchers))
        lines += f'case ":$PATH:" in *:{entry}:*) ;; *) export PATH={entry}:"$PATH" ;; esac\n'
    if workspace is not None:
        lines += f"export MINDSLICE_PLUGIN_WORKSPACE={shlex.quote(str(workspace))}\n"
    return lines


def _export_env(workspace: Path | None) -> None:
    try:
        launchers: Path | None = write_launchers()
    except OSError:
        launchers = None
    env_file = _clean(os.environ.get("CLAUDE_ENV_FILE"))
    if not env_file:
        return
    block = env_lines(workspace, launchers)
    try:
        target = Path(env_file)
        if target.is_file() and target.read_text(encoding="utf-8").endswith(block):
            return
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError:
        pass


def run_hook(args: list[str]) -> int:
    import core

    if core.isolated():  # no memory, no output; the command stays available (Forge calls it with -w)
        if args[:1] == ["1"]:
            _export_env(None)
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
    if slot == 1:
        _export_env(result.workspace)
    if slot <= len(result.pages):
        out = result.pages[slot - 1]
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.flush()
    return 0
