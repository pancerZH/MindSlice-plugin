If MindSlice was set up by hand before (the `mindslice-setup` skill or the README), the old configuration
now delivers the memory a second time and exposes a second set of tools. Look for it, show the user what
you found, and remove it **only after they agree**, editing surgically so every other entry stays valid:

- **MCP server**: `codex mcp list` shows the servers configured in `~/.codex/config.toml` (and in a trusted
  project's `.codex/config.toml`): look for one other than the plugin's whose command runs
  `mindslice ... mcp`, and remove it with `codex mcp remove <name>`. Note the `-w` path it used: if it differs
  from the plugin's workspace, ask which one the user wants to keep (Step 3).
- **Hooks**: `~/.codex/hooks.json`, `[hooks]` tables in `~/.codex/config.toml`, and a project's
  `.codex/hooks.json` or `.codex/config.toml`, for a hook that runs `mindslice ... boot`. Do not touch the
  `[hooks.state...]` entries: they record which hooks the user trusted.
- **Standing rule**: `~/.codex/AGENTS.md` and project `AGENTS.md` files, for the paragraph that tells the
  agent to call the MindSlice server's `manifest` tool. The plugin's startup pages and MCP server
  instructions replace it.
- **The PyPI/checkout `mindslice` command** itself can stay; the plugin does not use it. Removing a
  `MINDSLICE_WORKSPACE` export from a shell profile is worth suggesting: it overrides the plugin's choice of
  workspace for every `mindslice` command.

Do not read `~/.codex/auth.json`: it holds the user's credentials. Then start a new session and run
`mindslice plugin-status` and the Step 4 checks again.
