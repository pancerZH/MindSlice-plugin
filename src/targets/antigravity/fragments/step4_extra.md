### Antigravity: the new-conversation checks

`agy -p` starts a one-shot conversation that loads the same plugins, rules, hooks and MCP servers as one the
user opens, so run the checks through it yourself (from the user's project directory). `agy` cannot forbid
single tools, so ask the model not to call any and check its answer names no tool call; a correct phrase can
then only come from the startup pages:

```bash
agy -p "Without calling any tool: what is the phrase in your MindSlice always-loaded memory? Answer NONE if you do not have one."
```

For the memory lookup, ask a question only a card can answer, without that restriction, and check the
answer used the MindSlice `search` or `read` tool. Plant and remove the temporary standing card with
`<mindslice_bin> write ... --load always --no-stage` and `--op delete` as `doctor` describes. For the
compaction check, the user runs `/compact` in a long conversation and asks for the phrase again: the model
should call `manifest` first, because Antigravity does not re-inject the pages after a compaction.

### Optional: `mindslice` in the user's own terminal

The plugin's command is on the PATH of Antigravity's terminal tool only. If the user wants it in their own
terminal (for example to run `mindslice review` themselves), offer to link it, after showing them the
command (`<plugin_bin>` is the plugin's `.../bin/mindslice` path printed by `command -v mindslice` or
`which -a mindslice`, typically `~/.gemini/config/plugins/mindslice/bin/mindslice`):

```bash
mkdir -p ~/.local/bin && ln -sf "<plugin_bin>" ~/.local/bin/mindslice
```

The link follows reinstalls into the same folder; uninstalling the plugin leaves it dangling. Skip it when
the user already has a `mindslice` installed from PyPI or a checkout. On Windows, cmd and PowerShell use
`<plugin>\bin\mindslice.cmd` directly.
