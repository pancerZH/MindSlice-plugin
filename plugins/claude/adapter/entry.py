#!/usr/bin/env python3
"""MindSlice plugin entry point: Python >= 3.12 bootstrap, the pinned engine (``provision``), then ``core``.

This file must stay parseable by Python 3.8 (macOS GUI apps often start ``/usr/bin/python3`` 3.9,
Ubuntu 22.04 ships 3.10): no ``match``, no ``X | Y`` annotations, no walrus at module level.

Subcommands (see ``core.main``): ``hook <driver-args...>``, ``mcp [--workspace DIR]``,
``plugin-status``; anything else is forwarded to the upstream ``mindslice`` CLI.
"""

import os
import re
import subprocess
import sys

MIN_VERSION = (3, 12)
REEXEC_FLAG = "_MINDSLICE_REEXEC"
WINDOWS = os.name == "nt"
SEARCH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/.pyenv/shims")
NAMES = ("python3.14", "python3.13", "python3.12", "python3")
WINDOWS_NAMES = ("python3.14.exe", "python3.13.exe", "python3.12.exe", "python.exe", "python3.exe")
WINDOWS_VERSIONS = ("314", "313", "312")
PROBE = "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
_PY_LIST_PATH = re.compile(r"([A-Za-z]:[\\/].*?\.exe)\s*$", re.I)


def parse_py_list(text):
    """Interpreter paths from ``py -0p`` output (any launcher generation), newest first as listed."""
    paths = []
    for line in text.splitlines():
        m = _PY_LIST_PATH.search(line.strip())
        if m:
            paths.append(m.group(1))
    return paths


def _windows_paths():
    try:
        out = subprocess.run(["py", "-0p"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for path in parse_py_list(out):
        yield path
    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python"),
             os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
    for version in WINDOWS_VERSIONS:
        for root in roots:
            if root:
                yield os.path.join(root, "Python" + version, "python.exe")
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    for name in WINDOWS_NAMES:
        for d in dirs:
            yield os.path.join(d, name)


def _posix_paths():
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    dirs += [os.path.expanduser(d) for d in SEARCH_DIRS]
    for name in NAMES:
        for d in dirs:
            yield os.path.join(d, name)


def _candidates():
    seen = set()
    for path in (_windows_paths() if WINDOWS else _posix_paths()):
        real = os.path.normcase(os.path.realpath(path))
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


def _relaunch(exe, env):
    argv = [exe, os.path.abspath(__file__)] + sys.argv[1:]
    if WINDOWS:
        # os.exec* on Windows starts a new process and ends this one, so the host would see its MCP server
        # or hook exit at once. Run the child on the inherited stdio and pass its exit code on instead.
        try:
            sys.exit(subprocess.call(argv, env=env))
        except KeyboardInterrupt:
            sys.exit(130)
    os.execve(exe, argv, env)


def _bootstrap():
    if sys.version_info >= MIN_VERSION:
        os.environ.pop(REEXEC_FLAG, None)
        return
    if os.environ.get(REEXEC_FLAG) != "1":
        me = os.path.normcase(os.path.realpath(sys.executable or ""))
        for exe in _candidates():
            if os.path.normcase(os.path.realpath(exe)) == me or not _usable(exe):
                continue
            env = dict(os.environ)
            env[REEXEC_FLAG] = "1"
            _relaunch(exe, env)
    where = ("python.org installs (found with the py launcher), %LOCALAPPDATA%\\Programs\\Python and PATH are "
             "searched" if WINDOWS else
             "python3.12 on PATH, Homebrew, ~/.local/bin or pyenv are searched")
    _fail("needs Python >= 3.12 (found %d.%d at %s); install Python 3.12+ (%s) and restart the session."
          % (sys.version_info[0], sys.version_info[1], sys.executable, where))


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
