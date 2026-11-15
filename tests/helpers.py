"""Shared setup: the tests exercise the built plugin (``plugins/<target>``), exactly what users install."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ inside plugins/

REPO = Path(__file__).resolve().parent.parent
TARGET = os.environ.get("MINDSLICE_PLUGIN_TARGET", "claude")
PLUGIN = REPO / "plugins" / TARGET
ENTRY = PLUGIN / "adapter" / "entry.py"
WINDOWS = os.name == "nt"
CLAUDE = TARGET == "claude"
CODEX = TARGET == "codex"
# What the host sets for hooks and the MCP server: the plugin's data directory and its root.
DATA_ENV, ROOT_ENV = ("CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_ROOT") if CLAUDE else ("PLUGIN_DATA", "PLUGIN_ROOT")


def only(target: str):
    """Skip a test (or class) unless the suite runs against ``target`` (MINDSLICE_PLUGIN_TARGET)."""
    return unittest.skipUnless(TARGET == target, f"{target} plugin only")


def target_config() -> dict:
    import json

    return json.loads((PLUGIN / "adapter" / "target.json").read_text())


def target_config_src() -> dict:
    """The target's source settings (src/targets/<target>/target.json)."""
    import json

    return json.loads((REPO / "src" / "targets" / TARGET / "target.json").read_text())


MAX_PAGES = target_config()["hook_slots"]  # pages one session start delivers (Claude: one per hook slot)

if str(PLUGIN / "adapter") not in sys.path:
    sys.path.insert(0, str(PLUGIN / "adapter"))


def _engine() -> Path:
    """The pinned engine, installed once for the whole suite by the plugin's own provisioner (from PyPI, or from
    MINDSLICE_PLUGIN_WHEEL offline) into .cache/ at the repository root."""
    import json

    import provision

    spec = json.loads((PLUGIN / "adapter" / "target.json").read_text())["engine"]
    saved = os.environ.pop("MINDSLICE_PLUGIN_ENGINE_DIR", None)
    try:
        path = provision.ensure_engine(spec, REPO / ".cache" / "test-plugin-data")
    finally:
        if saved is not None:
            os.environ["MINDSLICE_PLUGIN_ENGINE_DIR"] = saved
    assert path is not None
    return path


ENGINE = _engine()
sys.path.insert(0, str(ENGINE))

# Variables that would point a test at the developer's real memory.
SCRUB = ("MINDSLICE_PLUGIN_WHEEL", "MINDSLICE_PLUGIN_PYTHON", "CLAUDE_PLUGIN_OPTION_PYTHON", "MINDSLICE_PLUGIN_OPTION_WORKSPACE", "CLAUDE_PLUGIN_ROOT", "MINDSLICE_WORKSPACE", "MINDSLICE_PLUGIN_WORKSPACE", "MINDSLICE_PLUGIN_ISOLATE", "CLAUDE_PLUGIN_OPTION_WORKSPACE",
         "CLAUDE_PLUGIN_DATA", "CLAUDE_ENV_FILE", "MINDSLICE_PLUGIN_STAGE_WRITES", "CLAUDE_PLUGIN_OPTION_STAGE_WRITES",
         "PLUGIN_DATA", "PLUGIN_ROOT", "MINDSLICE_PLUGIN_DATA", "ANTIGRAVITY_APP_DATA_DIR")


