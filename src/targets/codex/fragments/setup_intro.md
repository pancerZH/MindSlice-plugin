This plugin has already done what a manual MindSlice setup does by hand: it ships the `mindslice` engine and
command, registers the MindSlice MCP server (`mindslice`, tools `manifest`, `search`, `read`, `write`), and
delivers the user's standing memory through its own `SessionStart` hooks at every session start, resume,
clear, fork and compaction. **Do not install the `mindslice` package, register another MindSlice MCP server
(`codex mcp add`), add `boot` hooks or add a "call manifest" rule to `AGENTS.md`**: that would load the memory
twice. What is left is trusting the hooks, the workspace (where it lives, how to seed it), and checking that a
new session receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.
