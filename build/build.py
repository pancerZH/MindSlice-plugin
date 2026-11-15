#!/usr/bin/env python3
"""Build the host plugins from the locked upstream MindSlice release.

    python3 build/build.py [--target claude|antigravity|codex|all] [--check] [--upstream PATH]

Reads only ``mindslice/``, ``skills/``, ``LICENSE`` and ``NOTICE`` from upstream (at the commit in
``build/upstream.lock``: a ``git archive`` of a local checkout given with ``--upstream``, or the GitHub tarball),
plus ``src/``, and writes ``plugins/<target>/``. The engine is not copied: the plugin installs the PyPI wheel
pinned in the lock at first use. The build checks that this wheel has the lock's sha256 and that its
``mindslice/`` package is byte-identical to the locked commit, so the skills and the engine always agree. ``--check`` rebuilds into a temporary directory and fails if
the committed ``plugins/<target>/`` differs in any byte or executable bit.

Every selection and rewrite rule must match, and every relative Markdown link must resolve, or the build fails.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
COMMON = SRC / "common"  # shared by the hosts: skill rules, the logo, the launchers and hook wrapper of the JSON hosts
LOCK = REPO / "build" / "upstream.lock"
TARGETS = ("claude", "antigravity", "codex")
CACHE = REPO / "build" / ".cache"
MAX_TARGET_BYTES = 256_000  # everything but images (the directory limits images separately)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")  # binary images only: an SVG is text and counts
ICON_MAX_BYTES = 2_000_000

sys.path.insert(0, str(COMMON))
import rules  # noqa: E402

# Top-level paths a plugin directory may contain, per host (anything else is a build bug).
# Claude: no top-level bin/, since Chat and Cowork refuse to install a plugin that has one (the launchers live in
# adapter/). Antigravity: bin/ is what it puts on the agent's PATH; hooks.json, mcp_config.json and rules/ must sit
# at the plugin root. Codex: .codex-plugin/plugin.json names .mcp.json and skills/; hooks/hooks.json is found by
# default; bin/ is not put on any PATH (it is the CLI for whoever knows the plugin folder).
OUTPUT_ALLOWED = {
    "claude": (".claude-plugin/", ".build-info.json", "README.md", "LICENSE", "NOTICE", "hooks/", "adapter/",
               "skills/"),
    "antigravity": ("plugin.json", "mcp_config.json", "hooks.json", "rules/", "bin/", "assets/", ".build-info.json",
                    "README.md", "LICENSE", "NOTICE", "adapter/", "skills/"),
    "codex": (".codex-plugin/", ".mcp.json", "hooks/", "bin/", "assets/", ".build-info.json", "README.md", "LICENSE",
              "NOTICE", "adapter/", "skills/"),
}
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
PLACEHOLDER_RE = re.compile(r"\{\{(host|upstream):([A-Za-z0-9_.-]+)\}\}")


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------
# upstream
# ---------------------------------------------------------------------------
def _allowed(path: str) -> bool:
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in rules.UPSTREAM_ALLOWED)


class Upstream:
    """The whitelisted part of the upstream tree at the locked commit (names of the rest, for link checks)."""

    def __init__(self, files: dict[str, bytes], names: set[str], repo: str, commit: str) -> None:
        self.files = files
        self.names = names
        self.repo = repo.removesuffix(".git").rstrip("/")
        self.commit = commit

    @classmethod
    def from_tar(cls, data: bytes, repo: str, commit: str, strip_top: bool) -> "Upstream":
        files: dict[str, bytes] = {}
        names: set[str] = set()
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar.getmembers():
                name = member.name
                if strip_top:
                    name = name.split("/", 1)[1] if "/" in name else ""
                if not name or not member.isfile():
                    continue
                names.add(name)
                if _allowed(name):
                    fh = tar.extractfile(member)
                    assert fh is not None
                    files[name] = fh.read()
        return cls(files, names, repo, commit)

    @classmethod
    def load(cls, lock: dict[str, str], local: Path | None) -> "Upstream":
        commit = lock["commit"]
        if local is not None:
            try:
                # no eol conversion: Git for Windows defaults to core.autocrlf=true, which git archive applies
                data = subprocess.run(["git", "-C", str(local), "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                                       "archive", "--format=tar", commit],
                                      check=True, capture_output=True).stdout
            except (OSError, subprocess.CalledProcessError) as exc:
                raise BuildError(f"cannot archive {commit} from {local}: {exc}") from None
            return cls.from_tar(data, lock["repo"], commit, strip_top=False)
        m = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", lock["repo"])
        if not m:
            raise BuildError(f"cannot download {lock['repo']}: pass --upstream PATH")
        url = f"https://codeload.github.com/{m.group(1)}/tar.gz/{commit}"
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
        except OSError as exc:
            raise BuildError(f"cannot download {url}: {exc} (or pass --upstream PATH)") from None
        return cls.from_tar(data, lock["repo"], commit, strip_top=True)

    def read(self, path: str) -> bytes:
        if not _allowed(path):
            raise BuildError(f"build may not read upstream path {path!r}")
        if path not in self.files:
            raise BuildError(f"upstream has no {path!r} at {self.commit}")
        return self.files[path]

    def text(self, path: str) -> str:
        return self.read(path).decode("utf-8")

    def listdir(self, prefix: str) -> list[str]:
        return sorted(p for p in self.files if p.startswith(prefix))

    def blob_url(self, path: str) -> str:
        return f"{self.repo}/blob/{self.commit}/{path}"


def load_wheel(lock: dict, local: Path | None) -> bytes:
    """The pinned wheel (a local file, the build cache or PyPI), checked against the lock's sha256."""
    spec = lock["wheel"]
    name = spec["url"].rsplit("/", 1)[-1]
    cached = CACHE / name
    if local is not None:
        data = local.read_bytes()
    elif cached.is_file():
        data = cached.read_bytes()
    else:
        try:
            with urllib.request.urlopen(spec["url"], timeout=60) as resp:
                data = resp.read()
        except OSError as exc:
            raise BuildError(f"cannot download {spec['url']}: {exc} (or pass --wheel PATH)") from None
    digest = hashlib.sha256(data).hexdigest()
    if digest != spec["sha256"]:
        raise BuildError(f"wheel {name} has sha256 {digest}, the lock says {spec['sha256']}")
    if local is None and not cached.is_file():
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return data


