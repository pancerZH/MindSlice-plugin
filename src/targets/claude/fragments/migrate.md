If MindSlice was set up by hand before (the `mindslice-setup` skill or the README), the old configuration
now delivers the memory a second time and exposes a second set of tools. Look for it, show the user what
you found, and remove it **only after they agree**, editing surgically so every other entry stays valid:

- **MCP server**: run `claude mcp list` (in each project the user names, too: project and local servers
  show only there) and look for a server other than `plugin:mindslice:mindslice` whose command runs
  `mindslice ... mcp`; `claude mcp get <name>` shows its command and scope. Remove it with
  `claude mcp remove <name> -s <scope>`. Note the `-w` path it used: if it differs from the plugin's
  workspace, ask which one the user wants to keep (Step 3).
- **Hooks**: ask the user to open `/hooks` and look under `SessionStart` (and other events) for a hook that
  runs `mindslice ... boot` and is not the plugin's, then delete it there. Do not read Claude's own settings
  or configuration files yourself: they can hold the user's credentials.
- **Standing rule**: `~/.claude/CLAUDE.md` and project `CLAUDE.md` files, for the paragraph that tells the
  agent to call the MindSlice server's `manifest` tool. The plugin's MCP server instructions replace it.
- **The PyPI/checkout `mindslice` command** itself can stay; the plugin does not use it. Removing a
  `MINDSLICE_WORKSPACE` export from a shell profile is worth suggesting: it overrides the plugin's choice of
  workspace for every `mindslice` command.

Then start a new session and run `mindslice plugin-status` and the Step 4 checks again.
