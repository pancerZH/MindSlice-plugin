"""Codex target: layout, the hook's JSON, the data directory the MCP server derives, plugin-config, launchers.

Runs when the suite targets Codex: ``MINDSLICE_PLUGIN_TARGET=codex python3 -m unittest ...``. What these tests
encode was measured on Codex CLI 0.169.0 (see the driver's docstring); ``tests/acceptance_codex.sh`` checks it
against a real ``codex``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import PLUGIN, REPO, WINDOWS, PluginTestCase, only, snapshot_files, write_always

import core
from mindslice import Workspace

LOCK = json.loads((REPO / "build" / "upstream.lock").read_text())
HEADER_RE = re.compile(r"^\[MindSlice standing memory · page (\d+)/(\d+) · snapshot ([0-9a-f]{8})\]")


def load(path: str) -> dict:
    return json.loads((PLUGIN / path).read_text(encoding="utf-8"))


def hook_handler() -> dict:
    """The plugin's one hook: the user trusts each handler separately, and again after every update."""
    (group,) = load("hooks/hooks.json")["hooks"]["SessionStart"]
    (handler,) = group["hooks"]
    return handler


@only("codex")
class LayoutTest(unittest.TestCase):
    def test_files(self) -> None:
        for f in (".codex-plugin/plugin.json", ".mcp.json", "hooks/hooks.json", "adapter/hook.py", "adapter/mcp",
                  "adapter/mcp.cmd", "bin/mindslice", "bin/mindslice.cmd", "README.md", "assets/logo.png"):
            self.assertTrue((PLUGIN / f).is_file(), f)
        for absent in (".claude-plugin", "rules", "plugin.json", "mcp.json", "mcp_config.json"):
            self.assertFalse((PLUGIN / absent).exists(), absent)

    def test_manifest(self) -> None:
        manifest = load(".codex-plugin/plugin.json")
        self.assertEqual(manifest["name"], "mindslice")
        self.assertTrue(manifest["version"].startswith(LOCK["version"] + "-"))
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertNotIn("hooks", manifest)  # hooks/hooks.json is found by default; a value would replace it
        ui = manifest["interface"]
        for key in ("displayName", "shortDescription", "longDescription", "developerName", "category",
                    "capabilities", "logo", "composerIcon"):
            self.assertIn(key, ui)
        self.assertLessEqual(len(ui["displayName"]), 30)
        self.assertLessEqual(len(ui["shortDescription"]), 30)
        self.assertLessEqual(len(ui["defaultPrompt"]), 3)
        for key in ("logo", "composerIcon"):
            self.assertTrue(ui[key].startswith("./"))
            self.assertTrue((PLUGIN / ui[key]).is_file(), ui[key])

    def test_mcp_json(self) -> None:
        server = load(".mcp.json")["mcpServers"]["mindslice"]
        # Codex substitutes nothing in a plugin's MCP entry and resolves cwd against the plugin folder
        self.assertEqual(server["command"], "./adapter/mcp")
        self.assertEqual(server["cwd"], ".")
        self.assertNotIn("${", json.dumps(server))
        self.assertNotIn("env", server)
        # its environment is filtered: only what env_vars names passes through (isolation for nested sessions)
        self.assertEqual(server["env_vars"], ["MINDSLICE_PLUGIN_ISOLATE"])
        self.assertGreaterEqual(server["startup_timeout_sec"], 30)  # the first start may download the engine

    def test_hooks_json(self) -> None:
        cfg = helpers.target_config()
        self.assertNotIn("matcher", load("hooks/hooks.json")["hooks"]["SessionStart"][0])  # every source
        h = hook_handler()
        self.assertEqual(h["type"], "command")
        runs = re.findall(r'(\S+) "\$\{PLUGIN_ROOT\}/adapter/hook\.py"', h["command"])
        self.assertEqual(runs, ["python3", "py", "python"])
        self.assertGreater(h["timeout"], 55)  # hook.py's own timeout
        # Codex cuts a hook's context at ~2,500 tokens unless this raises it. Measured: 38,000 CJK characters pass
        # a limit of 32000; a token per UTF-16 unit of every page is a bound with room to spare.
        self.assertGreaterEqual(h["additionalContextLimit"], cfg["hook_slots"] * cfg["page_limit"])

    def test_line_endings_and_modes(self) -> None:
        for f in ("adapter/mcp.cmd", "bin/mindslice.cmd"):
            data = (PLUGIN / f).read_bytes()
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), f"{f} must be CRLF")
        for f in ("adapter/mcp", "bin/mindslice", "adapter/hook.py"):
            self.assertNotIn(b"\r", (PLUGIN / f).read_bytes(), f)
        if not WINDOWS:
            for f in ("adapter/mcp", "bin/mindslice"):
                self.assertTrue(os.access(PLUGIN / f, os.X_OK), f)

    def test_marketplace(self) -> None:
        market = json.loads((REPO / ".agents" / "plugins" / "marketplace.json").read_text())
        self.assertEqual(market["name"], "mindslice")
        (entry,) = market["plugins"]
        self.assertEqual(entry["name"], "mindslice")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/codex"})
        for key in ("policy", "category"):
            self.assertIn(key, entry)
        self.assertEqual(REPO / entry["source"]["path"], PLUGIN)

    def test_driver_flags(self) -> None:
        import driver

        self.assertTrue(driver.reinjects_on_compact)  # SessionStart fires with source "compact"
        self.assertTrue(driver.options_reach_hooks)  # the settings file


