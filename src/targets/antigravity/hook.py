#!/usr/bin/env python3
"""Antigravity SessionStart hook: ``entry.py hook 1``, its output always handed to Antigravity as JSON.

The driver prints ``{"injectSteps": [...]}`` itself. But when the plugin cannot start at all (no Python 3.12+,
or the engine cannot be installed), ``entry.py`` reports it in plain text before any driver code runs; this
wrapper turns that text into a system message so the model can tell the user. Kept parseable by old Pythons
(the ``python3`` on PATH may be older than the 3.12 that ``entry.py`` then finds and switches to).
"""

import json
import os
import subprocess
import sys

TIMEOUT = 55  # below the hook's timeout in hooks.json


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data = b""
    if sys.stdin is not None and not sys.stdin.isatty():
        data = sys.stdin.buffer.read()
    try:
        # the environment is inherited as is
        proc = subprocess.run([sys.executable, os.path.join(here, "entry.py"), "hook", "1"], input=data,
                              stdout=subprocess.PIPE, timeout=TIMEOUT)
        out = proc.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as exc:
        out = "[MindSlice plugin could not start] %s\nTell the user MindSlice memory is unavailable in this " \
              "session and why.\n" % exc
    text = out.strip()
    if text.startswith("{"):
        result = text
    elif text:
        result = json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": text}}]}, ensure_ascii=False)
    else:
        result = "{}"
    sys.stdout.buffer.write((result + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
