"""Build output and upstream contract (PLAN 3, 4.2, 5, 8)."""

from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import helpers
from helpers import PLUGIN, REPO

import core

sys.path.insert(0, str(REPO / "build"))
import build  # noqa: E402

LOCK = json.loads((REPO / "build" / "upstream.lock").read_text())


def local_upstream() -> Path | None:
    env = os.environ.get("MINDSLICE_UPSTREAM")
    if env:
        return Path(env)
    sibling = REPO.parent / "mindslice"
    return sibling if (sibling / ".git").exists() else None


class ContractTest(unittest.TestCase):
    def test_upstream_symbols(self) -> None:
        import importlib

        import mindslice

        for dotted in core.UPSTREAM_CONTRACT:
            head, *rest = dotted.split(".")
            if head == "Workspace":
                obj = mindslice.Workspace
            elif head == "MCPServer":
                obj = core.MCPServer
            else:
                mod_parts = [head]
                while rest and not hasattr(importlib.import_module("mindslice." + ".".join(mod_parts)), rest[0]):
                    mod_parts.append(rest.pop(0))
                obj = importlib.import_module("mindslice." + ".".join(mod_parts))
            for attr in rest:
                obj = getattr(obj, attr)
            self.assertTrue(obj is not None, dotted)

    def test_signatures(self) -> None:
        from mindslice import Workspace
        from mindslice.interfaces.mcp_server import MCPServer
        from mindslice.operations.boot import render_markdown
        from mindslice.storage.locking import WorkspaceLock

        def params(fn):
            return list(inspect.signature(fn).parameters)

        self.assertEqual(params(Workspace.init)[:1], ["root"])
        self.assertEqual(params(render_markdown), ["cards", "header"])
        self.assertEqual(params(MCPServer.__init__), ["self", "ws", "stage_writes"])
        self.assertEqual(params(MCPServer._mark_seen), ["self", "cards"])
        self.assertEqual(params(MCPServer.call_tool), ["self", "name", "arguments"])
        self.assertEqual(params(MCPServer._tools_call), ["self", "params"])
        self.assertEqual(params(WorkspaceLock.__init__), ["self", "path", "timeout"])

    def test_engine_text_rewrites_match(self) -> None:
        for reinject in (True, False):
            text = core.plugin_instructions(reinject)
            self.assertIn("standing memory", text)
            core.plugin_tools(reinject)
        self.assertIn("call manifest() again before continuing", core.plugin_instructions(False))
        self.assertNotIn("call manifest() again before continuing", core.plugin_instructions(True))


