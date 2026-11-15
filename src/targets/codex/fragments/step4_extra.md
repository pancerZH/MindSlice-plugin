### Codex: the new-session checks

`codex exec` starts a one-shot session that loads the same plugins, hooks and MCP servers as one the user
opens, so run the checks through it yourself (from the user's project directory, with stdin closed, or it
waits for more input). It runs only hooks the user has trusted. `codex exec` cannot forbid single tools, so ask
the model not to call any and check that its answer names no tool call; a correct phrase can then only come
from the startup pages:

```bash
codex exec "Without calling any tool: what is the phrase in your MindSlice always-loaded memory? Answer NONE if you do not have one." < /dev/null
```

For the memory lookup, ask a question only a card can answer, without that restriction, and check the answer
used the MindSlice `search` or `read` tool. Plant and remove the temporary standing card with
`<mindslice_bin> write ... --load always --no-stage` and `--op delete` as `doctor` describes. A compaction
cannot be triggered from `codex exec`: hand the user that check (run `/compact` in a long session, then ask
for the phrase again).

### Optional: `mindslice` in the user's own terminal

If the user wants the command in their own terminal (for example to run `mindslice review` themselves), offer
to link the plugin's launcher, after showing them the command:

```bash
mkdir -p ~/.local/bin && ln -sf "<mindslice_bin>" ~/.local/bin/mindslice
```

The launcher's path does not change between plugin versions (the plugin refreshes it at every session start),
so the link keeps working after updates; uninstalling the plugin leaves it dangling. Skip it when the user
already has a `mindslice` installed from PyPI or a checkout. On Windows, cmd and PowerShell use the
`mindslice.cmd` next to the launcher.
