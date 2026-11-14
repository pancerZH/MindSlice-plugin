"""Host-independent core of the MindSlice plugin.

Everything a host needs except its own calling conventions lives here (the host driver, ``driver.py``,
supplies those): workspace resolution with the non-empty-directory guard, the startup payload and its
paginator, the per-session spool that keeps concurrent hook slots on one snapshot, the plugin MCP server,
``plugin-status`` and the CLI routing rules.

Only standard library and the upstream engine are used: the pinned PyPI release, which ``entry.py`` has made
importable through ``provision.py`` before this module loads. The engine symbols relied on are listed in ``UPSTREAM_CONTRACT`` and checked by the test suite.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import driver
import mindslice
from mindslice import Workspace
from mindslice import __version__ as ENGINE_VERSION
from mindslice.errors import LockTimeoutError, MindSliceError
from mindslice.interfaces.mcp_server import (
    DOCTOR_CLIENT,
    EMPTY_WORKSPACE_HINT,
    INSTRUCTIONS,
    PROTOCOL_VERSIONS,
    TOOLS,
    MCPServer,
    ensure_utf8_stdio,
)
from mindslice.operations.boot import HEADER, render_markdown
from mindslice.storage.locking import WorkspaceLock

ADAPTER_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = ADAPTER_DIR.parent
MOUNTS_FILE = "mounts.toml"

UPSTREAM_CONTRACT = (
    "Workspace", "Workspace.init", "Workspace.discover", "Workspace.boot", "Workspace.table",
    "operations.boot.render_markdown", "operations.boot.HEADER",
    "interfaces.mcp_server.MCPServer", "interfaces.mcp_server.TOOLS", "interfaces.mcp_server.INSTRUCTIONS",
    "interfaces.mcp_server.EMPTY_WORKSPACE_HINT", "interfaces.mcp_server.ensure_utf8_stdio",
    "MCPServer.instructions", "MCPServer._mark_seen", "MCPServer.boot_update", "MCPServer.call_tool",
    "MCPServer._tools_call", "MCPServer.serve", "MCPServer.handle",
    "storage.locking.WorkspaceLock", "interfaces.cli.main",
)


class PluginError(Exception):
    """A plugin-level failure with a message meant for the user (never an upstream `init` hint)."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def utf16_len(text: str) -> int:
    """Length in UTF-16 code units (a character outside the BMP counts 2): never below the character count."""
    return len(text.encode("utf-16-le")) // 2


def target_config() -> dict[str, Any]:
    """Runtime parameters the build wrote for this host (``adapter/target.json``)."""
    return json.loads((ADAPTER_DIR / "target.json").read_text(encoding="utf-8"))


def isolated() -> bool:
    """``MINDSLICE_PLUGIN_ISOLATE=1``: a nested (e.g. Forge) session that must not see the user's memory."""
    return os.environ.get("MINDSLICE_PLUGIN_ISOLATE") == "1"


def clean_value(value: str | None) -> str | None:
    """A configured value, or None when it is unset, blank or an unsubstituted ``${...}`` placeholder."""
    if value is None:
        return None
    value = value.strip()
    if not value or "${" in value:
        return None
    return value


def plugin_data_dir() -> Path:
    path = Path(driver.plugin_data_dir())
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def bin_path() -> Path:
    return PLUGIN_ROOT / "bin" / "mindslice"


# ---------------------------------------------------------------------------
# engine text, rewritten where it contradicts the plugin's delivery (section 5.2)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TextRewrite:
    name: str
    old: str
    reinject: str      # host re-delivers the standing pages after compaction
    no_reinject: str   # host only delivers them at session start


_START_OLD = (
    "Start with manifest() to see the mounted slices, use search() to find relevant cards, and read() an address "
    "for full content (it composes extensions and follows replacements)."
)
_START_NEW = (
    "Your always-loaded cards and these instructions are delivered automatically at session start as "
    "\"MindSlice standing memory\" pages; call manifest(include_always=false) to see the mounted slices, use "
    "search() to find relevant cards, and read() an address for full content (it composes extensions and follows "
    "replacements)."
)
_COMPACT_OLD = (
    "After your context is compacted or summarized, call manifest() again before continuing: its always_loaded is "
    "the current set, and updates delivered in earlier tool results are gone."
)
_COMPACT_NEW = (
    "After your context is compacted, the standing memory pages are delivered again automatically with the current "
    "set (updates delivered in earlier tool results are gone); call manifest(include_always=true) before continuing "
    "only if those pages are missing, incomplete or carry different snapshot ids."
)
_MANIFEST_OLD = "Boot context; call this first in a session, and again after the conversation is compacted."
_MANIFEST_REINJECT = (
    "Boot context. Its instructions and always-loaded cards already arrive at session start and after compaction "
    "as \"MindSlice standing memory\" pages, so call it with include_always=false to browse the slices, and with "
    "include_always=true only when those pages are missing, incomplete or carry different snapshot ids."
)
_MANIFEST_NO_REINJECT = (
    "Boot context. Its instructions and always-loaded cards already arrive at session start as \"MindSlice standing "
    "memory\" pages, so call it with include_always=false to browse the slices; call it again (include_always=true) "
    "after the conversation is compacted."
)

