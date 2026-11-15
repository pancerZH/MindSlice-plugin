"""Antigravity target: layout, hook JSON, byte limit, bridge timing, data dir, launchers (PLAN section 12).

Runs when the suite targets Antigravity: ``MINDSLICE_PLUGIN_TARGET=antigravity python3 -m unittest ...``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

import helpers
from helpers import PLUGIN, REPO, WINDOWS, PluginTestCase, only, snapshot_files, write_always

import core
from mindslice import Workspace

LOCK = json.loads((REPO / "build" / "upstream.lock").read_text())


def load(path: str) -> dict:
    return json.loads((PLUGIN / path).read_text(encoding="utf-8"))


@only("antigravity")
class LayoutTest(unittest.TestCase):
    def test_root_files(self) -> None:
        # Antigravity loads hooks.json, mcp_config.json and rules/ only from the plugin root
        for f in ("plugin.json", "mcp_config.json", "hooks.json", "rules/AGENTS.md", "bin/mindslice",
                  "bin/mindslice.cmd", "adapter/hook.py", "README.md"):
            self.assertTrue((PLUGIN / f).is_file(), f)
        self.assertFalse((PLUGIN / "hooks").exists())
        self.assertFalse((PLUGIN / ".claude-plugin").exists())

    def test_manifest(self) -> None:
        manifest = load("plugin.json")
        # unknown top-level fields are dropped silently by Antigravity's loader
        allowed = {"name", "description", "logo", "suggestedPrompts", "displayName", "version", "author", "homepage",
                   "repository", "disabled"}
        self.assertLessEqual(set(manifest), allowed)
        self.assertEqual(manifest["name"], "mindslice")
        self.assertTrue(manifest["version"].startswith(LOCK["version"] + "-"))
        self.assertLessEqual(len(manifest["suggestedPrompts"]), 3)
        self.assertTrue((PLUGIN / manifest["logo"]).is_file())

    def test_mcp_config(self) -> None:
        server = load("mcp_config.json")["mcpServers"]["mindslice"]
        # ${PLUGIN_ROOT} is not expanded in "command": a relative command run in the plugin folder
        self.assertEqual(server["command"], "./adapter/mcp")
        self.assertEqual(server["cwd"], "${PLUGIN_ROOT}")
        names = [v["name"] for v in server["variables"]]
        self.assertEqual(names, ["workspace", "stage_writes"])
        placeholders = set(re.findall(r"\$\{([A-Za-z_]+)\}", json.dumps(server["env"])))
        self.assertEqual(placeholders, set(names))  # every placeholder declared, so it is substituted
        self.assertEqual(server["env"]["MINDSLICE_PLUGIN_OPTION_WORKSPACE"], "${workspace}")

    def test_hooks_json(self) -> None:
        hooks = load("hooks.json")
        self.assertEqual(list(hooks), ["mindslice"])
        (handler,) = hooks["mindslice"]["SessionStart"]  # flat list of handlers for SessionStart
        self.assertEqual(handler["command"], "py adapter/hook.py || python3 adapter/hook.py || python adapter/hook.py")
        self.assertNotIn("PLUGIN_ROOT", handler["command"])  # hooks run in the plugin folder
        self.assertGreater(handler["timeout"], 30)

    def test_line_endings_and_modes(self) -> None:
        for f in ("adapter/mcp.cmd", "bin/mindslice.cmd"):
            data = (PLUGIN / f).read_bytes()
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), f"{f} must be CRLF")
        for f in ("adapter/mcp", "bin/mindslice", "adapter/hook.py"):
            self.assertNotIn(b"\r", (PLUGIN / f).read_bytes(), f)
        if not WINDOWS:
            for f in ("adapter/mcp", "bin/mindslice"):
                self.assertTrue(os.access(PLUGIN / f, os.X_OK), f)

    def test_page_limit_fits_the_byte_cap(self) -> None:
        import driver

        cfg = helpers.target_config()
        # UTF-8 never needs more than 3 bytes per UTF-16 unit; agy's wrapper adds about 230 bytes
        self.assertLessEqual(cfg["page_limit"] * 3, driver.HOOK_BYTE_LIMIT)
        self.assertLessEqual(driver.HOOK_BYTE_LIMIT + 300, 49152)
        self.assertFalse(driver.reinjects_on_compact)
        self.assertFalse(driver.options_reach_hooks)

    def test_agy_validate(self) -> None:
        agy = shutil.which("agy")
        if not agy:
            self.skipTest("agy not installed")
        r = subprocess.run([agy, "plugin", "validate", str(PLUGIN), "--strict"], capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@only("antigravity")
class HookTest(PluginTestCase):
    def test_hook_command_as_agy_runs_it(self) -> None:
        # exactly what hooks.json runs, through the shell (sh -c on Unix, cmd /c on Windows), in the plugin folder
        ws = self.tmp / "ws"
        self.configure(ws)
        command = load("hooks.json")["mindslice"]["SessionStart"][0]["command"]
        shell = ["cmd", "/c", command] if WINDOWS else ["sh", "-c", command]
        r = subprocess.run(shell, cwd=PLUGIN, input=json.dumps({"conversationId": "c1"}),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        page = out["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertTrue(page.startswith("[MindSlice standing memory · page 1/1"), page[:200])
        self.assertIn("standing memory complete", page)

    def test_every_page_fits_in_bytes(self) -> None:
        ws = self.tmp / "ws"
        self.configure(ws)
        core.ensure_workspace(core.resolve("hook"))
        write_always(ws, "big/cjk", "- " + "中文规则内容测试。" * 4000)  # 3 bytes per unit, no newlines
        write_always(ws, "big/astral", "- " + "😀🎉" * 6000)  # 4 bytes per 2 units
        r = self.hook(1, session="bytes")
        self.assertGreater(len(r.pages), 3)
        for page in r.pages:
            self.assertLessEqual(len(page.encode("utf-8")), 48000)
        self.assertIn("standing memory complete", r.pages[-1])
        self.assertEqual(len({re.search(r"snapshot (\w+)", p).group(1) for p in r.pages}), 1)

    def test_oversized_page_becomes_a_fault_notice(self) -> None:
        import driver

        out = driver.inject(["x" * 10, "é" * 30000])
        texts = [s["systemMessage"]["systemMessage"] for s in out["injectSteps"]]
        self.assertEqual(texts[0], "x" * 10)
        self.assertIn("could not be delivered safely", texts[1])
        self.assertEqual(driver.inject([]), {})

    def test_waits_for_the_first_bridge(self) -> None:
        # the first conversation: the MCP server writes the bridge while the hook is already running
        ws = self.tmp / "ws"
        Workspace.init(ws).close()

        def later() -> None:
            time.sleep(1.0)
            core.write_bridge(ws)

        t = threading.Thread(target=later)
        t.start()
        try:
            r = self.hook(1, session="late")
        finally:
            t.join()
        self.assertIn(str(ws), r.stdout)
        self.assertIn("standing memory complete", r.stdout)

    def test_unconfigured_after_the_wait(self) -> None:
        start = time.monotonic()
        r = self.hook(1, session="none")
        self.assertGreaterEqual(time.monotonic() - start, 4.5)
        self.assertIn("no memory workspace configured", r.stdout)
        self.assertIn("include_always=true", r.stdout)  # recovery hint when MCP starts slower than the hook
        self.assertEqual(len(r.pages), 1)

    def test_unconfigured_mcp_clears_leftover_bridge(self) -> None:
        # uninstall clears config.json but leaves plugin_data: an unconfigured MCP start must drop the old bridge
        old = self.tmp / "old"
        Workspace.init(old).close()
        write_always(old, "prefs/p", "- OLD-PHRASE-2")
        core.write_bridge(old)
        mcp = self.run_entry("mcp", stdin="", env={"MINDSLICE_PLUGIN_OPTION_WORKSPACE": "${workspace}"})
        self.assertEqual(mcp.returncode, 1)
        self.assertIsNone(core.read_bridge())
        self.assertFalse(core.bridge_path().exists())

    def test_relative_and_plugin_dir_workspaces_refused(self) -> None:
        # MCP runs with cwd=PLUGIN_ROOT: a relative path or a path inside the plugin folder would put memory where
        # plugin updates wipe it
        old = self.tmp / "old"
        Workspace.init(old).close()
        core.write_bridge(old)
        plugin_before = snapshot_files(PLUGIN)
        for bad, expected in (("mindslice-rel", "relative path"),
                              ("$HOME/mindslice", "unexpanded shell variable"),
                              (str(PLUGIN / "my-memory"), "inside the plugin installation folder"),
                              (str(core.plugin_data_dir() / "my-memory"), "internal data folder")):
            mcp = self.run_entry("mcp", stdin="", cwd=PLUGIN, env={"MINDSLICE_PLUGIN_OPTION_WORKSPACE": bad})
            self.assertEqual(mcp.returncode, 1, bad)
            self.assertIn(expected, mcp.stderr, bad)
            self.assertIsNone(core.read_bridge(), bad)
            start = time.monotonic()
            r = self.hook(1, session="bad")
            self.assertLess(time.monotonic() - start, 3.0)  # invalid bridge error stops _await_bridge immediately
            self.assertIn(expected, r.stdout, bad)
        self.assertEqual(snapshot_files(PLUGIN), plugin_before)

    def test_invalid_setting_does_not_fall_through_to_env(self) -> None:
        # an invalid setting must fail the server, not silently serve (and record) MINDSLICE_WORKSPACE instead
        other = self.tmp / "other"
        Workspace.init(other).close()
        mcp = self.run_entry("mcp", stdin="", cwd=PLUGIN,
                             env={"MINDSLICE_PLUGIN_OPTION_WORKSPACE": "rel-path", "MINDSLICE_WORKSPACE": str(other)})
        self.assertEqual(mcp.returncode, 1)
        self.assertIn("relative path", mcp.stderr)
        self.assertEqual(mcp.stderr.count("relative path"), 1)  # reported once
        self.assertIsNone(core.read_bridge())

    def test_stale_bridge_error_waits_for_the_new_server(self) -> None:
        # an error recorded by an earlier conversation's server must not end the wait: the user may have fixed the
        # setting, and this conversation's server replaces the bridge a moment after the hook starts
        import driver

        ws = self.tmp / "ws"
        Workspace.init(ws).close()
        write_always(ws, "prefs/p", "- FIXED-PHRASE-3")
        core.atomic_write(core.bridge_path(), json.dumps({"invalid_workspace": "rel", "error": "OLD-ERROR"}) + "\n")
        stamp = time.time() - driver.FRESH_ERROR - 60
        os.utime(core.bridge_path(), (stamp, stamp))
        timer = threading.Timer(1.0, core.write_bridge, args=(ws,))
        timer.start()
        try:
            r = self.hook(1, session="stale")
        finally:
            timer.join()
        self.assertIn("FIXED-PHRASE-3", r.stdout)
        self.assertNotIn("OLD-ERROR", r.stdout)
        # still stale and nothing replaces it: the hook waits it out, then reports it with the recovery hint
        core.atomic_write(core.bridge_path(), json.dumps({"invalid_workspace": "rel", "error": "OLD-ERROR"}) + "\n")
        os.utime(core.bridge_path(), (stamp, stamp))
        start = time.monotonic()
        r = self.hook(1, session="stale2")
        self.assertGreaterEqual(time.monotonic() - start, 4.5)
        self.assertIn("OLD-ERROR", r.stdout)
        self.assertIn("include_always=true", r.stdout)

    def test_refused_setting_replaces_an_older_bridge(self) -> None:
        # the user points the setting at a folder with other files: the MCP server refuses it and exits, and the
        # next conversation must report that folder instead of delivering the workspace named before
        old = self.tmp / "old"
        Workspace.init(old).close()
        write_always(old, "prefs/p", "- OLD-PHRASE-1")
        core.write_bridge(old)
        notes = self.tmp / "notes"
        notes.mkdir()
        (notes / "todo.md").write_text("mine\n")
        before = snapshot_files(notes)
        mcp = self.run_entry("mcp", stdin="", env={"MINDSLICE_PLUGIN_OPTION_WORKSPACE": str(notes)})
        self.assertEqual(mcp.returncode, 1)
        self.assertEqual(core.read_bridge(), str(notes))
        r = self.hook(1, session="refused")
        self.assertIn("not empty and is not a MindSlice workspace", r.stdout)
        self.assertNotIn("OLD-PHRASE-1", r.stdout)
        self.assertEqual(snapshot_files(notes), before)

    def test_plain_text_failure_becomes_a_system_message(self) -> None:
        # entry.py reports a failure before any driver code runs (here: no engine, offline) in plain text
        os.environ.pop("MINDSLICE_PLUGIN_ENGINE_DIR")
        pinned = LOCK["version"]
        probe = subprocess.run([sys.executable, "-c", "import importlib.metadata as m; print(m.version('mindslice'))"],
                               capture_output=True, text=True)
        if probe.stdout.strip() == pinned:
            self.skipTest(f"mindslice {pinned} is installed for this interpreter")
        r = self.hook(1, env={"MINDSLICE_PLUGIN_WHEEL": str(self.tmp / "nope.whl"), "PYTHONNOUSERSITE": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.pages), 1)
        self.assertIn("[MindSlice plugin could not start]", r.stdout)

    def test_stderr_only_crash_becomes_a_system_message(self) -> None:
        # an unhandled crash (empty stdout, traceback on stderr, non-zero exit) is still surfaced to the model
        os.environ.pop("PLUGIN_DATA", None)
        r = self.hook(1, env={"HOME": "", "USERPROFILE": "", "ANTIGRAVITY_APP_DATA_DIR": "",
                              "MINDSLICE_PLUGIN_DATA": ""})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.pages), 1)
        self.assertIn("[MindSlice plugin could not start]", r.stdout)
        self.assertIn("no plugin data directory", r.stdout)


@only("antigravity")
class ManifestTest(PluginTestCase):
    def test_mcp_as_mcp_config_starts_it(self) -> None:
        # command ./adapter/mcp in cwd ${PLUGIN_ROOT}, the variables in the environment
        server = load("mcp_config.json")["mcpServers"]["mindslice"]
        root = self.tmp / "ws"
        Workspace.init(root).close()
        env = {k: v.replace("${workspace}", str(root)).replace("${stage_writes}", "false")
               for k, v in server["env"].items()}
        command = server["command"] + (".cmd" if WINDOWS else "")
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        r = self.run_entry(*server.get("args", []), stdin=json.dumps(req) + "\n", env=env,
                           cwd=Path(server["cwd"].replace("${PLUGIN_ROOT}", str(PLUGIN))),
                           cmd=[str(PLUGIN / command) if WINDOWS else command])
        self.assertEqual(r.returncode, 0, r.stderr)
        init = json.loads(r.stdout.splitlines()[0])["result"]
        self.assertEqual(init["instructions"], core.SHORT_INSTRUCTIONS)
        self.assertEqual(core.read_bridge(), str(root))

    def test_engine_text_keeps_the_compaction_rule(self) -> None:
        self.assertIn("call manifest() again before continuing", core.plugin_instructions())
        manifest = next(t for t in core.plugin_tools() if t["name"] == "manifest")
        self.assertIn("after the conversation is compacted", manifest["description"])

    def test_stage_writes_setting(self) -> None:
        import driver

        for value, expected in (("true", True), ("TRUE", True), ("false", False), ("", False), ("${stage_writes}", False)):
            os.environ["MINDSLICE_PLUGIN_STAGE_WRITES"] = value
            self.assertEqual(driver.stage_writes_enabled(), expected, value)
            self.assertEqual(driver.startup_notes(), [])
        # a typo fails closed (stages writes) and records a startup warning until corrected
        os.environ["MINDSLICE_PLUGIN_STAGE_WRITES"] = "ture"
        self.assertTrue(driver.stage_writes_enabled())
        self.assertTrue(any("ture" in n for n in driver.startup_notes()))
        os.environ["MINDSLICE_PLUGIN_STAGE_WRITES"] = "false"
        self.assertFalse(driver.stage_writes_enabled())
        self.assertEqual(driver.startup_notes(), [])


@only("antigravity")
class DataDirTest(PluginTestCase):
    def test_terminal_tool_uses_the_app_data_dir(self) -> None:
        # run_command has ANTIGRAVITY_APP_DATA_DIR but no PLUGIN_DATA; its plugin_data/<folder> is the same dir
        app = self.tmp / "app"
        data = app / "plugin_data" / PLUGIN.name
        ws = self.tmp / "ws"
        Workspace.init(ws).close()
        os.environ["PLUGIN_DATA"] = str(data)
        core.write_bridge(ws)
        del os.environ["PLUGIN_DATA"]
        project = self.tmp / "project"
        project.mkdir()
        r = self.run_entry("write", "t/one", "--summary", "s", "--content", "- x", "--reason", "t", cmd=self.shim(),
                           cwd=project, env={"ANTIGRAVITY_APP_DATA_DIR": str(app)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((ws / "overlay" / "t" / "one.md").is_file())

    def test_own_terminal_finds_the_newest_bridge(self) -> None:
        import driver

        del os.environ["PLUGIN_DATA"]
        home = self.tmp / "home"
        os.environ["USERPROFILE" if WINDOWS else "HOME"] = str(home)
        self.assertEqual(driver.plugin_data_dir(), home / ".cache" / "mindslice-plugin" / "antigravity")
        older = home / ".gemini" / "antigravity" / "plugin_data" / PLUGIN.name
        newer = home / ".gemini" / "antigravity-cli" / "plugin_data" / PLUGIN.name
        for d, stamp in ((older, 1_000_000), (newer, 2_000_000)):
            d.mkdir(parents=True)
            (d / "active_workspace.json").write_text('{"workspace": "/x"}\n')
            os.utime(d / "active_workspace.json", (stamp, stamp))
        self.assertEqual(driver.plugin_data_dir(), newer)

    def test_workspace_plugin_and_mindslice_fallback_data_dir(self) -> None:
        import driver

        del os.environ["PLUGIN_DATA"]
        home = self.tmp / "home"
        app = self.tmp / "app"
        os.environ["USERPROFILE" if WINDOWS else "HOME"] = str(home)
        os.environ["ANTIGRAVITY_APP_DATA_DIR"] = str(app)
        # workspace plugin (.agents/plugins/...): MCP/hook wrote to ~/.cache, app/plugin_data/<dir> does not exist
        cache = home / ".cache" / "mindslice-plugin" / "antigravity"
        cache.mkdir(parents=True)
        (cache / "active_workspace.json").write_text('{"workspace": "/ws"}\n')
        self.assertEqual(driver.plugin_data_dir(), cache)
        # installed under "mindslice" while symlinked to plugins/antigravity: app/plugin_data/mindslice wins
        installed = app / "plugin_data" / "mindslice"
        installed.mkdir(parents=True)
        self.assertEqual(driver.plugin_data_dir(), installed)
        # two app data dirs (an old install folder name and the current one): the newest bridge wins, not name order
        names = driver._dir_names()
        dirs = [app / "plugin_data" / n for n in names]
        for i, d in enumerate(dirs):
            d.mkdir(parents=True, exist_ok=True)
            (d / "active_workspace.json").write_text('{"workspace": "/ws"}\n')
            stamp = time.time() - 100 * (len(dirs) - i)  # last name in the list is the newest
            os.utime(d / "active_workspace.json", (stamp, stamp))
        self.assertEqual(driver.plugin_data_dir(), dirs[-1])


@only("antigravity")
class LauncherTest(PluginTestCase):
    def fake_python(self, name: str, marker: str) -> Path:
        d = self.tmp / f"bin-{name}"
        d.mkdir()
        exe = d / name
        exe.write_text(f'#!/bin/sh\nprintf "%s\\n" "{marker} $*"\n')
        exe.chmod(0o755)
        return exe

    @unittest.skipIf(WINDOWS, "POSIX launchers")
    def test_order_and_paths(self) -> None:
        launcher = self.fake_python("py", "LAUNCHER")
        py3 = self.fake_python("python3", "PY3")
        py = self.fake_python("python", "PY")
        tools = self.tmp / "tools"  # what the launcher needs besides a Python, and no real python3
        tools.mkdir()
        for name in ("dirname", "readlink"):
            (tools / name).symlink_to(shutil.which(name))
        # outside Windows a `py` on PATH is never used (it may be pythonpy, and exec leaves no fallback)
        first = subprocess.run([str(PLUGIN / "adapter" / "mcp")], capture_output=True, text=True,
                               env={"PATH": f"{launcher.parent}:{py3.parent}:{tools}"})
        self.assertEqual(first.stdout.strip(), f"PY3 {PLUGIN / 'adapter' / 'entry.py'} mcp", first.stderr)
        only_py = subprocess.run([str(PLUGIN / "adapter" / "mcp")], capture_output=True, text=True,
                                 env={"PATH": f"{launcher.parent}:{tools}"})
        self.assertEqual(only_py.returncode, 1, only_py.stdout)
        # on Windows (Git Bash) py comes first: python3 is often the Microsoft Store stub
        win_first = subprocess.run([str(PLUGIN / "adapter" / "mcp")], capture_output=True, text=True,
                                   env={"PATH": f"{launcher.parent}:{py3.parent}:{tools}", "OS": "Windows_NT"})
        self.assertEqual(win_first.stdout.strip(), f"LAUNCHER {PLUGIN / 'adapter' / 'entry.py'} mcp",
                         win_first.stderr)
        env = {"PATH": f"{py3.parent}:{py.parent}:{tools}"}
        mcp = subprocess.run([str(PLUGIN / "adapter" / "mcp")], capture_output=True, text=True, env=env)
        self.assertEqual(mcp.stdout.strip(), f"PY3 {PLUGIN / 'adapter' / 'entry.py'} mcp", mcp.stderr)
        cli = subprocess.run([str(PLUGIN / "bin" / "mindslice"), "-w", "a b", "status"], capture_output=True,
                             text=True, env={"PATH": f"{py.parent}:{tools}"})
        self.assertEqual(cli.stdout.strip(), f"PY {PLUGIN / 'bin' / '..' / 'adapter' / 'entry.py'} -w a b status",
                         cli.stderr)
        cyg = self.fake_python("cygpath", "C:/win")
        win = subprocess.run([str(PLUGIN / "adapter" / "mcp")], capture_output=True, text=True,
                             env={"PATH": f"{launcher.parent}:{cyg.parent}:{tools}", "OS": "Windows_NT"})
        self.assertEqual(win.stdout.strip(), f"LAUNCHER C:/win -m {PLUGIN / 'adapter' / 'entry.py'} mcp", win.stderr)
        none = subprocess.run([str(PLUGIN / "adapter" / "mcp")], capture_output=True, text=True,
                              env={"PATH": str(tools)})
        self.assertEqual(none.returncode, 1)
        self.assertIn("Python 3.12 or newer is required", none.stderr)

    @unittest.skipIf(WINDOWS, "POSIX launchers")
    def test_broken_candidate_is_skipped(self) -> None:
        # Antigravity's terminal sandbox on Windows: py exists but reports "No installed Python found!"
        broken = self.tmp / "bin-broken"
        broken.mkdir()
        for name in ("py", "python3"):
            exe = broken / name
            exe.write_text('#!/bin/sh\necho "No installed Python found!" >&2\nexit 103\n')
            exe.chmod(0o755)
        py = self.fake_python("python", "PY")
        tools = self.tmp / "tools"
        tools.mkdir()
        for name in ("dirname", "readlink"):
            (tools / name).symlink_to(shutil.which(name))
        r = subprocess.run([str(PLUGIN / "bin" / "mindslice"), "status"], capture_output=True, text=True,
                           env={"PATH": f"{broken}:{py.parent}:{tools}", "OS": "Windows_NT"})
        self.assertEqual(r.stdout.strip(), f"PY {PLUGIN / 'bin' / '..' / 'adapter' / 'entry.py'} status", r.stderr)

    @unittest.skipUnless(WINDOWS, "cmd launchers")
    def test_cmd_launcher_skips_broken_py(self) -> None:
        # a py.exe that fails (where.exe rejects -c), then the real Python as `python`; a .bat would not do: cmd
        # runs a batch file named without `call` in place of the launcher, so the fallback would never be reached
        broken = self.tmp / "bin-broken"
        broken.mkdir()
        system32 = Path(os.environ["SystemRoot"]) / "System32"
        shutil.copy(system32 / "where.exe", broken / "py.exe")
        real = Path(sys.executable).parent
        self.assertTrue((real / "python.exe").is_file(), real)
        env = dict(os.environ, PATH=f"{broken};{real};{system32}", HOME=str(self.tmp), USERPROFILE=str(self.tmp))
        r = subprocess.run(["cmd", "/c", str(PLUGIN / "bin" / "mindslice.cmd"), "--version"], capture_output=True,
                           text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mindslice 0.", r.stdout)

    @unittest.skipIf(WINDOWS, "POSIX links")
    def test_linked_cli(self) -> None:
        # the setup skill's optional ~/.local/bin/mindslice link (a relative link, followed twice)
        links = self.tmp / "links"
        links.mkdir()
        (links / "real").symlink_to(PLUGIN / "bin" / "mindslice")
        (links / "mindslice").symlink_to("real")
        r = subprocess.run([str(links / "mindslice"), "--version"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mindslice 0.", r.stdout)


if __name__ == "__main__":
    unittest.main()