def check_wheel(data: bytes, up: "Upstream", version: str) -> None:
    """The wheel's engine package must be the locked commit's ``mindslice/`` package, byte for byte."""
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        files = {n: wheel.read(n) for n in wheel.namelist() if n.startswith("mindslice/") and not n.endswith("/")}
        meta = [n for n in wheel.namelist() if n.endswith(".dist-info/METADATA")]
        metadata = wheel.read(meta[0]).decode("utf-8") if meta else ""
    if f"\nVersion: {version}\n" not in metadata:
        raise BuildError(f"the pinned wheel is not version {version}")
    upstream = {p: up.read(p) for p in up.listdir("mindslice/") if "__pycache__" not in p}
    if files != upstream:
        differ = sorted(p for p in set(files) | set(upstream) if files.get(p) != upstream.get(p))
        raise BuildError(f"the pinned wheel differs from upstream {up.commit[:12]} in: {', '.join(differ[:10])}")


# ---------------------------------------------------------------------------
# text derivation
# ---------------------------------------------------------------------------
def select(text: str, how: str, anchor: str, name: str) -> str:
    lines = text.splitlines(keepends=True)
    if how == "section":
        hits = [i for i, line in enumerate(lines) if line.rstrip("\n") == anchor]
        if len(hits) != 1:
            raise BuildError(f"selection {name!r}: heading {anchor!r} found {len(hits)} times")
        level = len(anchor) - len(anchor.lstrip("#"))
        end = next((j for j in range(hits[0] + 1, len(lines))
                    if re.match(r"#{1,%d} " % level, lines[j])), len(lines))
        return "".join(lines[hits[0]:end]).rstrip("\n")
    if how == "paragraph":
        hits = [i for i, line in enumerate(lines) if line.startswith(anchor)]
        if len(hits) != 1:
            raise BuildError(f"selection {name!r}: paragraph {anchor!r} found {len(hits)} times")
        end = next((j for j in range(hits[0], len(lines)) if not lines[j].strip()), len(lines))
        return "".join(lines[hits[0]:end]).rstrip("\n")
    raise BuildError(f"selection {name!r}: unknown kind {how!r}")


def _applies(when: str | None, flags: dict[str, bool]) -> bool:
    return when is None or flags[when]


