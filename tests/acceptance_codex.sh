#!/usr/bin/env bash
# Real Codex CLI acceptance for plugins/codex. Uses a few requests of your Codex quota.
#
#   tests/acceptance_codex.sh
#   MODEL=gpt-6.1-sol tests/acceptance_codex.sh
#
# Needs codex (signed in: ~/.codex/auth.json) and Python 3.12+. Linux/macOS only.
#
# Runs against a temporary CODEX_HOME (your auth.json linked in, your config.toml copied), so your own plugins,
# settings and hook trust are untouched: the repository is added there as the `mindslice` marketplace and the
# plugin installed from it. Plugin hooks run only once trusted (/hooks in the TUI), so every session but check 0
# passes --dangerously-bypass-hook-trust.
#
# Checks: 0 untrusted hooks: no pages, the MCP tools still work; 1 startup pages, the MCP search tool, the pages
# name the stable CLI; 2 a multi-page Chinese standing memory arrives whole on one snapshot; 3 the CLI works in
# the sandbox once the workspace is a writable root, and a local workspace wins; 4 after a compaction the pages
# are delivered again; 5 a folder with other files is refused, untouched and reported; 6 stage_writes=true stages
# a write sent with stage=false; 7 MINDSLICE_PLUGIN_ISOLATE=1 hides the memory.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d)"
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
unset PLUGIN_DATA PLUGIN_ROOT CLAUDE_PLUGIN_DATA CLAUDE_PLUGIN_ROOT MINDSLICE_PLUGIN_DATA MINDSLICE_PLUGIN_WORKSPACE \
  MINDSLICE_PLUGIN_ISOLATE MINDSLICE_WORKSPACE || true
fail=0
pass() { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }
trap 'rm -rf "$WORK"' EXIT

export CODEX_HOME="$WORK/codex-home"
mkdir -p "$CODEX_HOME" "$WORK/proj"
ln -s "$HOME/.codex/auth.json" "$CODEX_HOME/auth.json"
[ -f "$HOME/.codex/config.toml" ] && cp "$HOME/.codex/config.toml" "$CODEX_HOME/config.toml"
cat >> "$CODEX_HOME/config.toml" <<'EOF'

[plugins."mindslice@mindslice".mcp_servers.mindslice.tools.write]
approval_mode = "approve"
EOF
codex plugin marketplace add "$REPO" > /dev/null 2>&1
codex plugin add mindslice@mindslice > /dev/null 2>&1
ROOT="$(ls -d "$CODEX_HOME"/plugins/cache/mindslice/mindslice/*/ | head -1)"
DATA="$CODEX_HOME/plugins/data/mindslice-mindslice"
CLI="$DATA/bin/mindslice"
ms() { "$ROOT/bin/mindslice" "$@"; }  # the installed plugin's CLI, for seeding (outside any sandbox)
card() {  # card <workspace> <id> <title> <content> [load] [op]
  ms -w "$1" write "$2" --title "$3" --summary "$3." --content "$4" --load "${5:-always}" --op "${6:-create}" \
    --no-stage --reason acceptance > /dev/null; }

