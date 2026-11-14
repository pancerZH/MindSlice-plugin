#!/usr/bin/env python3
"""MindSlice plugin entry point: Python >= 3.12 bootstrap, the pinned engine (``provision``), then ``core``.

This file must stay parseable by Python 3.8 (macOS GUI apps often start ``/usr/bin/python3`` 3.9,
Ubuntu 22.04 ships 3.10): no ``match``, no ``X | Y`` annotations, no walrus at module level.

Subcommands (see ``core.main``): ``hook <driver-args...>``, ``mcp [--workspace DIR]``,
``plugin-status``; anything else is forwarded to the upstream ``mindslice`` CLI.
"""

import os
import subprocess
import sys

MIN_VERSION = (3, 12)
REEXEC_FLAG = "_MINDSLICE_REEXEC"
SEARCH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/.pyenv/shims")
NAMES = ("python3.14", "python3.13", "python3.12", "python3")
PROBE = "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"


def _candidates():
    seen = set()
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    dirs += [os.path.expanduser(d) for d in SEARCH_DIRS]
    for name in NAMES:
        for d in dirs:
            path = os.path.join(d, name)
            real = os.path.realpath(path)
            if real in seen or not os.path.isfile(path) or not os.access(path, os.X_OK):
                continue
            seen.add(real)
            yield path


def _usable(exe):
    try:
        return subprocess.run([exe, "-c", PROBE], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _fail(message):
    sys.stderr.write("mindslice plugin: " + message + "\n")
    # A SessionStart hook's stdout is what the model sees: say it there too, once (slot 1).
    if sys.argv[1:3] == ["hook", "1"]:
        sys.stdout.write("[MindSlice plugin could not start] " + message + "\n"
                         "Tell the user MindSlice memory is unavailable in this session and why.\n")
        sys.exit(0)
    sys.exit(1)


def _bootstrap():
    if sys.version_info >= MIN_VERSION:
        os.environ.pop(REEXEC_FLAG, None)
        return
    if os.environ.get(REEXEC_FLAG) != "1":
        me = os.path.realpath(sys.executable or "")
        for exe in _candidates():
            if os.path.realpath(exe) == me or not _usable(exe):
                continue
            env = dict(os.environ)
            env[REEXEC_FLAG] = "1"
            os.execve(exe, [exe, os.path.abspath(__file__)] + sys.argv[1:], env)
    _fail("needs Python >= 3.12 (found %d.%d at %s); install Python 3.12+ (python3.12 on PATH, Homebrew, "
          "~/.local/bin or pyenv are searched) and restart the session."
          % (sys.version_info[0], sys.version_info[1], sys.executable))


def main():
    _bootstrap()
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import json
    from pathlib import Path

    import driver
    import provision

    with open(os.path.join(here, "target.json"), encoding="utf-8") as fh:
        spec = json.load(fh)["engine"]
    try:
        engine = provision.ensure_engine(spec, Path(driver.plugin_data_dir()))
    except provision.EngineUnavailable as exc:
        _fail(str(exc))
    if engine is not None:
        sys.path.insert(0, str(engine))
        # For subprocesses such as `doctor`'s `sys.executable -m mindslice` handshake.
        old = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = str(engine) + (os.pathsep + old if old else "")
    import core  # noqa: E402  (needs the engine on sys.path)

    sys.exit(core.main(sys.argv[1:]))


if __name__ == "__main__":
    main()