@only("codex")
class HookTest(PluginTestCase):
    def test_hook_command_as_codex_runs_it(self) -> None:
        # what hooks.json runs, ${PLUGIN_ROOT} substituted by Codex, in the session's directory
        ws = self.tmp / "ws"
        self.configure(ws)
        project = self.tmp / "project"
        project.mkdir()
        command = hook_handler()["command"].replace("${PLUGIN_ROOT}", str(PLUGIN))
        shell = ["cmd", "/c", command] if WINDOWS else ["sh", "-c", command]
        r = subprocess.run(shell, cwd=project, input=json.dumps({"session_id": "c1", "source": "startup"}),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertTrue(out["additionalContext"].startswith("[MindSlice standing memory · page 1/1"))
        self.assertIn("standing memory complete", out["additionalContext"])

    def test_every_page_in_one_context(self) -> None:
        ws = self.tmp / "ws"
        self.configure(ws)
        core.ensure_workspace(core.resolve("hook"))
        for i in range(6):
            write_always(ws, f"rules/r{i}", "- " + ("规则内容 " * 900))
        r = self.hook(session="many")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.raw.splitlines()), 1)  # one JSON object
        headers = [HEADER_RE.match(page) for page in r.pages]
        self.assertGreater(len(headers), 1)
        self.assertEqual([(int(m.group(1)), int(m.group(2))) for m in headers],
                         [(i, len(headers)) for i in range(1, len(headers) + 1)])  # in order, none missing
        self.assertEqual(len({m.group(3) for m in headers}), 1)  # one snapshot
        self.assertIn("standing memory complete", r.pages[-1])
        self.assertEqual(r.context, core.SEP.join(r.pages))
        self.assertLessEqual(core.utf16_len(r.context), hook_handler()["additionalContextLimit"])

    def test_overflow_keeps_the_first_pages(self) -> None:
        ws = self.tmp / "ws"
        self.configure(ws)
        core.ensure_workspace(core.resolve("hook"))
        cfg = helpers.target_config()
        for i in range(-(-cfg["hook_slots"] * cfg["page_limit"] // 8000) + 2):
            write_always(ws, f"big/b{i}", "- " + ("长规则 " * 2200))
        r = self.hook(session="ovf")
        self.assertEqual(len(r.pages), cfg["hook_slots"])
        self.assertIn("MindSlice's usage instructions", r.pages[0])  # the preamble is still there
        self.assertIn("# Standing memory overflow", r.pages[-1])
        self.assertLessEqual(core.utf16_len(r.context), hook_handler()["additionalContextLimit"])

    def test_unconfigured(self) -> None:
        r = self.hook(1)
        self.assertIn("no memory workspace configured", r.stdout)
        self.assertIn("plugin-config --workspace", r.stdout)
        self.assertNotIn("/plugin,", r.stdout)  # no plugin options in Codex
        self.assertTrue((core.plugin_data_dir() / "bin" / "mindslice").is_file())  # setup still has the CLI

    def test_page_names_the_stable_cli(self) -> None:
        self.configure(self.tmp / "ws")
        page = self.hook(1).stdout
        launcher = core.plugin_data_dir() / "bin" / ("mindslice.cmd" if WINDOWS else "mindslice")
        self.assertIn(f"run it as `{launcher}`", page)
        self.assertIn("escalated permissions", page)
        self.assertIn("$mindslice:review", page)

    def test_plain_text_failure_becomes_context(self) -> None:
        # entry.py reports a failure before any driver code runs (here: no engine, offline) in plain text that
        # starts with "[", which Codex would reject as broken JSON
        os.environ.pop("MINDSLICE_PLUGIN_ENGINE_DIR")
        probe = subprocess.run([sys.executable, "-c", "import importlib.metadata as m; print(m.version('mindslice'))"],
                               capture_output=True, text=True)
        if probe.stdout.strip() == LOCK["version"]:
            self.skipTest(f"mindslice {LOCK['version']} is installed for this interpreter")
        env = {"MINDSLICE_PLUGIN_WHEEL": str(self.tmp / "nope.whl"), "PYTHONNOUSERSITE": "1"}
        r = self.hook(1, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("[MindSlice plugin could not start]", r.stdout)
        self.assertEqual(len(r.raw.splitlines()), 1)  # as JSON, like a page

    def test_stderr_only_crash_becomes_context(self) -> None:
        os.environ.pop("PLUGIN_DATA", None)
        r = self.hook(1, env={"HOME": "", "USERPROFILE": ""})
        self.assertEqual(r.returncode, 0)
        self.assertIn("[MindSlice plugin could not start]", r.stdout)
        self.assertIn("no plugin data directory", r.stdout)


@only("codex")
class InstalledLayoutTest(PluginTestCase):
    """The plugin as Codex installs it: <home>/plugins/cache/<marketplace>/mindslice/<version>/."""

    def install(self) -> tuple[Path, Path]:
        home = self.tmp / "codex-home"
        root = home / "plugins" / "cache" / "mkt" / "mindslice" / "1.2.3"
        shutil.copytree(PLUGIN, root, symlinks=True)
        os.environ.pop("PLUGIN_DATA")  # only hooks get it
        os.environ.pop("PLUGIN_ROOT")
        return root, home / "plugins" / "data" / "mindslice-mkt"

    def test_data_dir_is_derived_from_the_install_path(self) -> None:
        import driver

        root, data = self.install()
        self.assertEqual(driver.cache_data_dir(root), data)
        self.assertIsNone(driver.cache_data_dir(PLUGIN))
        self.assertIsNone(driver.cache_data_dir(Path("/plugins/cache/x")))

    def test_mcp_as_codex_starts_it(self) -> None:
        # ./adapter/mcp in the plugin folder, with no PLUGIN_DATA: it finds the settings plugin-config wrote
        root, data = self.install()
        ws = self.tmp / "ws"
        cli = [str(root / "bin" / ("mindslice.cmd" if WINDOWS else "mindslice"))]
        r = self.run_entry("plugin-config", "--workspace", str(ws), cmd=cli)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((data / "settings.json").read_text())["workspace"], str(ws))
        server = load(".mcp.json")["mcpServers"]["mindslice"]
        command = server["command"] + (".cmd" if WINDOWS else "")
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        r = self.run_entry(stdin="".join(json.dumps(q) + "\n" for q in reqs), cwd=root / server["cwd"],
                           cmd=[str(root / command) if WINDOWS else command])
        self.assertEqual(r.returncode, 0, r.stderr)
        out = [json.loads(line) for line in r.stdout.splitlines()]
        self.assertEqual(out[0]["result"]["instructions"], core.SHORT_INSTRUCTIONS)
        self.assertTrue((ws / "mounts.toml").is_file())
        self.assertEqual(json.loads((data / "active_workspace.json").read_text())["workspace"], str(ws))
        # the hooks, which do get PLUGIN_DATA, use the same directory
        hook = self.run_entry(stdin="{}", cmd=[sys.executable, str(root / "adapter" / "hook.py")],
                              env={"PLUGIN_DATA": str(data), "PLUGIN_ROOT": str(root)})
        page = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"Memory workspace: `{ws}`", page)
        self.assertIn(str(data / "bin"), page)


@only("codex")
class ConfigTest(PluginTestCase):
    def config(self, *args: str) -> subprocess.CompletedProcess:
        return self.run_entry("plugin-config", *args, cmd=self.shim())

    def test_set_show_unset(self) -> None:
        import driver

        ws = self.tmp / "mem"
        r = self.config("--workspace", str(ws), "--stage-writes", "true")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("start a new Codex session", r.stdout)
        self.assertEqual(driver.configured_workspace(), str(ws))
        self.assertTrue(driver.stage_writes_enabled())
        self.assertFalse(ws.exists())  # initialized at the next session start, not here
        shown = json.loads(self.config("--json").stdout)
        self.assertEqual((shown["workspace"], shown["stage_writes"], shown["changed"]), (str(ws), True, False))
        self.assertEqual(core.resolve("hook").path, ws)
        self.assertEqual(core.resolve("mcp").path, ws)
        self.config("--stage-writes", "false")
        self.assertFalse(driver.stage_writes_enabled())
        core.write_bridge(ws)
        self.assertEqual(self.config("--unset-workspace").returncode, 0)
        self.assertIsNone(driver.configured_workspace())
        self.assertIsNone(core.read_bridge())
        self.assertIn("no memory workspace configured", self.hook(1).stdout)

    def test_home_relative_path(self) -> None:
        import driver

        os.environ["USERPROFILE" if WINDOWS else "HOME"] = str(self.tmp / "home")
        self.assertEqual(self.config("--workspace", "~/mem").returncode, 0)
        self.assertEqual(driver.configured_workspace(), str(self.tmp / "home" / "mem"))

    def test_refused_paths_change_nothing(self) -> None:
        import driver

        notes = self.tmp / "notes"
        notes.mkdir()
        (notes / "todo.md").write_text("mine\n")
        before = snapshot_files(notes)
        cases = [("relative/path", "relative path"), ("$HOME/mem", "unexpanded shell variable"),
                 (str(PLUGIN / "mem"), "plugin installation folder"),
                 (str(core.plugin_data_dir() / "mem"), "internal data folder"),
                 (str(notes), "not empty and is not a MindSlice workspace")]
        for value, why in cases:
            r = self.config("--workspace", value)
            self.assertEqual(r.returncode, 1, value)
            self.assertIn(why, r.stderr, value)
            self.assertIn("Nothing was changed", r.stderr)
            self.assertIsNone(driver.configured_workspace())
        self.assertEqual(snapshot_files(notes), before)
        existing = self.tmp / "existing"
        Workspace.init(existing).close()
        self.assertEqual(self.config("--workspace", str(existing)).returncode, 0)

    def test_read_only_sandbox_is_one_line(self) -> None:
        # Codex's sandbox shows the world outside the project as a read-only file system (EROFS)
        import driver

        denied = OSError(30, "Read-only file system", str(core.plugin_data_dir() / "settings.json"))
        err = io.StringIO()
        with mock.patch.object(core, "atomic_write", side_effect=denied), contextlib.redirect_stderr(err):
            self.assertEqual(core.main(["plugin-config", "--workspace", str(self.tmp / "ws")]), 1)
        lines = err.getvalue().splitlines()
        self.assertIn("Read-only file system", lines[0])
        self.assertEqual(lines[1], f"mindslice plugin: {driver.PERMISSION_HINT}")
        other = OSError(5, "I/O error")
        with mock.patch.object(core, "atomic_write", side_effect=other), self.assertRaises(OSError):
            core.main(["plugin-config", "--workspace", str(self.tmp / "ws")])


@only("codex")
class SettingsTest(PluginTestCase):
    def test_compaction_text(self) -> None:
        self.assertNotIn("call manifest() again before continuing", core.plugin_instructions())

    def test_stage_writes_comes_from_the_settings_file_only(self) -> None:
        # the MCP server's environment is filtered: a variable would never reach it
        import driver

        os.environ["MINDSLICE_PLUGIN_STAGE_WRITES"] = "true"
        self.assertFalse(driver.stage_writes_enabled())
        driver.save_settings({"stage_writes": True})
        self.assertTrue(driver.stage_writes_enabled())


@only("codex")
class LauncherTest(PluginTestCase):
    @unittest.skipIf(WINDOWS, "POSIX launchers")
    def test_cli_without_hooks(self) -> None:
        # before the hooks have run (not trusted yet), setup uses <plugin root>/bin/mindslice
        env = {k: v for k, v in os.environ.items() if k not in ("PLUGIN_ROOT", "PLUGIN_DATA")}
        env["HOME"] = str(self.tmp)
        r = subprocess.run([str(PLUGIN / "bin" / "mindslice"), "plugin-config"], capture_output=True, text=True,
                           env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("workspace: (not configured)", r.stdout)

    @unittest.skipIf(WINDOWS, "POSIX links")
    def test_linked_launcher(self) -> None:
        d = core.write_launchers()
        links = self.tmp / "links"
        links.mkdir()
        (links / "mindslice").symlink_to(d / "mindslice")
        r = subprocess.run([str(links / "mindslice"), "--version"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mindslice 0.", r.stdout)


if __name__ == "__main__":
    unittest.main()