MODEL_ARGS=()
[ -n "${MODEL:-}" ] && MODEL_ARGS=(-m "$MODEL")
ask() {  # ask <out.jsonl> <prompt> [codex exec args...]: one non-interactive session in the project
  local out="$1" prompt="$2"; shift 2
  (cd "$WORK/proj" && timeout 600 codex exec --json --skip-git-repo-check "${MODEL_ARGS[@]}" "$@" "$prompt" \
     < /dev/null > "$out" 2> "$out.err") || true
}
trusted() { ask "$@" --dangerously-bypass-hook-trust; }
reply() { "$PY" -c 'import json,sys
last=""
for l in open(sys.argv[1], encoding="utf-8"):
    try: e=json.loads(l)
    except ValueError: continue
    i=e.get("item") or {}
    if e.get("type")=="item.completed" and i.get("type")=="agent_message": last=i.get("text","")
print(last)' "$1"; }
calls() {  # the tools a session called: MCP tool names, "shell" for commands
  "$PY" -c 'import json,sys
for l in open(sys.argv[1], encoding="utf-8"):
    try: e=json.loads(l)
    except ValueError: continue
    i=e.get("item") or {}
    if e.get("type")=="item.completed" and i.get("type")=="mcp_tool_call": print(i.get("tool"), i.get("status"))
    elif e.get("type")=="item.completed" and i.get("type")=="command_execution": print("shell")' "$1"; }
thread() { "$PY" -c 'import json,sys
for l in open(sys.argv[1], encoding="utf-8"):
    try: e=json.loads(l)
    except ValueError: continue
    if e.get("type")=="thread.started": print(e["thread_id"]); break' "$1"; }

ms plugin-config --workspace "$WORK/ws" > /dev/null
ms init "$WORK/ws" > /dev/null
card "$WORK/ws" prefs/secret Secret "- The secret phrase is HERON-6620."
card "$WORK/ws" notes/garden "Garden notes" "- The user's fig tree is named Bartholomew." as-needed

# 0. untrusted hooks are skipped; the MCP server runs anyway and its read-only tools need no approval
ask "$WORK/0.json" "What is the name of my fig tree? Look it up with the MindSlice search tool. Also say whether a 'MindSlice standing memory' page is in your context (yes/no)."
if grep -q Bartholomew <<<"$(reply "$WORK/0.json")" && calls "$WORK/0.json" | grep -q "^search completed"; then
  pass "0 MCP tools without trusted hooks"; else bad "0 untrusted: $(reply "$WORK/0.json")"; fi

# 1. startup pages (no tool call at all), then the search tool; the pages name the stable launcher
trusted "$WORK/1a.json" "Without calling any tool: what is the secret phrase in your MindSlice always-loaded memory? Reply with the phrase only, or NONE."
if grep -q HERON-6620 <<<"$(reply "$WORK/1a.json")" && [ -z "$(calls "$WORK/1a.json")" ]; then
  pass "1 startup phrase from the pages"; else bad "1 phrase: $(reply "$WORK/1a.json")"; fi
trusted "$WORK/1b.json" "Without calling any tool: quote the exact command the MindSlice standing memory tells you to run the mindslice CLI with."
if grep -qF "$CLI" <<<"$(reply "$WORK/1b.json")" && [ -x "$CLI" ]; then pass "1 pages name the stable CLI"; else bad "1 CLI hint: $(reply "$WORK/1b.json")"; fi

# 2. several pages of Chinese standing memory (within the 4-page capacity), the phrase on the last card
FILLER="$("$PY" -c 'print("这是一条常驻规则的填充内容，用于撑大启动页。" * 120)')"
for i in $(seq -w 0 7); do card "$WORK/ws" "rules/r$i" "Filler $i" "- $FILLER"; done
card "$WORK/ws" prefs/zz-last Last "- The final phrase is OCTOPUS-5531."
trusted "$WORK/2.json" "Without calling any tool: what is the final phrase in your MindSlice always-loaded memory, how many standing memory pages did you receive, and do they all carry the same snapshot id? Reply briefly."
out2="$(reply "$WORK/2.json")"
if grep -q OCTOPUS-5531 <<<"$out2" && [ -z "$(calls "$WORK/2.json")" ]; then pass "2 multi-page delivery ($out2)"; else bad "2 multi-page: $out2"; fi

# 3. the CLI from the sandboxed shell tool, with the workspace as a writable root; a local workspace wins
ms init "$WORK/proj/localws" > /dev/null
trusted "$WORK/3.json" "Run these two shell commands in the sandbox (no escalation) and print each full output verbatim: (a) $CLI status   (b) cd localws && $CLI --json status" -s workspace-write --add-dir "$WORK/ws"
out3="$(reply "$WORK/3.json")"
if grep -q "proj/localws" <<<"$out3" && ! grep -qi "read-only file system" <<<"$out3"; then pass "3 sandboxed CLI and local routing"; else bad "3 CLI: $out3"; fi

# 4. compaction: a tiny auto-compact limit on a resumed session; the pages come back after the compaction
T2="$(thread "$WORK/2.json")"
(cd "$WORK/proj" && timeout 600 codex exec resume "$T2" --json --skip-git-repo-check --dangerously-bypass-hook-trust \
   "${MODEL_ARGS[@]}" -c model_auto_compact_token_limit=12000 \
   "Without calling any tool: what is the final phrase in your MindSlice always-loaded memory right now?" \
   < /dev/null > "$WORK/4.json" 2> "$WORK/4.err") || true
ROLLOUT="$(ls -t "$CODEX_HOME"/sessions/*/*/*/*"$T2"*.jsonl 2>/dev/null | head -1)"
if [ -n "$ROLLOUT" ] && "$PY" - "$ROLLOUT" <<'EOF'
import json, sys
seen_compaction = after = False
for line in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(line)
    if d.get("type") == "compacted":
        seen_compaction = True
    elif seen_compaction and "MindSlice standing memory · page 1/" in line:
        after = True
sys.exit(0 if seen_compaction and after else 1)
EOF
then pass "4 pages delivered again after compaction"; else bad "4 compaction: $(reply "$WORK/4.json")"; fi

# 5. a folder that has other files by now: refused, untouched, reported
mkdir -p "$WORK/notes" && echo mine > "$WORK/notes/todo.md"
if ms plugin-config --workspace "$WORK/notes" > /dev/null 2>&1; then bad "5 plugin-config accepted a non-empty folder"; fi
"$PY" -c 'import json,sys; json.dump({"workspace": sys.argv[2]}, open(sys.argv[1], "w"))' "$DATA/settings.json" "$WORK/notes"
trusted "$WORK/5.json" "Without calling any tool: is your MindSlice memory loaded? If not, quote the reason you were given."
if [ "$(ls -A "$WORK/notes")" = "todo.md" ] && grep -qi "not empty\|not a MindSlice" <<<"$(reply "$WORK/5.json")"; then
  pass "5 non-empty folder refused and untouched"; else bad "5 refused: $(ls -A "$WORK/notes") / $(reply "$WORK/5.json")"; fi

# 6. stage_writes=true
ms plugin-config --workspace "$WORK/ws" --stage-writes true > /dev/null
trusted "$WORK/6.json" "Call the MindSlice write tool with id='notes/probe', summary='Probe.', content='- probe', reason='acceptance', stage=false, then report the tool result verbatim."
if [ -d "$WORK/ws/staging/notes" ] && [ ! -e "$WORK/ws/overlay/notes/probe.md" ]; then pass "6 stage_writes staged the write"; else bad "6 stage_writes: $(reply "$WORK/6.json")"; fi

# 7. isolation for nested sessions
MINDSLICE_PLUGIN_ISOLATE=1 trusted "$WORK/7.json" "Without calling any tool: what is the final phrase in your MindSlice always-loaded memory? Answer NONE if you have none."
if ! grep -q "OCTOPUS-5531\|HERON-6620" <<<"$(reply "$WORK/7.json")"; then pass "7 isolated session sees no memory"; else bad "7 isolation: $(reply "$WORK/7.json")"; fi
MINDSLICE_PLUGIN_ISOLATE=1 trusted "$WORK/7b.json" "Use the MindSlice search tool with query 'fig tree name' and give the tree's name, or say UNAVAILABLE if you cannot."
if ! grep -q Bartholomew <<<"$(reply "$WORK/7b.json")"; then pass "7 isolated MCP server exposes no tools"; else bad "7 isolated MCP: $(reply "$WORK/7b.json")"; fi

exit $fail
