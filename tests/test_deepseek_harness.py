"""DeepSeek Harness target: bundle manifest, cordis.patch.yml, plugin.js, settings.json, hook JSON, Node integration."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import helpers
from helpers import PLUGIN, REPO, WINDOWS, PluginTestCase, only, write_always

import core
from mindslice import Workspace

LOCK = json.loads((REPO / "build" / "upstream.lock").read_text())
HEADER_RE = re.compile(r"^\[MindSlice standing memory · page (\d+)/(\d+) · snapshot ([0-9a-f]{8})\]")


def load(path: str) -> dict:
    return json.loads((PLUGIN / path).read_text(encoding="utf-8"))


@only("deepseek-harness")
class LayoutTest(unittest.TestCase):
    def test_files(self) -> None:
        for f in ("package.json", "cordis.patch.yml", "adapter/plugin.js", "adapter/hook.py", "adapter/mcp",
                  "adapter/mcp.cmd", "bin/mindslice", "bin/mindslice.cmd", "README.md", "assets/logo.png",
                  "skills/mindslice-setup/SKILL.md", "skills/mindslice-setup/uninstall.md",
                  "skills/mindslice-review/SKILL.md", "skills/mindslice-slice-maintainer/SKILL.md"):
            self.assertTrue((PLUGIN / f).is_file(), f)
        for absent in (".claude-plugin", ".codex-plugin", "rules", "plugin.json", "hooks", "mcp_config.json"):
            self.assertFalse((PLUGIN / absent).exists(), absent)

    def test_package_json_and_cordis_patch(self) -> None:
        pkg = load("package.json")
        self.assertEqual(pkg["name"], "dsh-mindslice")
        self.assertTrue(pkg["version"].startswith(LOCK["version"] + "-"))
        self.assertEqual(pkg["type"], "module")
        self.assertEqual(pkg["main"], "./adapter/plugin.js")
        self.assertEqual(pkg["dsh"], {"bundle": {"patch": "./cordis.patch.yml"}})
        self.assertNotIn("dependencies", pkg)
        self.assertNotIn("prepare", pkg.get("scripts", {}))
        self.assertTrue((PLUGIN / pkg["icon"].removeprefix("./")).is_file())
        patch = (PLUGIN / "cordis.patch.yml").read_text(encoding="utf-8")
        self.assertIn("id: mindslice", patch)
        self.assertIn("name: dsh-mindslice", patch)

    def test_skill_names_follow_dsh_grammar(self) -> None:
        for skill_dir in sorted((PLUGIN / "skills").iterdir()):
            self.assertRegex(skill_dir.name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith(f"---\nname: {skill_dir.name}\n"), skill_dir.name)

    def test_line_endings_and_modes(self) -> None:
        for f in ("adapter/mcp.cmd", "bin/mindslice.cmd"):
            data = (PLUGIN / f).read_bytes()
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), f"{f} must be CRLF")
        for f in ("adapter/mcp", "bin/mindslice", "adapter/hook.py", "adapter/plugin.js"):
            self.assertNotIn(b"\r", (PLUGIN / f).read_bytes(), f)
        if not WINDOWS:
            for f in ("adapter/mcp", "bin/mindslice"):
                self.assertTrue(os.access(PLUGIN / f, os.X_OK), f)

    def test_driver_flags(self) -> None:
        import driver

        self.assertTrue(driver.reinjects_on_compact)
        self.assertTrue(driver.options_reach_hooks)


@only("deepseek-harness")
class DataDirTest(PluginTestCase):
    def test_dsh_profile_dir_env(self) -> None:
        import driver

        os.environ.pop("PLUGIN_DATA", None)
        profile = self.tmp / "desktop-profile"
        os.environ["DSH_PROFILE_DIR"] = str(profile)
        self.assertEqual(driver.plugin_data_dir(), profile / "plugin_data" / "mindslice")

    def test_own_terminal_picks_newest_profile_data(self) -> None:
        import driver

        os.environ.pop("PLUGIN_DATA", None)
        dsh_home = self.tmp / ".dsh"
        os.environ["DSH_HOME"] = str(dsh_home)
        old = dsh_home / "profiles" / "web" / "plugin_data" / "mindslice"
        new = dsh_home / "profiles" / "desktop" / "plugin_data" / "mindslice"
        old.mkdir(parents=True)
        new.mkdir(parents=True)
        (old / "settings.json").write_text("{}\n")
        os.utime(old / "settings.json", (1000, 1000))
        (new / "settings.json").write_text("{}\n")
        os.utime(new / "settings.json", (2000, 2000))
        self.assertEqual(driver.plugin_data_dir(), new)


@only("deepseek-harness")
class ConfigAndHookTest(PluginTestCase):
    def test_plugin_config_roundtrip_and_refusal(self) -> None:
        ws = self.tmp / "mem"
        ws.mkdir()
        r = self.run_entry("plugin-config", "--workspace", str(ws), "--stage-writes", "true", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(Path(data["workspace"]), ws)
        self.assertTrue(data["stage_writes"])
        self.assertTrue(data["changed"])

        occupied = self.tmp / "occupied"
        occupied.mkdir()
        (occupied / "notes.txt").write_text("keep")
        r = self.run_entry("plugin-config", "--workspace", str(occupied))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not empty", r.stderr)

        r = self.run_entry("plugin-config", "--unset-workspace", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNone(json.loads(r.stdout)["workspace"])

    def test_hook_json_and_compaction_instructions(self) -> None:
        ws = self.tmp / "ws"
        Workspace.init(ws).close()
        write_always(ws, "prefs/tone", "Keep answers short.", title="Tone")
        self.configure(ws)

        r = self.hook(session="dsh-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.raw)
        self.assertIsInstance(payload["systemPromptSections"], list)
        self.assertGreaterEqual(len(payload["systemPromptSections"]), 1)
        self.assertTrue(HEADER_RE.match(payload["systemPromptSections"][0]))
        self.assertIn("Keep answers short.", r.context)
        self.assertIn("automatically", core.plugin_instructions())

    def test_hook_plain_text_failure_wrapped_as_json(self) -> None:
        r = subprocess.run([sys.executable, str(PLUGIN / "adapter" / "hook.py")],
                           input=json.dumps({"session_id": "s1"}),
                           capture_output=True, text=True,
                           env=dict(os.environ, MINDSLICE_PLUGIN_WHEEL=str(self.tmp / "missing.whl"),
                                    MINDSLICE_PLUGIN_ENGINE_DIR=""),
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertTrue(payload["systemPromptSections"][0].startswith("[MindSlice plugin could not start]"))

    def test_node_cordis_plugin_integration(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        env = dict(os.environ)
        for k in ("PLUGIN_DATA", "MINDSLICE_PLUGIN_DATA", "PLUGIN_ROOT"):
            env.pop(k, None)
        r = subprocess.run([node, "--test", str(REPO / "tests" / "test_dsh_plugin.mjs")],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
