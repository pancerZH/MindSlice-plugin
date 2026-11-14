"""Host-independent derivation rules for the plugin's skills (PLAN section 5.1).

Upstream text is never edited in place: ``build.py`` selects sections of it, applies these rewrites and the
link rewriting, and fills the shared templates with the target's host fragments
(``src/targets/<target>/fragments/<name>.md``, referenced as ``{{host:<name>}}``).

Every rule whose condition holds must match exactly once, or the build fails: a wording change upstream is
caught at build time instead of drifting silently.
"""

# The only upstream paths a build may read (C1).
UPSTREAM_ALLOWED = ("mindslice/", "skills/", "LICENSE", "NOTICE")

# Upstream skill directory -> plugin skill directory.
SKILL_DIRS = {
    "mindslice-setup": "setup",
    "slice-builder": "slice-builder",
    "slice-maintainer": "slice-maintainer",
}

SETUP = "skills/mindslice-setup/SKILL.md"

# name -> (upstream file, how, anchor). "section": from a heading line to the next heading of the same level;
# "paragraph": from a line starting with the anchor to the next blank line.
SELECTIONS = {
    "setup.on_failure": (SETUP, "paragraph", "**When something fails, go by the error report.**"),
    "setup.step2": (SETUP, "section", "## Step 2 - Confirm location and how to seed the workspace"),
    "setup.step4": (SETUP, "section", "## Step 4 - Validate and hand off"),
}

# Conditions: None (always), "builder" (slice-builder is packaged), "no_builder" (it is not).
# kind "replace": ``old`` -> ``new``. kind "cut": from ``start`` (inclusive) to ``end`` (exclusive) -> ``new``.
REWRITES = [
    # Forge (slice-builder) stays hidden until its nested-session isolation is verified (PLAN Q4).
    {"source": "setup.step2", "when": "no_builder", "kind": "cut",
     "start": "3. **Distill source documents into cards with MindSlice-forge**",
     "end": "4. **Start from scratch in plain language**", "new": ""},
    {"source": "setup.step2", "when": "no_builder", "kind": "replace",
     "old": "4. **Start from scratch in plain language**", "new": "3. **Start from scratch in plain language**"},
    {"source": "setup.step2", "when": None, "kind": "replace",
     "old": "   - Initialize the confirmed workspace only if needed (`<mindslice_bin> init <workspace>`).",
     "new": "   - {{host:init_note}}"},
    {"source": "setup.step2", "when": None, "kind": "replace",
     "old": "   - Initialize the confirmed path if needed (`<mindslice_bin> init <workspace>`).",
     "new": "   - {{host:init_note}}"},
    # The plugin owns the hooks: check them through plugin-status instead of by hand.
    {"source": "setup.step4", "when": None, "kind": "replace",
     "old": "Before them, run every hook command you configured by hand and check its output is what the hook\n"
            "expects.",
     "new": "{{host:step4_hooks}}"},
    {"source": "setup.step4", "when": None, "kind": "replace",
     "old": "(the `manifest` rule, and the hook where there is one)", "new": "{{host:step4_delivery}}"},
    # There is no installed Python package behind the plugin's CLI.
    {"source": "skills/slice-maintainer/SKILL.md", "when": None, "kind": "replace",
     "old": "Commands use the `mindslice` CLI (`python -m mindslice` also works); add `-w <workspace>` unless\n"
            "inside the workspace.",
     "new": "{{host:maintainer_cli}}"},
]

# Host text appended to an upstream file (condition as above).
APPENDS = [
    {"source": "skills/slice-builder/SKILL.md", "when": "builder", "new": "{{host:builder_isolation}}"},
]