INSTRUCTION_REWRITES = (
    TextRewrite("instructions.start", _START_OLD, _START_NEW, _START_NEW),
    TextRewrite("instructions.compact", _COMPACT_OLD, _COMPACT_NEW, _COMPACT_OLD),
)
MANIFEST_REWRITES = (
    TextRewrite("tools.manifest", _MANIFEST_OLD, _MANIFEST_REINJECT, _MANIFEST_NO_REINJECT),
)


def apply_rewrites(text: str, rules: Iterable[TextRewrite], reinjects: bool) -> str:
    for rule in rules:
        count = text.count(rule.old)
        if count != 1:
            raise PluginError(f"engine text rewrite {rule.name!r} matched {count} times (expected 1); "
                              "the engine's wording changed: update core.py")
        text = text.replace(rule.old, rule.reinject if reinjects else rule.no_reinject)
    return text


def plugin_instructions(reinjects: bool | None = None) -> str:
    return apply_rewrites(INSTRUCTIONS, INSTRUCTION_REWRITES,
                          driver.reinjects_on_compact if reinjects is None else reinjects)


def plugin_tools(reinjects: bool | None = None) -> list[dict[str, Any]]:
    tools = copy.deepcopy(TOOLS)
    manifest = next(t for t in tools if t["name"] == "manifest")
    manifest["description"] = apply_rewrites(manifest["description"], MANIFEST_REWRITES,
                                             driver.reinjects_on_compact if reinjects is None else reinjects)
    return tools


# ---------------------------------------------------------------------------
# workspace resolution and the first-run guard (section 4.5)
# ---------------------------------------------------------------------------
UNSET, MISSING, EMPTY, WORKSPACE, OCCUPIED = "unset", "missing", "empty", "workspace", "occupied"


@dataclass
class Target:
    state: str
    path: Path | None = None
    source: str | None = None


def classify(path: Path) -> str:
    if (path / MOUNTS_FILE).is_file():
        return WORKSPACE
    if not os.path.lexists(path):
        return MISSING
    if not path.is_dir():
        return OCCUPIED
    try:
        next(path.iterdir())
    except StopIteration:
        return EMPTY
    return OCCUPIED


def bridge_path() -> Path:
    return plugin_data_dir() / "active_workspace.json"


