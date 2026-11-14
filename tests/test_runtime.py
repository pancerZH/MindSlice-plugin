"""Hooks, spool, workspace guard, CLI routing and isolation (PLAN 4.3, 4.5, 4.6, 8)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import helpers
from helpers import BIN, ENTRY, PluginTestCase, snapshot_files, write_always

import core

HEADER_RE = re.compile(r"^\[MindSlice standing memory · page (\d+)/(\d+) · snapshot ([0-9a-f]{8})\]")


class HookTest(PluginTestCase):
    def hook(self, slot: int, session: str = "s1", **kw) -> subprocess.CompletedProcess:
        return self.run_entry("hook", str(slot), stdin=json.dumps({"session_id": session, "source": "startup"}), **kw)

    def test_unconfigured(self) -> None:
        r = self.hook(1)
        self.assertEqual(r.returncode, 0)
        self.assertIn("no memory workspace configured", r.stdout)
        self.assertEqual(self.hook(2).stdout, "")

    def test_missing_and_empty_are_initialized(self) -> None:
        for path in (self.tmp / "new" / "ws", self.tmp / "empty"):
            if path.name == "empty":
                path.mkdir()
            self.configure(path)
            r = self.hook(1, session=path.name)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((path / "mounts.toml").is_file())
            self.assertIn("# Empty memory workspace", r.stdout)
            self.assertIn("standing memory complete · 1 pages · 0 cards", r.stdout)

    def test_occupied_directory_untouched(self) -> None:
        occupied = self.tmp / "notes"
        occupied.mkdir()
        (occupied / "todo.md").write_text("mine\n")
        before = snapshot_files(occupied)
        self.configure(occupied)
        r = self.hook(1)
        self.assertIn("not empty and is not a MindSlice workspace", r.stdout)
        self.assertNotIn("mindslice init", r.stdout)
        mcp = self.run_entry("mcp", "--workspace", str(occupied), stdin="")
        self.assertEqual(mcp.returncode, 1)
        self.assertIn("not empty and is not a MindSlice workspace", mcp.stderr)
        self.assertNotIn("mindslice init", mcp.stderr)
        cli = self.run_entry("status", cmd=[str(BIN)])
        self.assertEqual(cli.returncode, 1)
        self.assertEqual(snapshot_files(occupied), before)
        # a plain file is refused the same way
        plain = self.tmp / "file.txt"
        plain.write_text("x")
        self.configure(plain)
        self.assertIn("not empty and is not a MindSlice workspace", self.hook(1, session="f").stdout)
        self.assertEqual(plain.read_text(), "x")

    def test_env_file_export(self) -> None:
        ws = self.tmp / "my ws"
        self.configure(ws)
        env_file = self.tmp / "env.sh"
        env_file.write_text("")
        self.hook(1, env={"CLAUDE_ENV_FILE": str(env_file)})
        self.hook(1, env={"CLAUDE_ENV_FILE": str(env_file)})
        self.assertEqual(env_file.read_text(), f"export MINDSLICE_PLUGIN_WORKSPACE='{ws}'\n")

    def test_concurrent_slots_share_a_snapshot_and_refresh(self) -> None:
        ws = self.tmp / "ws"
        self.configure(ws)
        core.ensure_workspace(core.resolve("hook"))
        for i in range(8):
            write_always(ws, f"rules/r{i}", "- " + ("规则内容 " * 900))
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda s: self.hook(s, session="race"), range(1, 5)))
        ids = set()
        for slot, r in enumerate(results, 1):
            self.assertEqual(r.returncode, 0, r.stderr)
            m = HEADER_RE.match(r.stdout)
            self.assertIsNotNone(m, f"slot {slot}: {r.stdout[:200]!r}")
            self.assertEqual(int(m.group(1)), slot)
            ids.add(m.group(3))
        self.assertEqual(len(ids), 1)
        old = ids.pop()
        # change a standing card and fire again at once (a quick /compact): the cache must not serve old pages
        write_always(ws, "rules/r0", "- NEWPHRASE-7731 " + ("规则内容 " * 900), op="replace")
        start = time.monotonic()
        again = [self.hook(s, session="race") for s in range(1, 5)]
        self.assertLess(time.monotonic() - start, 30)
        new_ids = {HEADER_RE.match(r.stdout).group(3) for r in again}
        self.assertEqual(len(new_ids), 1)
        self.assertNotEqual(new_ids.pop(), old)
        self.assertTrue(any("NEWPHRASE-7731" in r.stdout for r in again))

    def test_overflow_reaches_last_slot(self) -> None:
        ws = self.tmp / "ws"
        self.configure(ws)
        core.ensure_workspace(core.resolve("hook"))
        for i in range(12):
            write_always(ws, f"big/b{i}", "- " + ("长规则 " * 2200))
        last = self.hook(4, session="ovf")
        self.assertIn("# Standing memory overflow", last.stdout)
        status = self.run_entry("plugin-status", cmd=[str(BIN)])
        self.assertEqual(status.returncode, 1)
        self.assertIn("pages but only 4 are delivered", status.stdout)

    def test_status_self_check_keeps_the_bridge(self) -> None:
        main_ws, other = self.tmp / "main", self.tmp / "other"
        from mindslice import Workspace
        for w in (main_ws, other):
            Workspace.init(w).close()
        core.write_bridge(main_ws)
        r = self.run_entry("plugin-status", "-w", str(other), cmd=[str(BIN)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(core.read_bridge(), str(main_ws))
        r = self.run_entry("plugin-status", "--json", cmd=[str(BIN)], env={"MINDSLICE_WORKSPACE": str(other)})
        self.assertEqual(json.loads(r.stdout)["workspace"], str(other))


class CliRoutingTest(PluginTestCase):
    def test_plugin_workspace_used_outside_workspaces(self) -> None:
        ws = self.tmp / "plugin-ws"
        self.configure(ws)
        project = self.tmp / "project"
        project.mkdir()
        r = self.run_entry("write", "t/one", "--summary", "s", "--content", "- x", "--reason", "t",
                           cmd=[str(BIN)], cwd=project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((ws / "overlay" / "t" / "one.md").is_file())

    def test_local_workspace_wins(self) -> None:
        plugin_ws = self.tmp / "plugin-ws"
        self.configure(plugin_ws)
        local = self.tmp / "local"
        from mindslice import Workspace
        Workspace.init(local).close()
        sub = local / "overlay"
        r = self.run_entry("write", "t/two", "--summary", "s", "--content", "- x", "--reason", "t",
                           cmd=[str(BIN)], cwd=sub, env={"MINDSLICE_PLUGIN_WORKSPACE": str(plugin_ws)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((local / "overlay" / "t" / "two.md").is_file())
        self.assertFalse(plugin_ws.exists())

    def test_explicit_workspace_and_env_pass_through(self) -> None:
        self.configure(self.tmp / "plugin-ws")
        other = self.tmp / "other"
        from mindslice import Workspace
        Workspace.init(other).close()
        r = self.run_entry("-w", str(other), "write", "t/three", "--summary", "s", "--content", "- x",
                           "--reason", "t", cmd=[str(BIN)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((other / "overlay" / "t" / "three.md").is_file())
        self.assertFalse((self.tmp / "plugin-ws").exists())
        self.assertIsNone(core.cli_workspace_for(["--help"]))
        self.assertIsNone(core.cli_workspace_for(["init", "x"]))
        self.assertIsNone(core.cli_workspace_for(["status", "--workspace=/x"]))

    def test_bridge_file_fallback(self) -> None:
        ws = self.tmp / "bridged"
        from mindslice import Workspace
        Workspace.init(ws).close()
        core.write_bridge(ws)
        project = self.tmp / "p"
        project.mkdir()
        r = self.run_entry("write", "t/four", "--summary", "s", "--content", "- x", "--reason", "t",
                           cmd=[str(BIN)], cwd=project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((ws / "overlay" / "t" / "four.md").is_file())

    def test_symlinked_shim(self) -> None:
        link = self.tmp / "bin" / "mindslice"
        link.parent.mkdir()
        link.symlink_to(BIN)
        r = self.run_entry("--version", cmd=[str(link)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mindslice 0.", r.stdout)


class IsolationTest(PluginTestCase):
    def test_isolated(self) -> None:
        ws = self.tmp / "ws"
        self.configure(ws)
        env = {"MINDSLICE_PLUGIN_ISOLATE": "1"}
        hook = self.run_entry("hook", "1", stdin="{}", env=env)
        self.assertEqual((hook.returncode, hook.stdout), (0, ""))
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        mcp = self.run_entry("mcp", "--workspace", str(ws), stdin="".join(json.dumps(r) + "\n" for r in reqs), env=env)
        out = [json.loads(line) for line in mcp.stdout.splitlines()]
        self.assertEqual(out[0]["result"]["instructions"], "")
        self.assertEqual(out[1]["result"]["tools"], [])
        project = self.tmp / "project"
        project.mkdir()
        cli = self.run_entry("status", cmd=[str(BIN)], cwd=project, env=env)
        self.assertNotEqual(cli.returncode, 0)  # no fallback to the personal workspace
        self.assertFalse(ws.exists())


if __name__ == "__main__":
    unittest.main()
