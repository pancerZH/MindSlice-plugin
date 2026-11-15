"""Engine provisioning: make the pinned MindSlice release importable, installing it from PyPI on first use.

The plugin does not ship the engine. ``adapter/target.json`` pins one release (version, wheel URL, sha256);
the first plugin process that needs it (a hook slot, the MCP server or the CLI) downloads that wheel, checks
its sha256 and unpacks it into ``<plugin data>/engine/<version>/``. MindSlice is a pure-Python wheel with no
dependencies, so unpacking it is the whole installation: no pip, venv or uv needed (system Pythons often lack
them). The plugin data directory survives plugin updates, so this happens once per engine version.

Where the engine comes from, in order:

1. ``MINDSLICE_PLUGIN_ENGINE_DIR``: a directory that contains ``mindslice/`` (development; used unchecked).
2. ``<plugin data>/engine/<version>/`` from an earlier run (its marker names the pinned sha256).
3. A ``mindslice`` already installed for this interpreter at exactly the pinned version (offline machines:
   ``python3.12 -m pip install --user mindslice==<version>``).
4. The pinned wheel: from ``MINDSLICE_PLUGIN_WHEEL`` (a local file) if set, else its PyPI URL.

Runs only on Python >= 3.12 (``entry.py`` checks first) and imports nothing from the engine.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MARKER = ".installed.json"
DOWNLOAD_TIMEOUT = 20.0
LOCK_WAIT = 25.0  # below the hosts' hook timeout (Claude: 30 s in hooks.json)


class EngineUnavailable(Exception):
    """The pinned engine could not be made available; the message says how to fix it."""


def _ready(path: Path, spec: dict[str, Any]) -> bool:
    try:
        marker = json.loads((path / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(marker, dict) and marker.get("sha256") == spec["sha256"]
            and (path / "mindslice" / "__init__.py").is_file())


def _preinstalled(version: str) -> bool:
    try:
        return importlib.util.find_spec("mindslice") is not None and importlib.metadata.version("mindslice") == version
    except (importlib.metadata.PackageNotFoundError, ImportError, ValueError):
        return False


def _fetch(spec: dict[str, Any]) -> bytes:
    local = os.environ.get("MINDSLICE_PLUGIN_WHEEL", "").strip()
    source = local or spec["url"]
    try:
        if local:
            data = Path(local).read_bytes()
        else:
            req = urllib.request.Request(spec["url"], headers={"User-Agent": "mindslice-plugin"})
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:  # honours HTTPS_PROXY etc.
                data = resp.read()
    except (OSError, ValueError) as exc:
        raise EngineUnavailable(_help(spec, f"could not download {source}: {exc}")) from None
    digest = hashlib.sha256(data).hexdigest()
    if digest != spec["sha256"]:
        raise EngineUnavailable(_help(spec, f"{source} has sha256 {digest}, expected {spec['sha256']}; refusing it"))
    return data


def _unpack(data: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        for info in wheel.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise EngineUnavailable(f"unsafe path in the MindSlice wheel: {info.filename!r}")
            if not (name.parts[0] == "mindslice" or name.parts[0].endswith(".dist-info")):
                continue
            target = dest.joinpath(*name.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wheel.read(info))


class _Lock:
    """Exclusive lock on a file, released by the OS if the process dies: ``fcntl.flock`` on POSIX, a one-byte
    ``msvcrt.locking`` range on Windows."""

    def __init__(self, path: Path, timeout: float) -> None:
        self.path, self.timeout, self.fd = path, timeout, None

    def _try(self) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def __enter__(self) -> "_Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self.timeout
        while not self._try():
            if time.monotonic() >= deadline:
                os.close(self.fd)
                self.fd = None
                raise EngineUnavailable("timed out waiting for another plugin process to install the "
                                        "MindSlice engine; start a new session")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc: object) -> None:
        if self.fd is None:
            return
        if os.name == "nt":
            import msvcrt

            try:
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(self.fd)  # on POSIX, closing releases the flock
        self.fd = None


def _help(spec: dict[str, Any], problem: str) -> str:
    return (f"the MindSlice engine {spec['version']} is not installed yet: {problem}. Connect to the internet "
            f"(or set HTTPS_PROXY) and start a new session; or install it yourself with "
            f"`python3.12 -m pip install --user mindslice=={spec['version']}`, or download {spec['url']} and set "
            "MINDSLICE_PLUGIN_WHEEL to the file")


def ensure_engine(spec: dict[str, Any], data_dir: Path) -> Path | None:
    """The directory to put on ``sys.path`` for the pinned engine, or None when it is already importable."""
    override = os.environ.get("MINDSLICE_PLUGIN_ENGINE_DIR", "").strip()
    if override:
        path = Path(override)
        if not (path / "mindslice" / "__init__.py").is_file():
            raise EngineUnavailable(f"MINDSLICE_PLUGIN_ENGINE_DIR={override} has no mindslice/ package")
        return path
    root = data_dir / "engine"
    path = root / spec["version"]
    if _ready(path, spec):
        return path
    if _preinstalled(spec["version"]):
        return None
    with _Lock(root / ".install.lock", LOCK_WAIT):
        if _ready(path, spec):  # another process finished while we waited
            return path
        data = _fetch(spec)
        tmp = root / f".tmp-{spec['version']}-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            tmp.mkdir(parents=True)
            _unpack(data, tmp)
            (tmp / MARKER).write_text(json.dumps({"version": spec["version"], "sha256": spec["sha256"],
                                                  "url": spec["url"]}) + "\n", encoding="utf-8")
            if path.exists():  # a broken earlier attempt
                shutil.rmtree(path)
            os.replace(tmp, path)
        except OSError as exc:
            if _ready(path, spec):  # someone else completed it (only possible if locking failed)
                return path
            raise EngineUnavailable(_help(spec, f"could not be unpacked into {root}: {exc}")) from None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return path
