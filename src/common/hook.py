#!/usr/bin/env python3
"""SessionStart hook of the hosts that take a hook's output as JSON (Antigravity, Codex): ``entry.py hook 1``, its
output always handed to the host in the host's JSON shape.

The driver prints that JSON itself. But when the plugin cannot start at all (no Python 3.12+, or the engine cannot
be installed), ``entry.py`` reports it in plain text before any driver code runs (and Codex parses text that starts
with "[" as JSON and fails the hook); this wrapper turns that text, or the last line of a crash that only wrote to
stderr, into a message for the model so it can tell the user. Kept parseable by old Pythons (the ``python3`` on PATH
may be older than the 3.12 that ``entry.py`` then finds and switches to).
"""

import json
import os
import subprocess
import sys

TIMEOUT = 55  # below the hook's timeout in the host's hooks.json


def _host(here):
    """``(wrap, nothing)`` for the host this copy was built for (``target.json``): how it takes a message for the
    model, and what it takes when there is none."""
    try:
        with open(os.path.join(here, "target.json")) as fh:
            target = json.load(fh).get("target")
    except (OSError, ValueError):
        target = None
    if target == "codex":
        return (lambda m: {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": m}}), ""
    return (lambda m: {"injectSteps": [{"systemMessage": {"systemMessage": m}}]}), "{}"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    wrap, nothing = _host(here)
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
            message = text
        elif code != 0:
            detail = (err.strip().splitlines() or ["exit status %d" % code])[-1]
            message = ("[MindSlice plugin could not start] %s\nTell the user MindSlice memory is unavailable in "
                       "this session and why." % detail)
        else:
            message = None
        result = nothing if message is None else json.dumps(wrap(message), ensure_ascii=False)
    if result:
        sys.stdout.buffer.write((result + "\n").encode("utf-8"))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
