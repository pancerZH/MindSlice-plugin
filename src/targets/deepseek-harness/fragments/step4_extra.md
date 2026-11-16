### DeepSeek Harness: the new-session checks

Ask the user to start a **new session** (after disabling/re-enabling `dsh-mindslice` in **Plugins** if
`workspace` was just changed for the first time so the MCP server restarts with the workspace) and verify:

1. **Standing memory without tool calls**: ask the model "Without calling any tool, what is the phrase in your
   MindSlice always-loaded memory?" — a correct phrase confirms the system-prompt delivery arrived.
2. **Memory lookup**: ask a question only a `load="as-needed"` card answers, and verify the model calls
   `mcp__mindslice__search` or `mcp__mindslice__read`.
3. **Compaction**: run `/compact` in a session and ask for the standing-memory phrase again to confirm the
   system prompt keeps and refreshes the standing memory after compaction.