def write_bridge(path: Path) -> None:
    try:
        atomic_write(bridge_path(), json.dumps({"workspace": str(path)}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # a convenience for hooks and the CLI, never a reason to fail the server


def read_bridge() -> str | None:
    try:
        value = json.loads(bridge_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value.get("workspace") if isinstance(value, dict) and isinstance(value.get("workspace"), str) else None


def _candidates(entry: str, cli_value: str | None) -> list[tuple[str, Any]]:
    env = os.environ.get
    if entry == "mcp":
        return [("--workspace", lambda: cli_value), ("plugin option", driver.configured_workspace),
                ("MINDSLICE_WORKSPACE", lambda: env("MINDSLICE_WORKSPACE"))]
    if entry == "hook":
        return [("--workspace", lambda: cli_value), ("plugin option", driver.configured_workspace),
                ("active_workspace.json", read_bridge), ("MINDSLICE_WORKSPACE", lambda: env("MINDSLICE_WORKSPACE"))]
    # cli / plugin-status: an explicit MINDSLICE_WORKSPACE wins, as it does for every upstream command (4.6 rule 2)
    return [("--workspace", lambda: cli_value), ("MINDSLICE_WORKSPACE", lambda: env("MINDSLICE_WORKSPACE")),
            ("plugin option", driver.configured_workspace),
            ("MINDSLICE_PLUGIN_WORKSPACE", lambda: env("MINDSLICE_PLUGIN_WORKSPACE")),
            ("active_workspace.json", read_bridge)]


def resolve(entry: str, cli_value: str | None = None) -> Target:
    """The workspace this entry point should serve, by the priority order of section 4.5."""
    for source, get in _candidates(entry, cli_value):
        raw = clean_value(get())
        if raw:
            path = Path(os.path.abspath(os.path.expanduser(raw)))
            return Target(classify(path), path, source)
    return Target(UNSET)


def unset_message() -> str:
    return ("The MindSlice plugin has no memory workspace configured yet, so no memory is loaded in this session "
            "and the MindSlice tools are unavailable. Set \"Memory workspace\" in the plugin's options (run /plugin, "
            "open mindslice, configure) to an existing MindSlice workspace or to a new or empty folder, then start "
            "a new session; or run /mindslice:setup for guided setup.")


def occupied_message(path: Path) -> str:
    return (f"The configured MindSlice memory workspace {path} is not empty and is not a MindSlice workspace "
            f"(no {MOUNTS_FILE}). The plugin left it untouched and loaded no memory. Point the plugin's \"Memory "
            "workspace\" option at an empty folder, a new path or an existing MindSlice workspace (/plugin, or "
            "/mindslice:setup), then start a new session. Do not initialize a workspace inside that folder.")


def ensure_workspace(target: Target) -> Path:
    """The target as an initialized workspace: a missing or empty folder is initialized (the user named it in the
    plugin options); anything else that is not a workspace is refused without writing a byte."""
    if target.state == UNSET or target.path is None:
        raise PluginError(unset_message())
    if target.state == OCCUPIED:
        raise PluginError(occupied_message(target.path))
    if target.state in (MISSING, EMPTY):
        # Hook slots and the MCP server start together: initialize under one lock, re-checking inside it.
        lock = WorkspaceLock(plugin_data_dir() / "init.lock", timeout=30.0)
        try:
            with lock.exclusive():
                state = classify(target.path)
                if state == OCCUPIED:
                    raise PluginError(occupied_message(target.path))
                if state in (MISSING, EMPTY):
                    Workspace.init(target.path).close()
        finally:
            lock.close()
        target.state = WORKSPACE
    return target.path


# ---------------------------------------------------------------------------
# the startup payload (section 4.3)
# ---------------------------------------------------------------------------
@dataclass
class Block:
    text: str
    label: str
    card: dict[str, str] | None = None  # {"address", "title"} for a standing card


def snapshot(path: Path) -> dict[str, Any]:
    with Workspace(path) as ws:
        snap = ws.boot()
        snap["overlay_alias"] = ws.table().overlay.alias
    return snap


def preamble(path: Path) -> str:
    return ("# MindSlice plugin: standing memory\n\n"
            f"Memory workspace: `{path}`\n"
            "These \"MindSlice standing memory\" pages deliver MindSlice's usage instructions and the user's "
            "always-loaded cards in full. Read every page: they are numbered page i/n with one snapshot id, and the "
            "last one ends with a \"complete\" line. You do not need manifest() for this content; call "
            "manifest(include_always=false) to browse the mounted slices.\n"
            + driver.CLI_HINT)


def pending_block(snap: dict[str, Any]) -> str | None:
    items = snap.get("pending_approval") or []
    if not items:
        return None
    alias = snap.get("overlay_alias", "@overlay")
    lines = ["# Changes awaiting the user's approval", "",
             "These staged changes to the always-loaded memory are not active yet:"]
    lines += [f"- {alias}/{i['id']} ({i.get('op', 'write')}): {i['reason']}" for i in items]
    lines += ["", "Mention them to the user once. They take effect only when the user approves them: in this "
              f"session with {driver.REVIEW_COMMAND}, or in their own terminal with "
              f"`{bin_path()} -w <workspace> review`. Never apply or discard them on your own initiative."]
    return "\n".join(lines)


def assemble(path: Path, snap: dict[str, Any]) -> list[Block]:
    blocks = [Block(preamble(path), "preamble"), Block(plugin_instructions(), "instructions")]
    pending = pending_block(snap)
    if pending:
        blocks.append(Block(pending, "pending approval"))
    if snap["cards"]:
        blocks.append(Block(HEADER, "Always-loaded memory"))
        for card in snap["cards"]:
            blocks.append(Block(render_markdown([card], header="").rstrip("\n"), card["address"],
                                {"address": card["address"], "title": card["title"]}))
    elif snap.get("empty_workspace"):
        blocks.append(Block(EMPTY_WORKSPACE_HINT, "empty workspace"))
    return blocks


# ---------------------------------------------------------------------------
# paginator
# ---------------------------------------------------------------------------
SEP = "\n\n"
PAGE_HEADER = "[MindSlice standing memory · page {i}/{n} · snapshot {snapshot}]"
PAGE_FOOTER = "[MindSlice standing memory complete · {n} pages · {c} cards]"
PAGE_FOOTER_INCOMPLETE = "[MindSlice standing memory INCOMPLETE · {n} pages · {d} of {c} cards delivered]"
CONTINUATION = "（续 {i}/{m}：{label} · 请按序号拼接阅读）"
CONTINUATION_RE = re.compile(r"^（续 (\d+)/(\d+)：.* · 请按序号拼接阅读）\n")
MARKER_RE = re.compile(r"(^|\n\n)（续 \d+/\d+：[^\n]* · 请按序号拼接阅读）\n")
HEADER_RE = re.compile(r"^\[MindSlice standing memory · page (\d+)/(\d+) · snapshot ([0-9a-f]{8})\]")
FAULT = ("[MindSlice standing memory page {i}/{n} could not be delivered safely] Before you reply, call "
         "manifest(include_always=true) and follow the instructions and always_loaded cards it returns; tell the "
         "user that the MindSlice plugin hit a delivery fault.")


def _overhead() -> int:
    header = utf16_len(PAGE_HEADER.format(i=9999, n=9999, snapshot="0" * 8))
    footer = max(utf16_len(PAGE_FOOTER.format(n=9999, c=999999)),
                 utf16_len(PAGE_FOOTER_INCOMPLETE.format(n=9999, d=999999, c=999999)))
    return header + 2 * len(SEP) + footer


def body_budget(page_limit: int) -> int:
    budget = page_limit - _overhead()
    if budget < 500:
        raise PluginError(f"page_limit {page_limit} is too small for the page frame")
    return budget


_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)", re.M)


def _joins(ch: str) -> bool:
    """True for a code point that binds to its neighbour (ZWJ, combining marks, variation selectors, skin tones,
    emoji tags): never cut next to one, so a grapheme cluster stays whole."""
    cp = ord(ch)
    return (ch == "‍" or unicodedata.category(ch) in ("Mn", "Me", "Mc") or 0xFE00 <= cp <= 0xFE0F
            or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F or 0xE0100 <= cp <= 0xE01EF)


def _cut(text: str, budget: int) -> int:
    """Where to end the next piece of ``text`` (0 < cut < len(text), ``utf16_len(text[:cut]) <= budget``)."""
    units, kmax = 0, 0
    for ch in text:
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > budget:
            break
        kmax += 1
    fence_ends = [m.end() for m in _FENCE_RE.finditer(text, 0, kmax)]

    def closed(k: int) -> bool:  # no code fence left open by text[:k]
        return bisect_right(fence_ends, k) % 2 == 0

    floor = max(1, kmax // 2)
    para = [m.end() for m in re.finditer(r"\n\n+", text[:kmax]) if m.end() >= floor]
    line = [m.end() for m in re.finditer(r"\n", text[:kmax]) if m.end() >= floor]
    for options, need_closed in ((para, True), (line, True), (para, False), (line, False)):
        for k in reversed(options):
            if k < len(text) and (closed(k) or not need_closed):
                return k
    k = kmax
    while k > 1 and (_joins(text[k]) or _joins(text[k - 1]) or (text[k - 1] == "\r" and text[k] == "\n")):
        k -= 1
    return k if k > 0 else kmax


def split_text(text: str, budget: int) -> list[str]:
    """``text`` in pieces of at most ``budget`` UTF-16 units each, concatenating back to ``text`` exactly."""
    pieces: list[str] = []
    rest = text
    while utf16_len(rest) > budget:
        k = _cut(rest, budget)
        pieces.append(rest[:k])
        rest = rest[k:]
    pieces.append(rest)
    return pieces


@dataclass
class Layout:
    pages: list[list[tuple[int, str]]] = field(default_factory=list)  # (block index, item text)


def layout(blocks: Sequence[Block], page_limit: int) -> Layout:
    """Greedy packing: a block never spans pages unless it alone exceeds a page; then it starts a fresh page and
    is cut into marked pieces, each piece but the last filling a page of its own."""
    budget = body_budget(page_limit)
    out = Layout()
    cur: list[tuple[int, str]] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            out.pages.append(cur)
        cur, cur_len = [], 0

    for idx, block in enumerate(blocks):
        size = utf16_len(block.text)
        if size <= budget:
            add = size + (len(SEP) if cur else 0)
            if cur_len + add > budget:
                flush()
                add = size
            cur.append((idx, block.text))
            cur_len += add
            continue
        flush()
        marker = utf16_len(CONTINUATION.format(i=9999, m=9999, label=block.label)) + 1
        pieces = split_text(block.text, max(budget - marker, budget // 2))
        for i, piece in enumerate(pieces, 1):
            item = CONTINUATION.format(i=i, m=len(pieces), label=block.label) + "\n" + piece
            if i < len(pieces):
                out.pages.append([(idx, item)])
            else:
                cur, cur_len = [(idx, item)], utf16_len(item)
    flush()
    return out


def render_pages(lay: Layout, snapshot_id: str, footer: str, extra: str | None = None) -> list[str]:
    bodies = [SEP.join(text for _, text in page) for page in lay.pages]
    if extra is not None:
        bodies.append(extra)
    n = len(bodies)
    return [PAGE_HEADER.format(i=i, n=n, snapshot=snapshot_id) + SEP + body + (SEP + footer if i == n else "")
            for i, body in enumerate(bodies, 1)]


def overflow_notice(missing: list[dict[str, str]], max_pages: int, budget: int) -> str:
    head = ("# Standing memory overflow\n\n"
            f"The user's always-loaded memory is larger than the {max_pages} pages this plugin delivers at session "
            "start. These always-loaded cards were NOT delivered above:\n")
    tail = ("\nBefore your first reply, call read(address) for each of them and follow them like the cards above. "
            "Tell the user their always-loaded memory overflows the startup budget (`mindslice plugin-status` shows "
            "the usage) and suggest moving reference knowledge to load=\"as-needed\".")
    lines: list[str] = []
    for n, card in enumerate(missing):
        line = f"- {card['address']} — {card['title']}"
        more = f"- … and {len(missing) - n} more: call manifest(include_always=true) to list them"
        if utf16_len(head + "\n".join(lines + [line, more]) + tail) > budget:
            lines.append(more)
            break
        lines.append(line)
    return head + "\n".join(lines) + tail


def deliver(blocks: Sequence[Block], page_limit: int, max_pages: int, snapshot_id: str) -> list[str]:
    """The pages to output: every one at most ``page_limit`` UTF-16 units, never a half-delivered card."""
    total = sum(1 for b in blocks if b.card)
    lay = layout(blocks, page_limit)
    if len(lay.pages) <= max_pages:
        pages = render_pages(lay, snapshot_id, PAGE_FOOTER.format(n=len(lay.pages), c=total))
    else:
        # Keep the blocks that end within the first K-1 pages (greedy packing is prefix-stable), then the notice.
        tail_blocks = {idx for page in lay.pages[max_pages - 1:] for idx, _ in page}
        keep = min(tail_blocks)
        while True:
            kept = layout(blocks[:keep], page_limit) if keep else Layout()
            if len(kept.pages) <= max_pages - 1:
                break
            keep -= 1
        missing = [b.card for b in blocks[keep:] if b.card]
        delivered = total - len(missing)
        notice = overflow_notice(missing, max_pages, body_budget(page_limit))
        n = len(kept.pages) + 1
        pages = render_pages(kept, snapshot_id, PAGE_FOOTER_INCOMPLETE.format(n=n, d=delivered, c=total), notice)
    n = len(pages)
    return [p if utf16_len(p) <= page_limit else FAULT.format(i=i, n=n) for i, p in enumerate(pages, 1)]


def reassemble(pages: Sequence[str]) -> str:
    """Inverse of ``deliver`` for complete deliveries (tests): strip frames and markers, rejoin the payload."""
    out = ""
    for n, page in enumerate(pages, 1):
        body = page.split(SEP, 1)[1]
        if n == len(pages):
            body = body[:body.rfind(SEP)]  # the footer
        m = CONTINUATION_RE.match(body)
        glued = m is not None and int(m.group(1)) > 1  # piece 2.. of a block: no separator before it
        body = MARKER_RE.sub(lambda mm: mm.group(1), body)
        out += body if glued or not out else SEP + body
    return out


@dataclass
class Delivery:
    pages: list[str]
    snapshot: str
    cards: int
    needed_pages: int
    card_units: int
    fixed_units: int


def compute_delivery(path: Path, page_limit: int, max_pages: int) -> Delivery:
    snap = snapshot(path)
    blocks = assemble(path, snap)
    payload = SEP.join(b.text for b in blocks)
    snapshot_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    card_blocks = [b for b in blocks if b.card or b.label == "Always-loaded memory"]
    card_units = sum(utf16_len(b.text) + len(SEP) for b in card_blocks)
    return Delivery(pages=deliver(blocks, page_limit, max_pages, snapshot_id), snapshot=snapshot_id,
                    cards=sum(1 for b in blocks if b.card), needed_pages=len(layout(blocks, page_limit).pages),
                    card_units=card_units, fixed_units=utf16_len(payload) - card_units)


# ---------------------------------------------------------------------------
# spool: one snapshot per startup event across concurrent hook slots
# ---------------------------------------------------------------------------
SPOOL_TTL = 3.0
SPOOL_LOCK_WAIT = 5.0
SPOOL_MAX_AGE = 86400.0


def state_fingerprint(root: Path) -> str:
    """Digest of ``(path, mtime_ns, size)`` over mounts.toml, overlay/ and staging/ (changes there change it)."""
    entries: list[tuple[str, int, int]] = []

    def note(p: Path) -> None:
        try:
            st = p.stat()
        except OSError:
            return
        entries.append((str(p.relative_to(root)), st.st_mtime_ns, st.st_size))

    note(root / MOUNTS_FILE)
    for sub in ("overlay", "staging"):
        base = root / sub
        note(base)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for name in dirnames + sorted(filenames):
                note(Path(dirpath) / name)
    return hashlib.sha256(json.dumps(entries).encode("utf-8")).hexdigest()


def _spool_key(session: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session)[:80]
    return safe or "session"


def _sweep(spool: Path) -> None:
    now = time.time()
    try:
        for p in spool.iterdir():
            if now - p.stat().st_mtime > SPOOL_MAX_AGE:
                p.unlink(missing_ok=True)
    except OSError:
        pass


def startup_pages(path: Path, session: str, page_limit: int, max_pages: int) -> list[str]:
    spool = plugin_data_dir() / "spool"
    spool.mkdir(parents=True, exist_ok=True)
    key = _spool_key(session)
    cache = spool / f"{key}.json"
    lock = WorkspaceLock(spool / f"{key}.lock", timeout=SPOOL_LOCK_WAIT)
    try:
        with lock.exclusive():
            fp = state_fingerprint(path)
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = None
            if (isinstance(cached, dict) and time.time() - cached.get("created", 0) <= SPOOL_TTL
                    and cached.get("fingerprint") == fp and cached.get("workspace") == str(path)
                    and cached.get("page_limit") == page_limit and cached.get("max_pages") == max_pages):
                return list(cached["pages"])
            pages = compute_delivery(path, page_limit, max_pages).pages
            atomic_write(cache, json.dumps({"created": time.time(), "fingerprint": fp, "workspace": str(path),
                                            "page_limit": page_limit, "max_pages": max_pages, "pages": pages},
                                           ensure_ascii=False))
            _sweep(spool)
            return pages
    except LockTimeoutError:
        return compute_delivery(path, page_limit, max_pages).pages  # the snapshot id exposes any mismatch
    finally:
        lock.close()


@dataclass
class HookResult:
    pages: list[str]
    workspace: Path | None = None


def hook_pages(session: str, page_limit: int, max_pages: int, cli_workspace: str | None = None) -> HookResult:
    """What a session-start hook delivers: the pages, or one diagnostic page when memory cannot load."""
    if isolated():
        return HookResult([])
    target = resolve("hook", cli_workspace)
    try:
        path = ensure_workspace(target)
        return HookResult(startup_pages(path, session, page_limit, max_pages), path)
    except PluginError as exc:
        return HookResult([f"[MindSlice plugin: memory not loaded] {exc}"])
    except Exception as exc:  # never fail a session start; tell the model how to recover instead
        return HookResult([FAULT.format(i=1, n=1) + f" (cause: {type(exc).__name__}: {exc})"], target.path)


# ---------------------------------------------------------------------------
# MCP server (section 4.4)
# ---------------------------------------------------------------------------
SHORT_INSTRUCTIONS = (
    "MindSlice is this user's long-term memory (tools: manifest, search, read, write). Its usage instructions and "
    "the user's always-loaded cards are delivered at session start (and after compaction where supported) as "
    "\"MindSlice standing memory\" pages, each marked `page i/n` with a snapshot id, the last one ending with a "
    "`complete` line. If those pages are missing, incomplete, or carry different snapshot ids, call `manifest` "
    "before you reply and follow the `instructions` and `always_loaded` cards it returns."
)
RESULT_LIMIT = 20000  # UTF-16 units of always-loaded cards inside one tool result
BODY_OMITTED_NOTE = ("The always-loaded cards are too large for one tool result, so their bodies are omitted here "
                     "(body_omitted). Call read(address) for each card you need; the standing memory pages carry "
                     "them in full.")


def _omit_bodies(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def strip(c: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in c.items() if k != "body"}
        out["body_omitted"] = True
        return out

    result = []
    for card in cards:
        c = strip(card)
        for key in ("baselines", "extensions"):
            if isinstance(card.get(key), list):
                c[key] = [strip(x) for x in card[key]]
        result.append(c)
    return result


def _too_big(value: Any) -> bool:
    return utf16_len(json.dumps(value, ensure_ascii=False)) > RESULT_LIMIT


def shrink_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The response copy with card bodies omitted where the always-loaded part would exceed ``RESULT_LIMIT``.
    Upstream has already fingerprinted the full cards, so ``always_loaded_update`` tracking stays exact."""
    if isinstance(payload.get("always_loaded"), list) and _too_big(payload["always_loaded"]):
        payload = dict(payload, always_loaded=_omit_bodies(payload["always_loaded"]),
                       always_loaded_note=BODY_OMITTED_NOTE)
    update = payload.get("always_loaded_update")
    if isinstance(update, dict) and isinstance(update.get("cards"), list) and _too_big(update["cards"]):
        payload = dict(payload, always_loaded_update=dict(update, cards=_omit_bodies(update["cards"]),
                                                          body_omitted_note=BODY_OMITTED_NOTE))
    return payload


class PluginMCPServer(MCPServer):
    """Upstream server with the plugin's delivery: short instructions, rewritten engine text, bounded results."""

    def __init__(self, ws: Workspace, stage_writes: bool = False, reinjects: bool | None = None) -> None:
        super().__init__(ws, stage_writes)
        reinjects = driver.reinjects_on_compact if reinjects is None else reinjects
        self._instructions = plugin_instructions(reinjects)
        self._tools = plugin_tools(reinjects)

    def instructions(self) -> str:
        try:
            snap = self.ws.boot()
        except MindSliceError:
            return SHORT_INSTRUCTIONS
        self._mark_seen(snap["cards"])  # the startup pages delivered this set
        return SHORT_INSTRUCTIONS

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().call_tool(name, arguments)
        if name == "manifest" and result.get("instructions") == INSTRUCTIONS:
            result["instructions"] = self._instructions
        return result

    def handle(self, message: Any) -> dict[str, Any] | None:
        if (isinstance(message, dict) and message.get("jsonrpc") == "2.0" and message.get("method") == "tools/list"
                and "id" in message):
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": self._tools}}
        return super().handle(message)

    def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        result = super()._tools_call(params)
        if result.get("isError"):
            return result
        try:
            payload = json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            return result
        shrunk = shrink_payload(payload) if isinstance(payload, dict) else payload
        if shrunk is payload:
            return result
        return {"content": [{"type": "text", "text": json.dumps(shrunk, ensure_ascii=False)}], "isError": False}


class IsolatedMCPServer(MCPServer):
    """``MINDSLICE_PLUGIN_ISOLATE=1``: answers the protocol, exposes nothing, never opens a workspace."""

    def __init__(self) -> None:  # no workspace on purpose
        self.protocol_version = PROTOCOL_VERSIONS[0]

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or "id" not in message:
            return None
        method, params = message.get("method"), message.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            result: dict[str, Any] = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                                      "serverInfo": {"name": "mindslice", "version": ENGINE_VERSION},
                                      "instructions": ""}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": []}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": json.dumps(
                {"error": "UnknownTool", "message": "MindSlice is isolated in this session"})}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def run_mcp(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="mindslice-plugin mcp")
    parser.add_argument("--workspace", "-w", default=None)
    ns = parser.parse_args(list(argv))
    ensure_utf8_stdio()
    if isolated():
        IsolatedMCPServer().serve(sys.stdin, sys.stdout)
        return 0
    try:
        path = ensure_workspace(resolve("mcp", ns.workspace))
        if os.environ.get(SELFTEST_FLAG) != "1":  # plugin-status's handshake must not repoint hooks and CLI
            write_bridge(path)
        with Workspace(path) as ws:
            PluginMCPServer(ws, driver.stage_writes_enabled()).serve(sys.stdin, sys.stdout)
    except PluginError as exc:
        sys.stderr.write(f"mindslice plugin: {exc}\n")
        return 1
    except MindSliceError as exc:
        sys.stderr.write(f"mindslice plugin: {exc}\n")
        return 1
    return 0


# ---------------------------------------------------------------------------
# plugin-status
# ---------------------------------------------------------------------------
SELFTEST_FLAG = "_MINDSLICE_PLUGIN_SELFTEST"


def mcp_handshake(path: Path, timeout: float = 30.0) -> dict[str, Any]:
    """Start this plugin's own ``mcp`` entry point and check it answers with the four tools and short instructions."""
    env = {k: v for k, v in os.environ.items() if k != "MINDSLICE_PLUGIN_ISOLATE"}
    env[SELFTEST_FLAG] = "1"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSIONS[0], "capabilities": {},
            "clientInfo": {"name": DOCTOR_CLIENT, "version": "plugin-status"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = "".join(json.dumps(r) + "\n" for r in requests)
    try:
        proc = subprocess.run([sys.executable, str(ADAPTER_DIR / "entry.py"), "mcp", "--workspace", str(path)],
                              input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "problem": f"could not start the MCP entry point: {exc}"}
    responses = {}
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            return {"ok": False, "problem": f"non-JSON line on MCP stdout: {line[:80]!r}"}
        responses[msg.get("id")] = msg
    init, tools = responses.get(1, {}).get("result"), responses.get(2, {}).get("result")
    if not init or not tools:
        return {"ok": False, "problem": "no initialize/tools/list response" + (f": {proc.stderr.strip()}" if proc.stderr.strip() else "")}
    names = sorted(t["name"] for t in tools.get("tools", []))
    instructions = init.get("instructions", "")
    problems = []
    if names != ["manifest", "read", "search", "write"]:
        problems.append(f"tools are {names}")
    if len(instructions) > 1000:
        problems.append(f"instructions are {len(instructions)} characters (limit 1000)")
    return {"ok": not problems, "tools": names, "instructions_chars": len(instructions),
            **({"problem": "; ".join(problems)} if problems else {})}


def status_report(cli_workspace: str | None = None) -> tuple[dict[str, Any], int]:
    cfg = target_config()
    page_limit, slots = cfg["page_limit"], cfg["hook_slots"]
    report: dict[str, Any] = {"target": cfg.get("target"), "plugin_version": cfg.get("plugin_version"),
                              "engine_version": ENGINE_VERSION,
                              "engine_path": str(Path(mindslice.__file__).resolve().parent.parent),
                              "page_limit": page_limit, "hook_slots": slots,
                              "isolated": isolated()}
    target = resolve("cli", cli_workspace)
    report["workspace"] = str(target.path) if target.path else None
    report["workspace_source"] = target.source
    try:
        path = ensure_workspace(target)
    except PluginError as exc:
        report["workspace_state"] = target.state
        report["problems"] = [str(exc)]
        return report, 1
    report["workspace_state"] = WORKSPACE
    d = compute_delivery(path, page_limit, slots)
    capacity = slots * body_budget(page_limit) - d.fixed_units
    pct = round(100.0 * d.card_units / capacity, 1) if capacity > 0 else 100.0
    report.update(cards=d.cards, pages_needed=d.needed_pages, card_units=d.card_units, card_capacity=capacity,
                  usage_percent=pct, snapshot=d.snapshot)
    problems, warnings = [], []
    if d.needed_pages > slots:
        problems.append(f"standing memory needs {d.needed_pages} pages but only {slots} are delivered: some "
                        "always-loaded cards do not reach the model at session start; move reference knowledge to "
                        "load=\"as-needed\"")
    elif pct >= 75:
        warnings.append(f"standing memory uses {pct}% of the startup capacity")
    hs = mcp_handshake(path)
    report["mcp_handshake"] = hs
    if not hs["ok"]:
        problems.append(f"MCP self-check failed: {hs.get('problem')}")
    report["problems"], report["warnings"] = problems, warnings
    return report, (1 if problems else 0)


def render_status(r: dict[str, Any]) -> str:
    lines = [f"MindSlice plugin {r.get('plugin_version')} ({r.get('target')}) · engine {r['engine_version']} "
             f"from {r['engine_path']}",
             f"workspace: {r.get('workspace') or '(not configured)'}"
             + (f"  [{r.get('workspace_state')}, from {r.get('workspace_source')}]" if r.get("workspace") else "")]
    if r.get("isolated"):
        lines.append("isolation: MINDSLICE_PLUGIN_ISOLATE=1 (hooks silent, MCP exposes no tools)")
    if "cards" in r:
        lines.append(f"standing memory: {r['cards']} card(s), {r['pages_needed']}/{r['hook_slots']} page(s) of "
                     f"{r['page_limit']} units, cards use {r['card_units']}/{r['card_capacity']} units "
                     f"({r['usage_percent']}%), snapshot {r['snapshot']}")
    hs = r.get("mcp_handshake")
    if hs:
        lines.append("mcp self-check: " + ("ok, tools " + ", ".join(hs["tools"]) +
                                           f", instructions {hs['instructions_chars']} chars" if hs["ok"]
                                           else "FAILED: " + str(hs.get("problem"))))
    lines += [f"warning: {w}" for w in r.get("warnings", [])]
    lines += [f"error: {p}" for p in r.get("problems", [])]
    return "\n".join(lines) + "\n"


def run_status(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="mindslice plugin-status",
                                     description="workspace, engine version, startup-memory usage and an MCP self-check")
    parser.add_argument("-w", "--workspace", default=None)
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(list(argv))
    ensure_utf8_stdio()
    report, code = status_report(ns.workspace)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n" if ns.json else render_status(report))
    return code


# ---------------------------------------------------------------------------
# CLI forwarding (section 4.6)
# ---------------------------------------------------------------------------
PASSTHROUGH_COMMANDS = {"init", "restore"}


def scan_cli(argv: Sequence[str]) -> tuple[bool, str | None, bool]:
    """``(names_workspace, subcommand, help_or_version)`` of an upstream CLI command line."""
    has_ws, command, meta = False, None, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-w", "--workspace"):
            has_ws = True
            i += 2
            continue
        if a.startswith("--workspace=") or (a.startswith("-w") and not a.startswith("--")):
            has_ws = True
        elif a in ("-h", "--help", "--version"):
            meta = True
        elif a == "--":
            break
        elif not a.startswith("-") and command is None:
            command = a
        i += 1
    return has_ws, command, meta


def find_local_workspace(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / MOUNTS_FILE).is_file():
            return candidate
    return None


def cli_workspace_for(argv: Sequence[str]) -> Target | None:
    """The plugin workspace to inject for this command, or None to leave the command to upstream as is."""
    has_ws, command, meta = scan_cli(argv)
    if has_ws or meta or command is None or command in PASSTHROUGH_COMMANDS:
        return None
    if os.environ.get("MINDSLICE_WORKSPACE") or isolated():
        return None
    if find_local_workspace(Path(os.path.abspath(os.getcwd()))):
        return None
    target = resolve("cli")
    return None if target.state == UNSET else target


def run_cli(argv: Sequence[str]) -> int:
    from mindslice.interfaces.cli import main as cli_main

    target = cli_workspace_for(argv)
    if target is not None:
        try:
            path = ensure_workspace(target)
        except PluginError as exc:
            sys.stderr.write(f"mindslice plugin: {exc}\n")
            return 1
        os.environ["MINDSLICE_WORKSPACE"] = str(path)  # this process (and its children) only
    return cli_main(list(argv))


# ---------------------------------------------------------------------------
def main(argv: Sequence[str]) -> int:
    argv = list(argv)
    if argv[:1] == ["hook"]:
        return driver.run_hook(argv[1:])
    if argv[:1] == ["mcp"]:
        return run_mcp(argv[1:])
    if argv[:1] == ["plugin-status"]:
        return run_status(argv[1:])
    return run_cli(argv)
