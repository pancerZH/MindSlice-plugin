This plugin has already done what a manual MindSlice setup does by hand: it ships the `mindslice` engine and
command, registers the MindSlice MCP server (tools `mcp__plugin_mindslice_mindslice__manifest`, `search`,
`read`, `write`), and delivers the user's standing memory through its own `SessionStart` hooks at every
session start, resume, clear and compaction. **Do not install the `mindslice` package, register another
MindSlice MCP server, add `boot` hooks or add a "call manifest" rule to `CLAUDE.md`**: that would load the
memory twice. What is left is the workspace: where it lives, how to seed it, and checking that a new session
receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.
