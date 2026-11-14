#!/bin/sh
## Template for adapter/hook-N and adapter/mcp, filled in by build/build.py, which drops these "##" lines.
## Kept plain for the plugin directory's validator: only CLAUDE_PLUGIN_ROOT, one literal path, fixed
## interpreter names and arguments, no path outside the plugin (not even /dev/null: command -v reports to
## stderr instead), and no comments in the output. py comes first because on Windows python3 is often the
## Microsoft Store placeholder; macOS and Linux rarely have py.
if command -v py >&2; then exec py "${CLAUDE_PLUGIN_ROOT}/adapter/entry.py" @ARGS@; fi
if command -v python3 >&2; then exec python3 "${CLAUDE_PLUGIN_ROOT}/adapter/entry.py" @ARGS@; fi
if command -v python >&2; then exec python "${CLAUDE_PLUGIN_ROOT}/adapter/entry.py" @ARGS@; fi
echo "mindslice plugin: Python 3.12 or newer is required" >&2
exit 1
