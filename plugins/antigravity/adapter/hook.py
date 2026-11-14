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


def _wrap(message):
    return json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": message}}]}, ensure_ascii=False)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data = b""
    if sys.stdin is not None and not sys.stdin.isatty():
        data = sys.stdin.buffer.read()
    err = ""
    code = 0
    try:
        # the environment is inherited as is
        proc = subprocess.run([sys.executable, os.path.join(here, "entry.py"), "hook", "1"], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT)
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        code = proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        out = "[MindSlice plugin could not start] %s\nTell the user MindSlice memory is unavailable in this " \
              "session and why.\n" % exc
    if err:
        sys.stderr.write(err)
        sys.stderr.flush()
    text = out.strip()
    result = None
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                result = text
        except ValueError:
            result = None
    if result is None:
        if text:
            result = _wrap(text)
        elif code != 0:
            detail = (err.strip().splitlines() or ["exit status %d" % code])[-1]
            result = _wrap("[MindSlice plugin could not start] %s\nTell the user MindSlice memory is unavailable in "
                           "this session and why." % detail)
        else:
            result = "{}"
    sys.stdout.buffer.write((result + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
