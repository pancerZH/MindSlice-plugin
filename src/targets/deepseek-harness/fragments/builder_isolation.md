## DeepSeek Harness plugin: running isolated Forge sessions

When Forge starts nested agent sessions that must not see your personal memory, set
`MINDSLICE_PLUGIN_ISOLATE=1` in their environment. With `MINDSLICE_PLUGIN_ISOLATE=1` the plugin injects no
standing memory, its MCP server exposes no tools, and the `mindslice` command no longer falls back to the
plugin's workspace (it stays available for Forge's own calls with `-w`).