class PluginTestCase(unittest.TestCase):
    """A temporary plugin data dir and a clean environment per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self._env = dict(os.environ)
        for k in SCRUB:
            os.environ.pop(k, None)
        os.environ[DATA_ENV] = str(self.tmp / "data")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["MINDSLICE_PLUGIN_ENGINE_DIR"] = str(ENGINE)  # subprocesses: no download per test
        os.environ[ROOT_ENV] = str(PLUGIN)  # as the host sets it for hooks and the MCP server
        if not WINDOWS:  # the launchers run python3 from PATH: make that the interpreter under test
            pybin = self.tmp / "pybin"
            pybin.mkdir()
            (pybin / "python3").symlink_to(sys.executable)
            os.environ["PATH"] = f"{pybin}{os.pathsep}{os.environ.get('PATH', '')}"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def shim(self) -> list[str]:
        """How the agent's shell tool and a user's terminal run the plugin CLI. Claude and Codex: the launcher the
        hook writes to <plugin data>/bin. Antigravity: the plugin's own bin/ (mindslice.cmd from cmd/PowerShell on
        Windows)."""
        import core
        import driver

        d = core.write_launchers() if CLAUDE or CODEX else driver.launcher_dir()
        return [str(d / ("mindslice.cmd" if WINDOWS else "mindslice"))]

    def configure(self, workspace: Path | str | None) -> None:
        """Set the plugin's workspace option as the host passes it on. Claude gives it to hooks. Antigravity gives
        it only to the MCP server, which records it in the bridge file the hook reads: write that record too. Codex
        has no options: the plugin's settings file, which `mindslice plugin-config` writes."""
        if CODEX:
            import driver

            settings = driver.load_settings()
            if workspace is None:
                settings.pop("workspace", None)
            else:
                settings["workspace"] = str(workspace)
            driver.save_settings(settings)
            return
        if CLAUDE:
            if workspace is None:
                os.environ.pop("CLAUDE_PLUGIN_OPTION_WORKSPACE", None)
            else:
                os.environ["CLAUDE_PLUGIN_OPTION_WORKSPACE"] = str(workspace)
            return
        import core

        if workspace is None:
            os.environ.pop("MINDSLICE_PLUGIN_OPTION_WORKSPACE", None)
            core.bridge_path().unlink(missing_ok=True)
        else:
            os.environ["MINDSLICE_PLUGIN_OPTION_WORKSPACE"] = str(workspace)
            core.write_bridge(Path(os.path.abspath(core.expand_home(str(workspace)))))

    def hook(self, slot: int = 1, session: str = "s1", **kw) -> subprocess.CompletedProcess:
        """Run the session-start hook as the host does; ``stdout`` is the text of page ``slot`` ("" if none).
        Claude runs one process per slot. Antigravity and Codex run adapter/hook.py once and get every page as
        JSON: Antigravity one system message per page, Codex all pages in one additional context (``raw`` is what
        the hook printed, ``context`` that text, ``pages`` its pages)."""
        import json
        import re

        if CODEX:
            r = self.run_entry(stdin=json.dumps({"session_id": session, "source": "startup",
                                                 "hook_event_name": "SessionStart"}),
                               cmd=[sys.executable, str(PLUGIN / "adapter" / "hook.py")], **kw)
            r.raw, context = r.stdout, ""  # type: ignore[attr-defined]
            if r.stdout.strip():
                out = json.loads(r.stdout)["hookSpecificOutput"]
                assert out["hookEventName"] == "SessionStart", out
                context = out["additionalContext"]
            pages = re.split(r"\n\n(?=\[MindSlice standing memory · page \d+/\d+ · snapshot [0-9a-f]{8}\])", context)
            r.context, r.pages = context, [p for p in pages if p]  # type: ignore[attr-defined]
            r.stdout = r.pages[slot - 1] if slot <= len(r.pages) else ""
            return r
        if CLAUDE:
            return self.run_entry("hook", str(slot), stdin=json.dumps({"session_id": session, "source": "startup"}),
                                  **kw)
        r = self.run_entry(stdin=json.dumps({"conversationId": session, "hookEventName": "SessionStart"}),
                           cmd=[sys.executable, str(PLUGIN / "adapter" / "hook.py")], **kw)
        out = json.loads(r.stdout)
        pages = [s["systemMessage"]["systemMessage"] for s in out.get("injectSteps", [])]
        r.pages = pages  # type: ignore[attr-defined]
        r.stdout = pages[slot - 1] if slot <= len(pages) else ""
        return r

    def run_entry(self, *args: str, stdin: str = "", cwd: Path | None = None,
                  env: dict[str, str] | None = None, cmd: list[str] | None = None) -> subprocess.CompletedProcess:
        full_env = dict(os.environ, **(env or {}))
        return subprocess.run((cmd or [sys.executable, str(ENTRY)]) + list(args), input=stdin, capture_output=True,
                              text=True, encoding="utf-8", cwd=str(cwd or self.tmp), env=full_env, timeout=120)


def snapshot_files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def write_always(ws_root: Path, card_id: str, body: str, title: str | None = None, op: str = "create") -> None:
    from mindslice import Workspace

    with Workspace(ws_root) as ws:
        ws.write(card_id, op=op, content=body, summary=f"Standing card {card_id}.", title=title or card_id,
                 load="always", stage=False, reason="test")
