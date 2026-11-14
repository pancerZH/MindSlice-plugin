"""Plugin MCP server: short instructions, rewritten engine text, bounded results without fingerprint drift."""

from __future__ import annotations

import json
import os
import unittest

import helpers  # noqa: F401
from helpers import PLUGIN, WINDOWS, PluginTestCase, write_always

import core
from mindslice import Workspace
from mindslice.interfaces.mcp_server import INSTRUCTIONS, TOOLS


def rpc(server, method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    return server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})


def call(server, name: str, arguments: dict) -> dict:
    result = rpc(server, "tools/call", {"name": name, "arguments": arguments})["result"]
    return json.loads(result["content"][0]["text"])


class MCPTest(PluginTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.tmp / "ws"
        Workspace.init(self.root).close()

    def server(self, ws: Workspace) -> core.PluginMCPServer:
        s = core.PluginMCPServer(ws)
        rpc(s, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test-client"}})
        return s

    def test_handshake(self) -> None:
        write_always(self.root, "prefs/secret", "- The secret phrase is ZEBRA-4412.")
        with Workspace(self.root) as ws:
            s = core.PluginMCPServer(ws)
            init = rpc(s, "initialize", {"clientInfo": {"name": "t"}})["result"]
            self.assertLessEqual(len(init["instructions"]), 1000)
            self.assertEqual(init["instructions"], core.SHORT_INSTRUCTIONS)
            self.assertNotIn("ZEBRA-4412", init["instructions"])
            tools = rpc(s, "tools/list", msg_id=2)["result"]["tools"]
            self.assertEqual([t["name"] for t in tools], [t["name"] for t in TOOLS])
            manifest = next(t for t in tools if t["name"] == "manifest")
            self.assertNotIn("again after the conversation is compacted", manifest["description"])
            self.assertIn("include_always=false", manifest["description"])
            # the delivered set counts as seen: no update on the first search
            self.assertNotIn("always_loaded_update", call(s, "search", {"query": "secret"}))
            m = call(s, "manifest", {})
            self.assertNotEqual(m["instructions"], INSTRUCTIONS)
            self.assertEqual(m["instructions"], core.plugin_instructions())

    def test_large_always_set_omits_bodies_without_spurious_updates(self) -> None:
        for i in range(6):
            write_always(self.root, f"big/c{i}", "- " + ("standing rule text " * 300))
        with Workspace(self.root) as ws:
            s = self.server(ws)
            m = call(s, "manifest", {})
            self.assertIn("always_loaded_note", m)
            self.assertTrue(all(c.get("body_omitted") and "body" not in c for c in m["always_loaded"]))
            self.assertTrue(all("address" in c and "title" in c for c in m["always_loaded"]))
            for name, args in (("search", {"query": "standing rule"}), ("read", {"address": "big/c1"})):
                self.assertNotIn("always_loaded_update", call(s, name, args), name)
            # a real change mid-session still arrives (and is bounded the same way)
            for i in range(6):
                with Workspace(self.root) as other:
                    other.write(f"big/c{i}", op="replace", content="- " + ("changed rule text " * 300),
                                load="always", stage=False, reason="t")
            r = call(s, "search", {"query": "rule"})
            update = r["always_loaded_update"]
            self.assertTrue(all(c.get("body_omitted") for c in update["cards"]))
            self.assertNotIn("always_loaded_update", call(s, "search", {"query": "rule"}))

    def test_small_results_match_upstream(self) -> None:
        write_always(self.root, "prefs/lang", "- Reply in English.")
        with Workspace(self.root) as ws:
            s = self.server(ws)
            m = call(s, "manifest", {})
            self.assertNotIn("always_loaded_note", m)
            self.assertIn("body", m["always_loaded"][0])

    def test_stage_writes(self) -> None:
        with Workspace(self.root) as ws:
            s = core.PluginMCPServer(ws, stage_writes=True)
            r = call(s, "write", {"id": "t/x", "summary": "s", "content": "- y", "reason": "t", "stage": False})
            self.assertTrue(r.get("staged") or "staging" in json.dumps(r), r)

    def test_mcp_as_the_manifest_starts_it(self) -> None:
        # plugin.json: command ${CLAUDE_PLUGIN_ROOT}/adapter/mindslice (mindslice.cmd on Windows), args ["mcp"],
        # the workspace option in the environment
        manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["mcpServers"]["mindslice"]
        command = manifest["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
        if WINDOWS:
            command += ".cmd"  # what Claude's spawn finds through PATHEXT
        env = {k: v.replace("${user_config.workspace}", str(self.root)).replace("${user_config.stage_writes}", "false")
               for k, v in manifest["env"].items()}
        # Claude sets CLAUDE_PLUGIN_ROOT itself and does not expand variables in "env": an entry there would
        # replace it with the literal text
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", manifest["env"])
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        r = self.run_entry(*manifest["args"], stdin=json.dumps(req) + "\n", env=env, cmd=[command])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.splitlines()[0])["id"], 1)
        self.assertEqual(core.read_bridge(), str(self.root))

    def test_mcp_entry_bridge(self) -> None:
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
        r = self.run_entry("mcp", "--workspace", str(self.root), stdin=json.dumps(reqs[0]) + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(core.read_bridge(), str(self.root))
        # an unsubstituted option is treated as unset
        bad = self.run_entry("mcp", stdin="", env={"MINDSLICE_PLUGIN_OPTION_WORKSPACE": "${user_config.workspace}"})
        self.assertEqual(bad.returncode, 1)
        self.assertIn("no memory workspace configured", bad.stderr)


if __name__ == "__main__":
    unittest.main()
