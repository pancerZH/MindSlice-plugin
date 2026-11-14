"""Engine provisioning from the pinned wheel (provision.py)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import helpers
from helpers import ENTRY, PluginTestCase

import provision


def wheel(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


GOOD = wheel({"mindslice/__init__.py": b'__version__ = "9.9.9"\n',
              "mindslice-9.9.9.dist-info/METADATA": b"Metadata-Version: 2.1\nName: mindslice\nVersion: 9.9.9\n"})


class ProvisionTest(PluginTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("MINDSLICE_PLUGIN_ENGINE_DIR", None)
        self.whl = self.tmp / "mindslice-9.9.9-py3-none-any.whl"
        self.whl.write_bytes(GOOD)
        self.spec = {"version": "9.9.9", "url": self.whl.as_uri(), "sha256": hashlib.sha256(GOOD).hexdigest()}
        self.data = self.tmp / "data"

    def test_install_then_reuse(self) -> None:
        path = provision.ensure_engine(self.spec, self.data)
        self.assertEqual(path, self.data / "engine" / "9.9.9")
        self.assertTrue((path / "mindslice" / "__init__.py").is_file())
        self.assertTrue((path / "mindslice-9.9.9.dist-info" / "METADATA").is_file())
        self.whl.unlink()  # cached: no second fetch
        self.assertEqual(provision.ensure_engine(self.spec, self.data), path)

    def test_concurrent_installs(self) -> None:
        with ThreadPoolExecutor(6) as pool:
            paths = set(pool.map(lambda _: provision.ensure_engine(self.spec, self.data), range(6)))
        self.assertEqual(paths, {self.data / "engine" / "9.9.9"})
        leftovers = [p.name for p in (self.data / "engine").iterdir() if p.name.startswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_wrong_hash_refused(self) -> None:
        spec = dict(self.spec, sha256="0" * 64)
        with self.assertRaises(provision.EngineUnavailable) as ctx:
            provision.ensure_engine(spec, self.data)
        self.assertIn("refusing it", str(ctx.exception))
        self.assertFalse((self.data / "engine" / "9.9.9").exists())

    def test_unreachable(self) -> None:
        spec = dict(self.spec, url=(self.tmp / "missing.whl").as_uri())
        with self.assertRaises(provision.EngineUnavailable) as ctx:
            provision.ensure_engine(spec, self.data)
        self.assertIn("pip install --user mindslice==9.9.9", str(ctx.exception))

    def test_local_wheel_override(self) -> None:
        spec = dict(self.spec, url="https://example.invalid/never-fetched.whl")
        os.environ["MINDSLICE_PLUGIN_WHEEL"] = str(self.whl)
        self.assertTrue((provision.ensure_engine(spec, self.data) / "mindslice").is_dir())

    def test_unsafe_paths_refused(self) -> None:
        bad = wheel({"mindslice/__init__.py": b"", "../evil.py": b"x"})
        self.whl.write_bytes(bad)
        spec = dict(self.spec, sha256=hashlib.sha256(bad).hexdigest())
        with self.assertRaises(provision.EngineUnavailable):
            provision.ensure_engine(spec, self.data)
        self.assertFalse((self.tmp / "evil.py").exists())

    def test_marker_must_match_the_pin(self) -> None:
        provision.ensure_engine(self.spec, self.data)
        other = wheel({"mindslice/__init__.py": b'__version__ = "9.9.9"  # rebuilt\n'})
        self.whl.write_bytes(other)
        spec = dict(self.spec, sha256=hashlib.sha256(other).hexdigest())
        path = provision.ensure_engine(spec, self.data)  # the old copy does not satisfy the new pin
        self.assertIn(b"rebuilt", (path / "mindslice" / "__init__.py").read_bytes())

    def test_entry_reports_failure_in_hook_slot_1(self) -> None:
        # a fresh data dir, offline, no preinstalled engine: slot 1 tells the model, exit 0; the CLI exits 1
        pinned = json.loads((helpers.PLUGIN / "adapter" / "target.json").read_text())["engine"]["version"]
        probe = subprocess.run([sys.executable, "-c", "import importlib.metadata as m; print(m.version('mindslice'))"],
                               capture_output=True, text=True,
                               env={k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT")} | {"PYTHONNOUSERSITE": "1"})
        if probe.stdout.strip() == pinned:
            self.skipTest(f"mindslice {pinned} is installed for this interpreter")
        env = {"MINDSLICE_PLUGIN_WHEEL": str(self.tmp / "nope.whl"), "PYTHONNOUSERSITE": "1"}
        r = self.run_entry("hook", "1", env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("[MindSlice plugin could not start]", r.stdout)
        self.assertEqual(self.run_entry("status", env=env).returncode, 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
