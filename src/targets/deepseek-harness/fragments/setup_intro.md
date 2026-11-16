This plugin has already done what a manual MindSlice setup does by hand: it provisions the `mindslice`
engine and command, registers the `mindslice` MCP server (`mcp__mindslice__manifest`, `search`, `read`,
`write`) via `ctx.mcpManager`, and delivers your standing memory in the system prompt at session start and
after compaction. **Do not add another MindSlice MCP server, add `boot` hooks, or add a "call manifest"
rule to `AGENTS.md`**: that would load the memory twice. What is left is choosing the workspace (where it
lives, how to seed it), and checking that a new session receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.
