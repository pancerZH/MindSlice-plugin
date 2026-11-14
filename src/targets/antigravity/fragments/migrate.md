If MindSlice was set up by hand before (the `mindslice-setup` skill or the README), the old configuration
now delivers the memory a second time and exposes a second set of tools. Look for it, show the user what
you found, and remove it **only after they agree**, editing surgically so every other entry stays valid:

- **MCP server**: `~/.gemini/config/mcp_config.json`, and `.agents/mcp_config.json` in the projects the user
  names, for a server whose command runs `mindslice ... mcp` (the plugin's own server lives inside the plugin
  folder, not in these files). `agy mcp list` shows the configured servers and `agy mcp remove <name>` removes
  one. Note the `-w` path it used: if it differs from the plugin's workspace, ask which one the user wants to
  keep (Step 3).
- **Hooks**: `~/.gemini/config/hooks.json` and `.agents/hooks.json`, for a hook that runs `mindslice ... boot`.
- **Standing rule**: `~/.gemini/GEMINI.md`, `~/.gemini/config/` rules and project `GEMINI.md`/`AGENTS.md`
  files, for the paragraph that tells the agent to call the MindSlice server's `manifest` tool. The plugin's
  own rule (`rules/AGENTS.md`) replaces it.
- **The PyPI/checkout `mindslice` command** can stay, but it comes before the plugin's command on the
  terminal tool's PATH (the plugin's `bin/` is appended last) and does not know the plugin's workspace: if
  `command -v mindslice` does not print a path inside the plugin folder, find the plugin's own binary with
  `which -a mindslice` (typically `~/.gemini/config/plugins/mindslice/bin/mindslice`) and call that full path,
  or uninstall the other one with the user's agreement. Removing a `MINDSLICE_WORKSPACE` export from a shell
  profile is worth suggesting: it overrides the plugin's choice of workspace for every `mindslice` command.

Do not edit `~/.gemini/config/config.json` (it holds the plugin settings and permission grants; Antigravity
writes it itself). Then start a new conversation and run `mindslice plugin-status` and the Step 4 checks again.