def apply_rules(source: str, text: str, flags: dict[str, bool]) -> str:
    for rule in rules.REWRITES:
        if rule["source"] != source or not _applies(rule["when"], flags):
            continue
        if rule["kind"] == "replace":
            n = text.count(rule["old"])
            if n != 1:
                raise BuildError(f"rewrite on {source}: {rule['old'][:60]!r} matched {n} times (expected 1)")
            text = text.replace(rule["old"], rule["new"])
        elif rule["kind"] == "cut":
            a, b = text.count(rule["start"]), text.count(rule["end"])
            if a != 1 or b != 1:
                raise BuildError(f"cut on {source}: start matched {a}, end matched {b} times (expected 1 each)")
            i, j = text.index(rule["start"]), text.index(rule["end"])
            if j <= i:
                raise BuildError(f"cut on {source}: end comes before start")
            text = text[:i] + rule["new"] + text[j:]
        else:
            raise BuildError(f"unknown rewrite kind {rule['kind']!r}")
    for rule in rules.APPENDS:
        if rule["source"] == source and _applies(rule["when"], flags):
            text = text.rstrip("\n") + "\n\n" + rule["new"] + "\n"
    return text


def map_upstream(path: str, skills: dict[str, bool]) -> str | None:
    """The plugin path an upstream skills/ file is published at, or None."""
    m = re.match(r"skills/([^/]+)/(.+)$", path)
    if not m or m.group(1) not in rules.SKILL_DIRS:
        return None
    out = rules.SKILL_DIRS[m.group(1)]
    return f"skills/{out}/{m.group(2)}" if skills.get(out) else None


def rewrite_links(text: str, src_path: str, out_path: str, outputs: set[str], up: Upstream,
                  skills: dict[str, bool]) -> str:
    """Relative links of upstream text at ``src_path``, made valid at ``out_path`` in the plugin: to the published
    copy when there is one, else to the upstream file at the locked commit."""
    def fix(m: re.Match[str]) -> str:
        target = m.group(1)
        if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            return m.group(0)
        path, _, anchor = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(src_path), path))
        if resolved.startswith("../"):
            raise BuildError(f"{src_path}: link {target!r} leaves the upstream tree")
        mapped = map_upstream(resolved, skills)
        if mapped in outputs:
            new = posixpath.relpath(mapped, posixpath.dirname(out_path))
        elif resolved in up.names:
            new = up.blob_url(resolved)
        else:
            raise BuildError(f"{src_path}: link {target!r} points to {resolved}, which upstream does not have")
        return f"]({new}{'#' + anchor if anchor else ''})"

    return LINK_RE.sub(fix, text)


def fill(text: str, fragments: dict[str, str], upstream_parts: dict[str, str], where: str) -> str:
    def sub(m: re.Match[str]) -> str:
        kind, name = m.groups()
        table = fragments if kind == "host" else upstream_parts
        if name not in table:
            raise BuildError(f"{where}: no {kind} part named {name!r}")
        return table[name]

    for _ in range(3):  # fragments may name other fragments
        text = PLACEHOLDER_RE.sub(sub, text)
    if PLACEHOLDER_RE.search(text):
        raise BuildError(f"{where}: unresolved placeholders")
    return text


def check_links(files: dict[str, "OutFile"]) -> None:
    for path, f in files.items():
        if not path.endswith(".md"):
            continue
        text = f.data.decode("utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in LINK_RE.findall(text):
            if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target.partition("#")[0]))
            if resolved not in files:
                raise BuildError(f"dead link in {path}: {target!r}")


# ---------------------------------------------------------------------------
# target build
# ---------------------------------------------------------------------------
@dataclass
class OutFile:
    data: bytes
    executable: bool = False


@dataclass
class Build:
    allowed: tuple[str, ...] = ()
    files: dict[str, OutFile] = field(default_factory=dict)

    def add(self, path: str, data: bytes | str, executable: bool = False) -> None:
        if path in self.files:
            raise BuildError(f"{path} generated twice")
        if not any(path == p or (p.endswith("/") and path.startswith(p)) for p in self.allowed):
            raise BuildError(f"{path} is outside the plugin whitelist")
        self.files[path] = OutFile(data.encode("utf-8") if isinstance(data, str) else data, executable)


