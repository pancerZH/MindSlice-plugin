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
    *) self=$(dirname -- "$self")/$link ;;
  esac
done
here=$(CDPATH= cd -- "$(dirname -- "$self")" && pwd)
entry="$here/@ENTRY@"
## On Windows (Git Bash), py comes first: python3 is often the Microsoft Store stub. Elsewhere a `py` on PATH
## may be an unrelated tool (pip's pythonpy), and exec leaves no fallback, so it is not tried at all.
pythons="python3 python"
if [ "${OS:-}" = "Windows_NT" ]; then
  pythons="py python3 python"
  if command -v cygpath >/dev/null 2>&1; then
    entry=$(cygpath -m "$entry")
  fi
fi
for py in $pythons; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" "$entry" @ARGS@
  fi
done
echo "mindslice plugin: Python 3.12 or newer is required" >&2
exit 1
