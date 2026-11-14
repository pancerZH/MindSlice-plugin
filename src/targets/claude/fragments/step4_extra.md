### Claude Code: the new-session checks

`claude -p` starts a one-shot session that loads the same plugins, hooks and MCP servers as one the user
opens, so run the checks through it yourself. For the startup check, forbid the memory tools, so a correct
answer can only come from the startup pages:

```bash
claude -p "Without calling any tool: what is the phrase in your MindSlice always-loaded memory? Answer NONE if you do not have one." \
  --disallowedTools "mcp__plugin_mindslice_mindslice__manifest,mcp__plugin_mindslice_mindslice__search,mcp__plugin_mindslice_mindslice__read"
```

For the memory lookup, ask a question only a card can answer, without that restriction, and check the
answer used `mcp__plugin_mindslice_mindslice__search` or `read`. Plant and remove the temporary
standing card with `<mindslice_bin> write ... --load always --no-stage` and `--op delete` as `doctor`
describes. A compaction cannot be triggered from `claude -p`: hand the user that check (run `/compact` in a
long session, then ask for the phrase again).

### Optional: `mindslice` in the user's own terminal

The plugin's command is only on the Bash tool's `PATH`. If the user wants it in their own terminal (for
example to run `mindslice review` themselves), offer to link it, after showing them the command:

```bash
mkdir -p ~/.local/bin && ln -sf "$(command -v mindslice)" ~/.local/bin/mindslice
```

The link points into the plugin's versioned cache directory, so it must be recreated after a plugin update.
Skip it when the user already has a `mindslice` installed from PyPI or a checkout.

On Windows, Git Bash can use the same link. For cmd and PowerShell, give the user the full path of the
plugin's `mindslice.cmd` instead (`cygpath -w "$(command -v mindslice).cmd"` in the Bash tool prints it); it
also moves with each plugin update.
