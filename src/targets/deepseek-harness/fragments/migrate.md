If MindSlice was set up by hand before, the old configuration now delivers the memory a second time or
exposes a second set of MCP tools. Look for it, show the user what you found, and remove it **only after they
agree**, editing surgically so every other entry stays valid:

- **Manual MCP server**: check `$DSH_HOME/cordis.patch.yml` and `$DSH_HOME/profiles/<profile>/cordis.patch.yml`
  (and DeepSeek Harness MCP settings) for a `dsh-mcp-client` or `mcp-manager` `mindslice` entry other than
  this plugin (`dsh-mindslice`). Note any `-w` path it used: if it differs from the plugin's workspace, ask
  which one the user wants to keep (Step 3).
- **Manual prompt / hooks**: check `$DSH_HOME/cordis.patch.yml`, `$DSH_HOME/profiles/<profile>/cordis.patch.yml`,
  or `hooks-claude-code` / `hooks-codex` configs for a rule or hook running `mindslice ... boot`.
- **Standing rule**: check `~/.dsh/AGENTS.md` (or project `AGENTS.md` / `CLAUDE.md`) for a paragraph telling
  the agent to call the MindSlice server's `manifest` tool. The plugin's standing memory pages and MCP server
  instructions replace it.
- **Manual skills**: check `~/.dsh/skills/` or `~/.agents/skills/` for older `mindslice-*` copies if the user
  no longer wants them overriding the bundled skills.
- **The PyPI/checkout `mindslice` command** itself can stay; the plugin does not use it. Removing a
  `MINDSLICE_WORKSPACE` environment variable is worth suggesting: it overrides the plugin's choice of
  workspace for every `mindslice` command.

Then start a new session and run `mindslice plugin-status` and the Step 4 checks again.
