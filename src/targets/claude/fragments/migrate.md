If MindSlice was set up by hand before (the `mindslice-setup` skill or the README), the old configuration
now delivers the memory a second time and exposes a second set of tools. Look for it, show the user what
you found, and remove it **only after they agree**, editing surgically so every other entry stays valid:

- **MCP server**: `claude mcp list`, plus `~/.claude.json` (user and per-project `mcpServers`) and any
  `.mcp.json` in the user's projects, for an entry whose command runs `mindslice ... mcp`. Remove it with
  `claude mcp remove <name> -s <scope>`. Note the `-w` path it used: if it differs from the plugin's
  workspace, ask which one the user wants to keep (Step 3).
- **Hooks**: `~/.claude/settings.json`, `.claude/settings.json` and `.claude/settings.local.json` in their
  projects, for `SessionStart` (or other) hooks that run `mindslice ... boot`.
- **Standing rule**: `~/.claude/CLAUDE.md` and project `CLAUDE.md` files, for the paragraph that tells the
  agent to call the MindSlice server's `manifest` tool. The plugin's MCP server instructions replace it.
- **The PyPI/checkout `mindslice` command** itself can stay; the plugin does not use it. Removing a
  `MINDSLICE_WORKSPACE` export from a shell profile is worth suggesting: it overrides the plugin's choice of
  workspace for every `mindslice` command.

Then start a new session and run `mindslice plugin-status` and the Step 4 checks again.
