# Uninstall or disconnect the MindSlice plugin (DeepSeek Harness)

Removing the plugin removes its MCP registration, standing-memory prompt contributor, skills, and `mindslice`
command. **The memory workspace on disk is kept unless the user explicitly asks to delete it.**

## Step 1 - Inspect

1. Run `<mindslice_bin> plugin-status` with the shell tool and note the workspace path (`<workspace>`).
2. Check what the workspace holds: `<workspace>/overlay/` and `<workspace>/staging/` (cards and pending
   changes), `<workspace>/slices/`, and the external folders listed in `<workspace>/mounts.toml`.
3. Check for leftovers outside the plugin: any manual `dsh-mcp-client` MindSlice entry or MindSlice prompt/rule
   in `$DSH_HOME/cordis.patch.yml`, `$DSH_HOME/profiles/<profile>/cordis.patch.yml`, `~/.dsh/skills/`, or
   project `AGENTS.md` / `CLAUDE.md` (see "Migrating from a manual MindSlice setup" in [SKILL.md](SKILL.md)).

## Step 2 - Confirm with the user (mandatory)

Ask the user, in their language, three separate questions, and wait for the answers:

1. Uninstall the plugin, or only **disconnect** the workspace (`<mindslice_bin> plugin-config
   --unset-workspace`: the plugin stays installed and loads no memory until a workspace is set again)?
2. Remove the leftovers found in Step 1 (manual configuration)?
3. **Also delete the workspace folder `<workspace>`?** Default: keep it. State the exact path and what it
   holds. Keeping it leaves every Markdown card on disk; deleting it permanently removes `overlay/`,
   `staging/` and `slices/`. External folders mounted via `mounts.toml` are never deleted.

## Step 3 - Remove the plugin

The user uninstalls **dsh-mindslice** from **Plugins → Installed plugins → Uninstall** in DeepSeek Harness
Desktop (or runs `dsh plugin --profile <profile> remove dsh-mindslice`).

Remove only the leftovers the user agreed to. The plugin's data folder
(`$DSH_HOME/profiles/<profile>/plugin_data/mindslice/`, holding the engine copy, `settings.json`, and the
launcher) can be deleted too; keeping it preserves the workspace setting for a later reinstall.

## Step 4 - Delete the workspace (only if the user explicitly asked)

- Verify `<workspace>` is neither `/` nor the user's home directory, and that `<workspace>/mounts.toml` exists,
  so you never delete a folder that is not a MindSlice workspace.
- Read `<workspace>/mounts.toml` and make sure no mounted folder you would remove lies outside `<workspace>`;
  never touch those.
- Delete `<workspace>`. If the user chose to keep it, leave it and tell them its path.

## Step 5 - Verify

Ask the user to start a new session and check that the `mcp__mindslice__*` tools and the "MindSlice standing
memory" pages are gone. Summarize what was removed and whether `<workspace>` was kept.
