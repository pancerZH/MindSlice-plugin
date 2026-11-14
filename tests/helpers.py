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
BIN = PLUGIN / "adapter" / "mindslice"  # the sh launcher (hooks.json runs it; the Bash tool reaches it via PATH)
WINDOWS = os.name == "nt"
# How a user's terminal runs the plugin CLI: the sh shim, or mindslice.cmd from cmd/PowerShell on Windows.
SHIM = [str(PLUGIN / "adapter" / "mindslice.cmd")] if WINDOWS else [str(BIN)]

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
         "CLAUDE_PLUGIN_DATA", "CLAUDE_ENV_FILE", "MINDSLICE_PLUGIN_STAGE_WRITES", "CLAUDE_PLUGIN_OPTION_STAGE_WRITES")


class PluginTestCase(unittest.TestCase):
    """A temporary plugin data dir and a clean environment per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self._env = dict(os.environ)
        for k in SCRUB:
            os.environ.pop(k, None)
        os.environ["CLAUDE_PLUGIN_DATA"] = str(self.tmp / "data")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["MINDSLICE_PLUGIN_ENGINE_DIR"] = str(ENGINE)  # subprocesses: no download per test
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)  # as Claude sets it for hooks and the MCP server
        if not WINDOWS:  # the launchers run python3 from PATH: make that the interpreter under test
            pybin = self.tmp / "pybin"
            pybin.mkdir()
            (pybin / "python3").symlink_to(sys.executable)
            os.environ["PATH"] = f"{pybin}{os.pathsep}{os.environ.get('PATH', '')}"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def configure(self, workspace: Path | str | None) -> None:
        if workspace is None:
            os.environ.pop("CLAUDE_PLUGIN_OPTION_WORKSPACE", None)
        else:
            os.environ["CLAUDE_PLUGIN_OPTION_WORKSPACE"] = str(workspace)

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
