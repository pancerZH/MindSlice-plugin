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
from helpers import CLAUDE, DATA_ENV, ENTRY, MAX_PAGES, PLUGIN, ROOT_ENV, WINDOWS, PluginTestCase, only, snapshot_files, write_always

import shutil

import core

HEADER_RE = re.compile(r"^\[MindSlice standing memory · page (\d+)/(\d+) · snapshot ([0-9a-f]{8})\]")


class HookTest(PluginTestCase):
    @only("claude")
    def test_unconfigured(self) -> None:
        env_file = self.tmp / "env.sh"
        env_file.write_text("")
        r = self.hook(1, env={"CLAUDE_ENV_FILE": str(env_file)})
        self.assertEqual(r.returncode, 0)
        self.assertIn("no memory workspace configured", r.stdout)
        self.assertEqual(self.hook(2).stdout, "")
        # the command is still provided, so setup can run `mindslice plugin-status` to diagnose
        text = env_file.read_text()
        self.assertIn("export PATH=", text)
        self.assertNotIn("MINDSLICE_PLUGIN_WORKSPACE", text)
        self.assertTrue((core.plugin_data_dir() / "bin" / "mindslice").is_file())

    @only("claude")
    def test_leftover_bridge_does_not_count_as_configured(self) -> None:
        # uninstall clears the options but not the data dir: hooks must report "not configured", not old memory
        old = self.tmp / "old-ws"
        from mindslice import Workspace
        Workspace.init(old).close()
        core.write_bridge(old)
        r = self.hook(1)
        self.assertIn("no memory workspace configured", r.stdout)
        # a host whose hooks never see the options still uses the bridge
        from unittest import mock

        import driver
        with mock.patch.object(driver, "options_reach_hooks", False):
            self.assertEqual(core.resolve("hook").path, old)
        # the CLI keeps it as its last fallback (the user's own terminal has nothing else)
        self.assertEqual(core.resolve("cli").path, old)

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

    def make_partial_init(self, path: Path) -> None:
        """What Workspace.init has written just before it writes mounts.toml."""
        for sub in ("overlay", "staging", "slices", ".cache"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        (path / ".gitignore").write_text(".cache/\n")

    def test_initialization_in_progress_is_awaited(self) -> None:
        # the race seen on Windows: a hook slot is inside Workspace.init (overlay/ exists, mounts.toml not yet)
        # while the MCP server resolves the same folder; it must wait for the init lock, not refuse the folder
        import threading

        from mindslice import Workspace
        from mindslice.storage.locking import WorkspaceLock

        ws = self.tmp / "ws"
        ws.mkdir()
        started = threading.Event()

        def initializer() -> None:
            lock = WorkspaceLock(core.plugin_data_dir() / "init.lock", timeout=10)
            with lock.exclusive():
                self.make_partial_init(ws)
                started.set()
                time.sleep(0.5)
                Workspace.init(ws).close()
            lock.close()

        t = threading.Thread(target=initializer)
        t.start()
        started.wait(5)
        try:
            path = core.ensure_workspace(core.resolve("mcp", str(ws)))
        finally:
            t.join()
        self.assertEqual(path, ws)
        self.assertTrue((ws / "mounts.toml").is_file())

    def test_interrupted_initialization_is_finished(self) -> None:
        ws = self.tmp / "ws"
        self.make_partial_init(ws)
        (ws / ".cache" / "workspace.lock").write_text("")
        self.configure(ws)
        r = self.hook(1, session="partial")
        self.assertIn("standing memory complete", r.stdout)
        self.assertTrue((ws / "mounts.toml").is_file())

    def test_leftovers_plus_user_files_are_still_refused(self) -> None:
        ws = self.tmp / "ws"
        self.make_partial_init(ws)
        (ws / "overlay" / "mine.md").write_text("user note\n")
        before = snapshot_files(ws)
        self.configure(ws)
        self.assertIn("not empty and is not a MindSlice workspace", self.hook(1, session="mixed").stdout)
        self.assertEqual(snapshot_files(ws), before)
        (ws / "overlay" / "mine.md").unlink()
        (ws / ".gitignore").write_text("node_modules/\n")  # not the generated one
        self.assertEqual(core.classify(ws), core.OCCUPIED)

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
        cli = self.run_entry("status", cmd=self.shim())
        self.assertEqual(cli.returncode, 1)
        self.assertEqual(snapshot_files(occupied), before)
        # a plain file is refused the same way
        plain = self.tmp / "file.txt"
        plain.write_text("x")
        self.configure(plain)
        self.assertIn("not empty and is not a MindSlice workspace", self.hook(1, session="f").stdout)
        self.assertEqual(plain.read_text(), "x")

    @only("claude")
    def test_env_file_export(self) -> None:
        ws = self.tmp / "my ws"
        self.configure(ws)
        env_file = self.tmp / "env.sh"
        env_file.write_text("")
        self.hook(1, env={"CLAUDE_ENV_FILE": str(env_file)})
        self.hook(1, env={"CLAUDE_ENV_FILE": str(env_file)})
        import driver

        text = env_file.read_text()
        self.assertEqual(text, driver.env_lines(ws, driver.launcher_dir()))
        self.assertEqual(text.count("export MINDSLICE_PLUGIN_WORKSPACE="), 1)
        self.assertIn("export MINDSLICE_PLUGIN_DATA=", text)
        data_line = next(line for line in text.splitlines() if line.startswith("export MINDSLICE_PLUGIN_DATA="))
        self.assertNotIn("\\", data_line)  # forward slashes for Git Bash

    @only("claude")
    @unittest.skipIf(WINDOWS, "POSIX shell")
    def test_bash_tool_gets_mindslice_on_path(self) -> None:
        # what Claude does with the env file: run it as shell code before each Bash command (W4)
        ws = self.tmp / "ws"
        self.configure(ws)
        env_file = self.tmp / "env.sh"
        env_file.write_text("")
        self.hook(1, env={"CLAUDE_ENV_FILE": str(env_file)})
        launcher = core.plugin_data_dir() / "bin" / "mindslice"
        self.assertTrue(os.access(launcher, os.X_OK))
        project = self.tmp / "project"
        project.mkdir()
        bash_tool = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp), "MINDSLICE_PLUGIN_ENGINE_DIR": str(helpers.ENGINE)}
        script = f". {env_file}; . {env_file}; command -v mindslice; echo \"$PATH\"; mindslice --json status"
        r = subprocess.run(["sh", "-c", script], cwd=project, capture_output=True, text=True, env=bash_tool)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], str(launcher), r.stderr)
        self.assertEqual(lines[1].split(":").count(str(launcher.parent)), 1)  # added once, however often sourced
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(str(ws), r.stdout)  # the CLI used the plugin workspace

    @only("claude")
    def test_launcher_follows_the_installed_version(self) -> None:
        d = core.write_launchers()
        text = (d / "mindslice").read_text()
        self.assertIn((core.PLUGIN_ROOT / "adapter" / "entry.py").as_posix(), text)
        self.assertIn(Path(sys.executable).as_posix(), text)  # the interpreter the hook checked
        mtime = (d / "mindslice").stat().st_mtime_ns
        core.write_launchers()  # unchanged: not rewritten
        self.assertEqual((d / "mindslice").stat().st_mtime_ns, mtime)

    @only("claude")
    def test_path_entry_on_windows(self) -> None:
        from unittest import mock

        import driver

        with mock.patch.object(driver.os, "name", "nt"), mock.patch.object(driver.shutil, "which", return_value=None):
            self.assertEqual(driver.path_entry(Path("C:/Users/Wenzhe Zhang/.claude/plugins/data/x/bin")),
                             "/c/Users/Wenzhe Zhang/.claude/plugins/data/x/bin")

    @only("claude")
    @unittest.skipUnless(shutil.which("sh"), "no sh")
    def test_hook_through_the_sh_launcher(self) -> None:
        # exactly what hooks.json runs: sh <plugin>/adapter/hook-<slot>
        self.configure(self.tmp / "ws")
        r = self.run_entry(stdin=json.dumps({"session_id": "sh"}), cmd=["sh", str(PLUGIN / "adapter" / "hook-1")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("[MindSlice standing memory · page 1/1"), r.stdout[:200])

    @only("claude")
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
        cfg = helpers.target_config()
        for i in range(-(-cfg["hook_slots"] * cfg["page_limit"] // 8000) + 2):
            write_always(ws, f"big/b{i}", "- " + ("长规则 " * 2200))
        last = self.hook(MAX_PAGES, session="ovf")
        self.assertIn("# Standing memory overflow", last.stdout)
        status = self.run_entry("plugin-status", cmd=self.shim())
        self.assertEqual(status.returncode, 1)
        self.assertIn(f"pages but only {MAX_PAGES} are delivered", status.stdout)

    def test_status_warns_when_every_page_is_in_use(self) -> None:
        # cards are never split across pages, so pages run out long before the units do
        ws = self.tmp / "ws"
        self.configure(ws)
        core.ensure_workspace(core.resolve("hook"))
        cfg = helpers.target_config()
        body = "- " + "规" * int(cfg["page_limit"] * 0.55)  # one such card per page
        for i in range(cfg["hook_slots"]):
            write_always(ws, f"half/h{i}", body)
            if core.compute_delivery(ws, cfg["page_limit"], cfg["hook_slots"]).needed_pages == cfg["hook_slots"]:
                break
        report, code = core.status_report(str(ws))
        self.assertEqual((code, report["pages_needed"]), (0, cfg["hook_slots"]), report)
        self.assertLess(report["usage_percent"], 75)
        self.assertIn(f"fills all {cfg['hook_slots']} startup pages", " ".join(report["warnings"]))

    def test_plugin_status_after_global_options(self) -> None:
        ws = self.tmp / "plugin-status"  # a path that looks like the subcommand must not confuse routing
        from mindslice import Workspace
        Workspace.init(ws).close()
        r = self.run_entry("-w", str(ws), "plugin-status", "--json", cmd=self.shim())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["workspace"], str(ws))
        self.assertEqual(json.loads(self.run_entry("--workspace", str(ws), "plugin-status", "--json",
                                                   cmd=self.shim()).stdout)["workspace"], str(ws))

    def test_status_self_check_keeps_the_bridge(self) -> None:
        main_ws, other = self.tmp / "main", self.tmp / "other"
        from mindslice import Workspace
        for w in (main_ws, other):
            Workspace.init(w).close()
        core.write_bridge(main_ws)
        r = self.run_entry("plugin-status", "-w", str(other), cmd=self.shim())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(core.read_bridge(), str(main_ws))
        r = self.run_entry("plugin-status", "--json", cmd=self.shim(), env={"MINDSLICE_WORKSPACE": str(other)})
        self.assertEqual(json.loads(r.stdout)["workspace"], str(other))


class CliRoutingTest(PluginTestCase):
    @only("claude")
    def test_bash_tool_uses_the_exported_data_dir(self) -> None:
        # the Bash tool has no CLAUDE_PLUGIN_DATA, only what slot 1 exported
        ws = self.tmp / "ws"
        from mindslice import Workspace
        Workspace.init(ws).close()
        core.write_bridge(ws)  # into CLAUDE_PLUGIN_DATA (the test's data dir)
        data = os.environ.pop("CLAUDE_PLUGIN_DATA")
        project = self.tmp / "p2"
        project.mkdir()
        r = self.run_entry("write", "t/five", "--summary", "s", "--content", "- x", "--reason", "t", cmd=self.shim(),
                           cwd=project, env={"MINDSLICE_PLUGIN_DATA": data})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((ws / "overlay" / "t" / "five.md").is_file())

    def test_permission_error_is_one_line(self) -> None:
        # Antigravity's terminal sandbox denies reading the workspace: no traceback, and the driver's hint
        import contextlib
        import io
        from unittest import mock

        import driver

        denied = PermissionError(13, "Access is denied", str(self.tmp / "ws" / "mounts.toml"))
        for argv in (["status"], ["plugin-status"], ["-w", str(self.tmp), "plugin-status"]):
            err = io.StringIO()
            with mock.patch.object(core, "resolve", side_effect=denied), contextlib.redirect_stderr(err):
                self.assertEqual(core.main(argv), 1, argv)
            lines = err.getvalue().splitlines()
            self.assertIn("Access is denied", lines[0], argv)
            self.assertNotIn("Traceback", err.getvalue(), argv)
            hint = getattr(driver, "PERMISSION_HINT", None)
            self.assertEqual(lines[1:], [f"mindslice plugin: {hint}"] if hint else [], argv)

    def test_plugin_workspace_used_outside_workspaces(self) -> None:
        ws = self.tmp / "plugin-ws"
        self.configure(ws)
        project = self.tmp / "project"
        project.mkdir()
        r = self.run_entry("write", "t/one", "--summary", "s", "--content", "- x", "--reason", "t",
                           cmd=self.shim(), cwd=project)
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
                           cmd=self.shim(), cwd=sub, env={"MINDSLICE_PLUGIN_WORKSPACE": str(plugin_ws)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((local / "overlay" / "t" / "two.md").is_file())
        self.assertFalse(plugin_ws.exists())

    def test_explicit_workspace_and_env_pass_through(self) -> None:
        self.configure(self.tmp / "plugin-ws")
        other = self.tmp / "other"
        from mindslice import Workspace
        Workspace.init(other).close()
        r = self.run_entry("-w", str(other), "write", "t/three", "--summary", "s", "--content", "- x",
                           "--reason", "t", cmd=self.shim())
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
                           cmd=self.shim(), cwd=project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((ws / "overlay" / "t" / "four.md").is_file())

    def test_generated_launcher_needs_no_host_environment(self) -> None:
        # the Bash tool and the user's terminal: no CLAUDE_PLUGIN_ROOT, no CLAUDE_PLUGIN_DATA
        import driver

        d = core.write_launchers() if CLAUDE or helpers.CODEX else driver.launcher_dir()
        launcher = d / ("mindslice.cmd" if WINDOWS else "mindslice")
        env = {k: v for k, v in os.environ.items() if k not in (ROOT_ENV, DATA_ENV)}
        env["HOME"] = env["USERPROFILE"] = str(self.tmp)
        r = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mindslice 0.", r.stdout)


@only("claude")
class ShimTest(PluginTestCase):
    """adapter/hook-N and adapter/mcp: ${CLAUDE_PLUGIN_ROOT}/adapter/entry.py with fixed arguments and a fixed
    interpreter name (py, python3, python)."""

    def fake_python(self, name: str, marker: str) -> Path:
        d = self.tmp / f"bin-{name}"
        d.mkdir()
        exe = d / name
        exe.write_text(f'#!/bin/sh\nprintf "%s\\n" "{marker} $*"\n')
        exe.chmod(0o755)
        return exe

    def run_shim(self, path: str, name: str = "mcp", **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/sh", str(PLUGIN / "adapter" / name)], capture_output=True, text=True,
                              env=dict({"PATH": path, "CLAUDE_PLUGIN_ROOT": "/plugin/root"}, **env))

    @unittest.skipIf(WINDOWS, "POSIX shim behaviour")
    def test_order(self) -> None:
        py3 = self.fake_python("python3", "PY3")
        py = self.fake_python("python", "PY")
        launcher = self.fake_python("py", "LAUNCHER")
        self.assertEqual(self.run_shim(f"{py3.parent}:{py.parent}").stdout.strip(),
                         "PY3 /plugin/root/adapter/entry.py mcp")
        self.assertEqual(self.run_shim(str(py.parent), "hook-3").stdout.strip(),
                         "PY /plugin/root/adapter/entry.py hook 3")
        # py first (Windows: python3 is often the Store placeholder); a native py gets Claude's C:\... path as is
        out = self.run_shim(f"{py3.parent}:{launcher.parent}", CLAUDE_PLUGIN_ROOT="C:\\Users\\me\\m").stdout.strip()
        self.assertEqual(out, "LAUNCHER C:\\Users\\me\\m/adapter/entry.py mcp")
        r = self.run_shim(str(self.tmp / "nowhere"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("Python 3.12 or newer is required", r.stderr)

    def test_launchers_are_plain(self) -> None:
        # what the plugin directory's validator follows: no variable but CLAUDE_PLUGIN_ROOT, no substitution, no
        # pattern, literal ${CLAUDE_PLUGIN_ROOT}/<file> paths, fixed interpreter names and arguments
        import json as _json

        hooks = _json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]["SessionStart"][0]["hooks"]
        names = [f"hook-{i}" for i in range(1, len(hooks) + 1)] + ["mcp"]
        for name in names:
            sh = (PLUGIN / "adapter" / name).read_text()
            self.assertEqual([line for line in sh.splitlines() if line.startswith("#")], ["#!/bin/sh"], name)
            code = "\n".join(sh.splitlines()[1:])
            self.assertEqual(re.findall(r"\$\{?[A-Za-z_@*#?0-9!-]", code.replace("${CLAUDE_PLUGIN_ROOT}", "")), [], name)
            for bad in ("$(", "`", "*", "?", "[", "{", "<<", "eval", "/dev/", "install", ";\n"):
                self.assertNotIn(bad, code.replace("${CLAUDE_PLUGIN_ROOT}", ""), name)
            execs = re.findall(r"exec (\S+) (\S+)", code)
            self.assertEqual([e[0] for e in execs], ["py", "python3", "python"], name)
            self.assertEqual({e[1] for e in execs}, {'"${CLAUDE_PLUGIN_ROOT}/adapter/entry.py"'}, name)
        cmd = (PLUGIN / "adapter" / "mcp.cmd").read_text()
        runs = [line for line in cmd.splitlines() if "entry.py" in line and not line.lower().startswith("rem")]
        self.assertEqual([line.split()[0] for line in runs], ["py", "python"])
        self.assertTrue(all(line.endswith('"%CLAUDE_PLUGIN_ROOT%\\adapter\\entry.py" mcp') for line in runs), runs)
        # no %NAME% but CLAUDE_PLUGIN_ROOT, no path outside the plugin (nul), no comments
        self.assertEqual(re.findall(r"%[^%\s]*%?", cmd.replace("%CLAUDE_PLUGIN_ROOT%", "")), [])
        self.assertNotIn("nul", cmd.lower())
        self.assertFalse([line for line in cmd.splitlines() if line.lower().startswith(("rem", "::"))])


class WindowsLogicTest(PluginTestCase):
    def test_expand_home(self) -> None:
        os.environ["USERPROFILE" if WINDOWS else "HOME"] = str(self.tmp / "home")
        self.assertEqual(core.expand_home("~/mem"), str(self.tmp / "home") + "/mem")
        self.assertEqual(core.expand_home("~"), str(self.tmp / "home"))
        self.assertEqual(core.expand_home("~bob/mem"), "~bob/mem")
        self.assertEqual(core.expand_home("/abs/~/x"), "/abs/~/x")
        self.configure("~/mem")
        self.assertEqual(core.resolve("hook").path, Path(os.path.abspath(str(self.tmp / "home") + "/mem")))

    def test_parse_py_list(self) -> None:
        import entry

        sample = (" -V:3.13 *        C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python313\\python.exe\n"
                  " -V:3.12          C:\\Program Files\\Python312\\python.exe\n"
                  " -3.11-64         C:\\Python311\\python.exe\n"
                  "Installed Pythons found by py Launcher for Windows\n")
        self.assertEqual(entry.parse_py_list(sample), [
            "C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python313\\python.exe",
            "C:\\Program Files\\Python312\\python.exe", "C:\\Python311\\python.exe"])

    def test_pending_block_names_the_terminal_shim(self) -> None:
        self.assertEqual(core.bin_path().name, "mindslice.cmd" if WINDOWS else "mindslice")


class IsolationTest(PluginTestCase):
    def test_isolated(self) -> None:
        ws = self.tmp / "ws"
        self.configure(ws)
        env = {"MINDSLICE_PLUGIN_ISOLATE": "1"}
        env_file = self.tmp / "env.sh"
        env_file.write_text("")
        hook = self.hook(1, env=dict(env, CLAUDE_ENV_FILE=str(env_file)))
        self.assertEqual((hook.returncode, hook.stdout), (0, ""))
        if CLAUDE:
            self.assertIn("export PATH=", env_file.read_text())  # Forge still calls `mindslice -w ...`
            self.assertNotIn("MINDSLICE_PLUGIN_WORKSPACE", env_file.read_text())
        elif helpers.CODEX:
            self.assertEqual(hook.raw, "")  # nothing for Codex to add
        else:
            self.assertEqual(hook.pages, [])
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        mcp = self.run_entry("mcp", "--workspace", str(ws), stdin="".join(json.dumps(r) + "\n" for r in reqs), env=env)
        out = [json.loads(line) for line in mcp.stdout.splitlines()]
        self.assertEqual(out[0]["result"]["instructions"], "")
        self.assertEqual(out[1]["result"]["tools"], [])
        project = self.tmp / "project"
        project.mkdir()
        cli = self.run_entry("status", cmd=self.shim(), cwd=project, env=env)
        self.assertNotEqual(cli.returncode, 0)  # no fallback to the personal workspace
        self.assertFalse(ws.exists())


if __name__ == "__main__":
    unittest.main()
