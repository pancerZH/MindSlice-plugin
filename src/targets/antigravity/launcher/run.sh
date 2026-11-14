#!/bin/sh
## Template for adapter/mcp and bin/mindslice, filled in by build/build.py, which drops these "##" lines.
## @ENTRY@ is entry.py relative to this script's real directory (links followed), @ARGS@ the arguments.
# MindSlice plugin launcher: runs the plugin's entry.py with the first Python on PATH (entry.py itself switches
# to Python 3.12+ when this one is older).
self=$0
while [ -L "$self" ]; do
  link=$(readlink "$self")
  case $link in
    /*) self=$link ;;
    *) self=$(dirname "$self")/$link ;;
  esac
done
here=$(CDPATH= cd -- "$(dirname -- "$self")" && pwd)
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" "$here/@ENTRY@" @ARGS@
  fi
done
echo "mindslice plugin: Python 3.12 or newer is required" >&2
exit 1
