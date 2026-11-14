## Antigravity plugin: running Forge sessions

When Forge's `--harness-cmd` starts `agy -p` sessions, those sessions load this plugin too, and with it the
user's personal memory. Isolate them: Forge runs the command without a shell, so set the variable through
`env`:

```bash
--harness-cmd 'env MINDSLICE_PLUGIN_ISOLATE=1 agy -p {message}'
```

With `MINDSLICE_PLUGIN_ISOLATE=1` the plugin's hook injects nothing, its MCP server exposes no tools, and the
`mindslice` command no longer falls back to the plugin's workspace (it stays available for Forge's own calls
with `-w`).