class OutputTest(unittest.TestCase):
    def files(self) -> list[str]:
        return sorted(p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("*")
                      if p.is_file() and "__pycache__" not in p.parts)

    def test_whitelist_and_size(self) -> None:
        files = self.files()
        for f in files:
            self.assertTrue(any(f == p or (p.endswith("/") and f.startswith(p)) for p in build.OUTPUT_ALLOWED), f)
            self.assertFalse(f.startswith(("tests/", "evals/", "docs/", ".github/", "src/", "build/")), f)
        self.assertNotIn("adapter/drivers", "\n".join(files))
        self.assertFalse(any(f.startswith("engine/") or "/mindslice/" in f for f in files), "engine is not shipped")
        total = sum((PLUGIN / f).stat().st_size for f in files)
        self.assertLessEqual(total, build.MAX_TARGET_BYTES)
        for f in ("adapter/entry.py", "adapter/core.py", "adapter/driver.py", "adapter/provision.py", "bin/mindslice", "hooks/hooks.json",
                  ".claude-plugin/plugin.json", "LICENSE", "NOTICE", "skills/setup/SKILL.md", "skills/review/SKILL.md"):
            self.assertIn(f, files)
        if os.name != "nt":
            self.assertTrue(os.access(PLUGIN / "bin" / "mindslice", os.X_OK))
        self.assertIn("bin/mindslice.cmd", files)
        cmd = (PLUGIN / "bin" / "mindslice.cmd").read_bytes()
        self.assertNotIn(b"\n", cmd.replace(b"\r\n", b""), "mindslice.cmd must be CRLF")
        lines = [line.strip().lower() for line in cmd.decode("ascii").splitlines() if line.strip()]
        self.assertEqual(lines[-1], "exit /b %errorlevel%", "the exit code must be passed on explicitly")
        self.assertNotIn("exit /b", lines[:-1])
        self.assertNotIn(b"\r", (PLUGIN / "bin" / "mindslice").read_bytes(), "the sh shim must be LF")

    def test_build_info_matches(self) -> None:
        info = json.loads((PLUGIN / ".build-info.json").read_text())
        self.assertEqual(info["upstream"]["commit"], LOCK["commit"])
        import hashlib
        for path, digest in info["files"].items():
            self.assertEqual(hashlib.sha256((PLUGIN / path).read_bytes()).hexdigest(), digest, path)

    def test_no_bare_python3_in_launch_commands(self) -> None:
        manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["mcpServers"]["mindslice"]["command"], "${user_config.python}")
        self.assertEqual(manifest["userConfig"]["python"]["default"], "python3")
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]["SessionStart"][0]["hooks"]
        for i, h in enumerate(hooks, 1):
            self.assertEqual(h["command"], f'sh "${{CLAUDE_PLUGIN_ROOT}}/bin/mindslice" hook {i}')

    def test_manifest_version(self) -> None:
        manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        self.assertTrue(manifest["version"].startswith(LOCK["version"] + "-"))
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        for entry in market["plugins"]:
            self.assertTrue((REPO / entry["source"] / ".claude-plugin" / "plugin.json").is_file())

    def test_skill_names_match_directories(self) -> None:
        for skill in (PLUGIN / "skills").iterdir():
            text = (skill / "SKILL.md").read_text()
            self.assertTrue(text.startswith(f"---\nname: {skill.name}\n"), skill.name)
            self.assertNotIn("{{", text)

    def test_target_pins_the_locked_wheel(self) -> None:
        engine = json.loads((PLUGIN / "adapter" / "target.json").read_text())["engine"]
        self.assertEqual(engine, {"version": LOCK["version"], "url": LOCK["wheel"]["url"],
                                  "sha256": LOCK["wheel"]["sha256"]})

    def test_installed_engine_is_the_locked_commit(self) -> None:
        upstream = local_upstream()
        if upstream is None:
            self.skipTest("no local upstream checkout")
        out = subprocess.run(["git", "-C", str(upstream), "ls-tree", "-r", "--name-only", LOCK["commit"], "mindslice"],
                             capture_output=True, text=True, check=True).stdout.split()
        for path in (p for p in out if p.endswith(".py")):
            blob = subprocess.run(["git", "-C", str(upstream), "show", f"{LOCK['commit']}:{path}"],
                                  capture_output=True, check=True).stdout
            self.assertEqual((helpers.ENGINE / path).read_bytes(), blob, path)


class BuildCheckTest(unittest.TestCase):
    def test_check(self) -> None:
        upstream = local_upstream()
        if upstream is None:
            self.skipTest("no local upstream checkout (set MINDSLICE_UPSTREAM)")
        r = subprocess.run([sys.executable, str(REPO / "build" / "build.py"), "--check", "--upstream", str(upstream)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_failing_rule_fails_the_build(self) -> None:
        saved = list(build.rules.REWRITES)
        try:
            build.rules.REWRITES.append({"source": "setup.step2", "when": None, "kind": "replace",
                                         "old": "this sentence is not upstream", "new": "x"})
            with self.assertRaises(build.BuildError):
                build.apply_rules("setup.step2", "some text", {"builder": False, "no_builder": True})
        finally:
            build.rules.REWRITES[:] = saved

    def test_wheel_must_match_the_locked_commit(self) -> None:
        import io
        import zipfile

        upstream = local_upstream()
        if upstream is None:
            self.skipTest("no local upstream checkout")
        up = build.Upstream.load(LOCK, upstream)
        good = build.load_wheel(LOCK, None)
        build.check_wheel(good, up, LOCK["version"])
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(good)) as src, zipfile.ZipFile(buf, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                dst.writestr(name, data + b"# patched\n" if name == "mindslice/workspace.py" else data)
        with self.assertRaises(build.BuildError):
            build.check_wheel(buf.getvalue(), up, LOCK["version"])

    def test_dead_links_fail(self) -> None:
        files = {"skills/a/SKILL.md": build.OutFile(b"see [x](../b/SKILL.md)")}
        with self.assertRaises(build.BuildError):
            build.check_links(files)

    def test_claude_validate(self) -> None:
        claude = shutil.which("claude")
        if not claude:
            self.skipTest("claude CLI not installed")
        r = subprocess.run([claude, "plugin", "validate", str(PLUGIN)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
