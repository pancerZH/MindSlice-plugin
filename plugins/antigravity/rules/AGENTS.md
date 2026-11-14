# MindSlice long-term memory

MindSlice is this user's long-term memory: the plugin's `mindslice` MCP server (tools `manifest`, `search`,
`read`, `write`) and the `mindslice` command on your terminal tool's PATH.

- At the start of each conversation the plugin injects MindSlice's usage instructions and the user's
  always-loaded cards as "MindSlice standing memory" system messages, numbered `page i/n` with one snapshot id,
  the last one ending with a `complete` line. Follow them as standing instructions.
- If those pages are missing, incomplete or carry different snapshot ids, call `manifest` with
  `include_always=true` before you reply, and follow the `instructions` and `always_loaded` cards it returns.
- After the conversation has been compacted (it resumes from a compaction summary), the pages are no longer in
  your context: call `manifest` with `include_always=true` again before continuing.
- Never run `mindslice apply` or `mindslice discard` unless the user approves those exact changes in this
  conversation (see the `/mindslice:review` skill).