def check_icon(data: bytes, where: Path) -> None:
    """The directory's listing icon: a square PNG of 512 to 2048 px per side, under 2 MB."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise BuildError(f"{where} is not a PNG")
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if width != height or not 512 <= width <= 2048:
        raise BuildError(f"{where} is {width}x{height} px; the icon must be square, 512 to 2048 px per side")
    if len(data) >= ICON_MAX_BYTES:
        raise BuildError(f"{where} is {len(data)} bytes; the icon must be under 2 MB")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"



def claude_files(out: Build, tdir: Path, cfg: dict, manifest: dict) -> None:
    """Claude Code: .claude-plugin/plugin.json (MCP server inside), hooks/hooks.json with one command per slot,
    the sh launchers adapter/hook-N and adapter/mcp, adapter/mcp.cmd, the directory icon."""
    out.add(cfg["manifest_path"], _json(manifest))
    hooks = [{"type": "command", "command": cfg["hook_command"].replace("{slot}", str(i)),
              "timeout": cfg["hook_timeout"]} for i in range(1, cfg["hook_slots"] + 1)]
    out.add("hooks/hooks.json", _json({
        "description": "MindSlice: deliver the standing memory at session start, resume, clear and compaction "
                       "(one page per command, all from one snapshot).",
        "hooks": {cfg["hook_event"]: [{"hooks": hooks}]}}))
    # One plain launcher per command, arguments spelled out: the plugin directory follows a command's script only
    # when it uses no variable but CLAUDE_PLUGIN_ROOT (so no "$@", no $OS).
    sh_tpl = "".join(line for line in (tdir / "launcher" / "run.sh").read_text(encoding="utf-8").splitlines(True)
                     if not line.startswith("##"))
    for i in range(1, cfg["hook_slots"] + 1):
        out.add(f"adapter/hook-{i}", sh_tpl.replace("@ARGS@", f"hook {i}").encode())
    out.add("adapter/mcp", sh_tpl.replace("@ARGS@", "mcp").encode(), executable=True)  # run directly by Claude
    cmd_tpl = (tdir / "launcher" / "run.cmd").read_bytes()
    if b"\n" in cmd_tpl.replace(b"\r\n", b""):
        raise BuildError(f"{tdir / 'launcher' / 'run.cmd'} must use CRLF line endings (cmd.exe labels break otherwise)")
    cmd_tpl = b"".join(line for line in cmd_tpl.splitlines(True) if not line.startswith(b"::"))
    out.add("adapter/mcp.cmd", cmd_tpl.replace(b"@ARGS@", b"mcp"))
    out.add("README.md", (tdir / "README.md").read_bytes())
    _add_logo(out, ".claude-plugin/icon.png")  # where the directory and `claude plugin validate` look for it


def _add_logo(out: Build, path: str) -> None:
    logo = COMMON / "logo.png"
    data = logo.read_bytes()
    check_icon(data, logo)
    out.add(path, data)


def _sh_launcher(entry: str, args: str) -> bytes:
    tpl = "".join(line for line in (COMMON / "launcher" / "run.sh").read_text(encoding="utf-8").splitlines(True)
                  if not line.startswith("##"))
    return tpl.replace("@ENTRY@", entry).replace("@ARGS@", args).encode()


def _cmd_launcher(entry: str, args: str) -> bytes:
    src = COMMON / "launcher" / "run.cmd"
    tpl = src.read_bytes()
    if b"\n" in tpl.replace(b"\r\n", b""):
        raise BuildError(f"{src} must use CRLF line endings (cmd.exe labels break otherwise)")
    tpl = b"".join(line for line in tpl.splitlines(True) if not line.startswith(b"::"))
    return tpl.replace(b"@ENTRY@", entry.encode()).replace(b"@ARGS@", args.encode())


def _add_runners(out: Build) -> None:
    """What Antigravity and Codex run: adapter/hook.py (the hook, its output always JSON), the MCP launchers and
    bin/mindslice, the CLI."""
    out.add("adapter/hook.py", (COMMON / "hook.py").read_bytes())
    out.add("adapter/mcp", _sh_launcher("entry.py", "mcp"), executable=True)
    out.add("adapter/mcp.cmd", _cmd_launcher("entry.py", "mcp"))
    out.add("bin/mindslice", _sh_launcher("../adapter/entry.py", '"$@"'), executable=True)
    out.add("bin/mindslice.cmd", _cmd_launcher("..\\adapter\\entry.py", "%*"))


def antigravity_files(out: Build, tdir: Path, cfg: dict, manifest: dict) -> None:
    """Antigravity: plugin.json, mcp_config.json and hooks.json at the plugin root (it loads them nowhere else),
    rules/AGENTS.md (always on), bin/mindslice for the agent's PATH, adapter/hook.py and the MCP launchers."""
    out.add(cfg["manifest_path"], _json(manifest))
    mcp = json.loads((tdir / "mcp_config.json").read_text(encoding="utf-8"))
    out.add("mcp_config.json", _json(mcp))
    out.add("hooks.json", _json({"mindslice": {cfg["hook_event"]: [
        {"type": "command", "command": cfg["hook_command"], "timeout": cfg["hook_timeout"]}]}}))
    _add_runners(out)
    out.add("rules/AGENTS.md", (tdir / "rules" / "AGENTS.md").read_bytes())
    out.add("README.md", (tdir / "README.md").read_bytes())
    _add_logo(out, manifest["logo"])


