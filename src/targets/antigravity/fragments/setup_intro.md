This plugin has already done what a manual MindSlice setup does by hand: it ships the `mindslice` engine and
command, registers the MindSlice MCP server (`mindslice`, tools `manifest`, `search`, `read`, `write`),
delivers the user's standing memory through its own `SessionStart` hook at the start of every conversation,
and adds an always-on rule (`rules/AGENTS.md`) that tells the agent to call `manifest` after a compaction.
**Do not install the `mindslice` package, register another MindSlice MCP server, add `boot` hooks or add a
"call manifest" rule to `GEMINI.md` or `AGENTS.md`**: that would load the memory twice. What is left is the
workspace: where it lives, how to seed it, and checking that a new conversation receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.