def codex_files(out: Build, tdir: Path, cfg: dict, manifest: dict) -> None:
    """Codex: .codex-plugin/plugin.json (naming .mcp.json and skills/), hooks/hooks.json with one command (Codex
    substitutes ${PLUGIN_ROOT} itself; the context limit is raised so every page fits in the one hook's output),
    adapter/hook.py, the MCP launchers, bin/mindslice and the listing logo."""
    out.add(cfg["manifest_path"], _json(manifest))
    out.add(".mcp.json", _json(json.loads((tdir / "mcp.json").read_text(encoding="utf-8"))))
    hook = {"type": "command", "command": cfg["hook_command"], "timeout": cfg["hook_timeout"],
            "additionalContextLimit": cfg["hook_context_limit"], "statusMessage": "Loading MindSlice memory"}
    out.add("hooks/hooks.json", _json({
        "description": "MindSlice: deliver the standing memory at session start, resume, clear, fork and compaction.",
        "hooks": {cfg["hook_event"]: [{"hooks": [hook]}]}}))
    _add_runners(out)
    out.add("README.md", (tdir / "README.md").read_bytes())
    _add_logo(out, manifest["interface"]["logo"].removeprefix("./"))


HOSTS = {"claude": claude_files, "antigravity": antigravity_files, "codex": codex_files}


def build_target(name: str, up: Upstream, lock: dict[str, str]) -> Build:
    tdir = SRC / "targets" / name
    cfg = json.loads((tdir / "target.json").read_text(encoding="utf-8"))
    manifest = json.loads((tdir / "plugin.json").read_text(encoding="utf-8"))
    version = manifest.get("version", "")
    if not re.fullmatch(re.escape(lock["version"]) + r"-\d+", version):
        raise BuildError(f"{name}: plugin version {version!r} must be '{lock['version']}-<revision>'")
    init = up.text("mindslice/__init__.py")
    m = re.search(r'^__version__ = "([^"]+)"', init, re.M)
    if not m or m.group(1) != lock["version"]:
        raise BuildError(f"upstream __version__ is {m.group(1) if m else None!r}, lock says {lock['version']!r}")

    out = Build(OUTPUT_ALLOWED[cfg.get("host", "claude")])
    out.add("LICENSE", up.read("LICENSE"))
    out.add("NOTICE", up.read("NOTICE"))

    # adapter
    adapter = SRC / "adapter"
    out.add("adapter/entry.py", (adapter / "entry.py").read_bytes(), executable=True)
    out.add("adapter/core.py", (adapter / "core.py").read_bytes())
    out.add("adapter/provision.py", (adapter / "provision.py").read_bytes())
    out.add("adapter/driver.py", (adapter / "drivers" / f"{cfg['driver']}.py").read_bytes())
    out.add("adapter/target.json", _json({"target": cfg["target"], "plugin_version": version,
                                          "engine_version": lock["version"], "page_limit": cfg["page_limit"],
                                          "hook_slots": cfg["hook_slots"],
                                          "engine": {"version": lock["version"], "url": lock["wheel"]["url"],
                                                     "sha256": lock["wheel"]["sha256"]}}))

    HOSTS[cfg.get("host", "claude")](out, tdir, cfg, manifest)

    # skills
    skills = cfg["skills"]
    flags = {"builder": bool(skills.get("slice-builder")), "no_builder": not skills.get("slice-builder")}
    fragments = {p.stem: p.read_text(encoding="utf-8").rstrip("\n") for p in sorted((tdir / "fragments").glob("*.md"))}

    planned: dict[str, tuple[str, str | None]] = {}  # out path -> (kind, upstream source)
    if skills.get("setup"):
        planned["skills/setup/SKILL.md"] = ("setup", None)
        planned["skills/setup/uninstall.md"] = ("target", "uninstall.md")
    if skills.get("review"):
        planned["skills/review/SKILL.md"] = ("common", "skills/review/SKILL.md")
    for upstream_dir in ("slice-maintainer", "slice-builder"):
        if skills.get(upstream_dir):
            for src in up.listdir(f"skills/{upstream_dir}/"):
                mapped = map_upstream(src, skills)
                assert mapped is not None
                planned[mapped] = ("upstream", src)
    outputs = set(planned)

    for out_path, (kind, src) in planned.items():
        if kind == "setup":
            parts = {}
            for sel_name, (sel_file, how, anchor) in rules.SELECTIONS.items():
                text = select(up.text(sel_file), how, anchor, sel_name)
                text = apply_rules(sel_name, text, flags)
                parts[sel_name] = rewrite_links(text, sel_file, out_path, outputs, up, skills)
            template = (SRC / "common" / "setup.md").read_text(encoding="utf-8")
            text = fill(template, fragments, parts, out_path)
        elif kind == "target":
            text = fill((tdir / src).read_text(encoding="utf-8"), fragments, {}, out_path)
        elif kind == "common":
            text = fill((SRC / "common" / src).read_text(encoding="utf-8"), fragments, {}, out_path)
        else:
            text = apply_rules(src, up.text(src), flags)
            text = rewrite_links(text, src, out_path, outputs, up, skills)
            text = fill(text, fragments, {}, out_path)
        out.add(out_path, text)

    check_links(out.files)
    size = sum(len(f.data) for p, f in out.files.items() if not p.lower().endswith(IMAGE_SUFFIXES))
    if size > MAX_TARGET_BYTES:
        raise BuildError(f"{name}: plugin is {size} bytes (limit {MAX_TARGET_BYTES})")

    info = {"target": name, "plugin_version": version,
            "upstream": {"repo": lock["repo"], "commit": lock["commit"], "version": lock["version"],
                         "wheel": lock["wheel"]},
            "files": {p: hashlib.sha256(f.data).hexdigest() for p, f in sorted(out.files.items())}}
    out.add(".build-info.json", _json(info))
    return out


def write_tree(build: Build, dest: Path) -> None:
    for path, f in sorted(build.files.items()):
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f.data)
        os.chmod(target, 0o755 if f.executable else 0o644)


def read_tree(root: Path) -> dict[str, OutFile]:
    found: dict[str, OutFile] = {}
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            found[rel] = OutFile(p.read_bytes(), bool(p.stat().st_mode & 0o100))
    return found


def compare(build: Build, root: Path) -> list[str]:
    have = read_tree(root)
    diffs = []
    for path in sorted(set(have) | set(build.files)):
        a, b = have.get(path), build.files.get(path)
        if a is None:
            diffs.append(f"missing: {path}")
        elif b is None:
            diffs.append(f"unexpected: {path}")
        elif a.data != b.data:
            diffs.append(f"differs: {path}")
        elif a.executable != b.executable and os.name != "nt":  # Windows file systems keep no exec bit
            diffs.append(f"mode differs: {path}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", default="all", choices=TARGETS + ("all",))
    parser.add_argument("--check", action="store_true", help="verify plugins/ matches a fresh build")
    parser.add_argument("--upstream", type=Path, default=os.environ.get("MINDSLICE_UPSTREAM") or None,
                        help="local git checkout of upstream MindSlice (archived at the locked commit)")
    parser.add_argument("--wheel", type=Path, default=None, help="the pinned engine wheel as a local file")
    ns = parser.parse_args(argv)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    targets = TARGETS if ns.target == "all" else (ns.target,)
    try:
        up = Upstream.load(lock, Path(ns.upstream) if ns.upstream else None)
        check_wheel(load_wheel(lock, ns.wheel), up, lock["version"])
        failed = False
        for name in targets:
            build = build_target(name, up, lock)
            cfg = json.loads((SRC / "targets" / name / "target.json").read_text(encoding="utf-8"))
            dest = REPO / cfg["output"]
            if ns.check:
                diffs = compare(build, dest)
                if diffs:
                    failed = True
                    print(f"{name}: {dest.relative_to(REPO)} is out of date:\n  " + "\n  ".join(diffs))
                else:
                    print(f"{name}: up to date ({len(build.files)} files)")
                continue
            with tempfile.TemporaryDirectory(dir=dest.parent if dest.parent.exists() else None) as tmp:
                staging = Path(tmp) / name
                write_tree(build, staging)
                if dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staging), dest)
            size = sum(len(f.data) for f in build.files.values())
            print(f"{name}: wrote {dest.relative_to(REPO)} ({len(build.files)} files, {size} bytes)")
        return 1 if failed else 0
    except BuildError as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
