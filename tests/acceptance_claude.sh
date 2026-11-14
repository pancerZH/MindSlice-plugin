#!/usr/bin/env bash
# Real Claude Code acceptance for plugins/claude (PLAN section 8). Costs a few cents with the default model.
#
#   tests/acceptance_claude.sh            # uses --plugin-dir plugins/claude
#   MODEL=sonnet tests/acceptance_claude.sh
#   PYTHON=py tests/acceptance_claude.sh  # the Python for the script's own helpers (default: py on Windows, else python3)
#
# Windows: run it from Git Bash (Git for Windows), with Claude Code and Python 3.12+ installed.
#
# The plugin's `workspace` option cannot be set for a --plugin-dir session (PLAN Q1), so its MCP server does not
# load here (F9); the hooks and the CLI resolve the workspace through $MINDSLICE_WORKSPACE, their last fallback.
# Checks: 1 startup pages reach the model whole; 2 compaction re-delivers fresh pages; 3 CLI routing in the Bash
# tool; 4 unconfigured / non-empty folders; 5 overflow.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${MODEL:-haiku}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if [ "${OS:-}" = Windows_NT ]; then
  PY="${PYTHON:-py}"
  # native programs (claude, python) need C:/... paths, also in environment variables
  REPO="$(cygpath -m "$REPO")"; WORK="$(cygpath -m "$WORK")"
else
  PY="${PYTHON:-python3}"
fi
PLUGIN="$REPO/plugins/claude"
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 CLAUDE_PLUGIN_DATA="$WORK/data"
unset MINDSLICE_PLUGIN_WORKSPACE MINDSLICE_PLUGIN_ISOLATE CLAUDE_PLUGIN_OPTION_WORKSPACE || true
mkdir -p "$WORK/proj"
fail=0
pass() { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }

MS="$PLUGIN/bin/mindslice"  # the plugin's own CLI: also installs the pinned engine into $CLAUDE_PLUGIN_DATA
FILLER="$("$PY" -c 'print("这是一条常驻规则的填充内容，用于撑大启动页。" * 180)')"
seed() {  # seed <workspace> <filler cards> <phrase>
  "$MS" init "$1" > /dev/null
  for i in $(seq -w 0 $(($2 - 1))); do
    "$MS" -w "$1" write "rules/r$i" --title "Filler $i" --summary "Filler rule $i." --content "- $FILLER" \
      --load always --no-stage --reason acceptance > /dev/null
  done
  "$MS" -w "$1" write rules/zz-last --title Secret --summary "Secret phrase card." \
    --content "- The secret phrase is $3." --load always --no-stage --reason acceptance > /dev/null
}

ask() {  # ask <workspace> <out.jsonl> <prompt> [extra claude args...]
  local ws="$1" out="$2" prompt="$3"; shift 3
  (cd "$WORK/proj" && MINDSLICE_WORKSPACE="$ws" claude -p "$prompt" --model "$MODEL" --plugin-dir "$PLUGIN" \
     --output-format stream-json --verbose "$@" < /dev/null > "$out" 2> "$out.err") || true
}

result() { "$PY" -c 'import json,sys
for l in open(sys.argv[1], encoding="utf-8"):
    m=json.loads(l)
    if m.get("type")=="result": print(m.get("result") or "")' "$1"; }
session() { "$PY" -c 'import json,sys
for l in open(sys.argv[1], encoding="utf-8"):
    m=json.loads(l)
    if m.get("session_id"): print(m["session_id"]); break' "$1"; }
hook_outputs() { "$PY" -c 'import json,sys
n=0
for l in open(sys.argv[1], encoding="utf-8"):
    m=json.loads(l)
    if m.get("subtype")=="hook_response" and str(m.get("hook_name","")).startswith("SessionStart:"+sys.argv[2]): n+=1
print(n)' "$1" "$2"; }

NO_TOOLS=(--disallowedTools "Bash,Read,Grep,Glob,mcp__plugin_mindslice_mindslice__read,mcp__plugin_mindslice_mindslice__search,mcp__plugin_mindslice_mindslice__manifest")

# 1. ~30,000 characters of standing memory, the phrase on the last card
seed "$WORK/ws" 5 "OCTOPUS-5531"
ask "$WORK/ws" "$WORK/1.jsonl" "Without calling any tool: what is the secret phrase in your MindSlice always-loaded memory? Reply with the phrase only, or NONE." "${NO_TOOLS[@]}"
if result "$WORK/1.jsonl" | grep -q "OCTOPUS-5531"; then pass "1 startup phrase"; else bad "1 startup phrase: $(result "$WORK/1.jsonl")"; fi

# 2. compaction re-delivers, and a card changed just before is seen
SID="$(session "$WORK/1.jsonl")"
"$MS" -w "$WORK/ws" write rules/zz-last --op replace --content "- The secret phrase is SQUID-8842." \
  --load always --no-stage --reason acceptance > /dev/null
ask "$WORK/ws" "$WORK/2a.jsonl" "/compact" --resume "$SID"
n="$(hook_outputs "$WORK/2a.jsonl" compact)"
if [ "$n" -ge 4 ]; then pass "2 compact fired $n hooks"; else bad "2 compact fired $n SessionStart:compact hooks (expected 4)"; fi
ask "$WORK/ws" "$WORK/2b.jsonl" "Without calling any tool: what is the secret phrase in your MindSlice always-loaded memory now? Reply with the phrase only." --resume "$SID" "${NO_TOOLS[@]}"
if result "$WORK/2b.jsonl" | grep -q "SQUID-8842"; then pass "2 phrase after compact"; else bad "2 phrase after compact: $(result "$WORK/2b.jsonl")"; fi

# 3. the CLI in the Bash tool targets the plugin workspace, and a local workspace wins inside it
"$MS" init "$WORK/proj/localws" > /dev/null
ask "$WORK/ws" "$WORK/3.jsonl" "Run exactly these two Bash commands and print their full output: 1) mindslice plugin-status 2) cd localws && mindslice --json status" --allowedTools "Bash(mindslice:*),Bash(cd localws && mindslice --json status)"
out3="$(result "$WORK/3.jsonl")"
# match by directory name: Windows prints C:\...\ws, the script knows C:/.../ws
if grep -Eq "[/\\]ws([^A-Za-z0-9_-]|$)" <<<"$out3" && grep -q "localws" <<<"$out3"; then pass "3 CLI routing"; else bad "3 CLI routing: $out3"; fi

# 4. unconfigured, and a non-empty folder that is not a workspace
ask "" "$WORK/4a.jsonl" "Without calling any tool: is your MindSlice memory loaded? If not, quote the reason you were given." "${NO_TOOLS[@]}"
if result "$WORK/4a.jsonl" | grep -qi "configur"; then pass "4 unconfigured notice"; else bad "4 unconfigured: $(result "$WORK/4a.jsonl")"; fi
mkdir -p "$WORK/notes" && echo "mine" > "$WORK/notes/todo.md"
ask "$WORK/notes" "$WORK/4b.jsonl" "Without calling any tool: is your MindSlice memory loaded? If not, quote the reason you were given." "${NO_TOOLS[@]}"
if [ "$(ls -A "$WORK/notes")" = "todo.md" ] && result "$WORK/4b.jsonl" | grep -qi "not empty\|not a MindSlice"; then
  pass "4 non-empty folder refused and untouched"; else bad "4 non-empty folder: $(ls -A "$WORK/notes") / $(result "$WORK/4b.jsonl")"; fi

# 5. overflow: more than 4 pages of standing memory
seed "$WORK/big" 12 "WALRUS-1209"
ask "$WORK/big" "$WORK/5.jsonl" "Without calling any tool: did your MindSlice standing memory report an overflow? Answer YES or NO and list the undelivered card addresses." "${NO_TOOLS[@]}"
if result "$WORK/5.jsonl" | grep -qi "yes"; then pass "5 overflow reported"; else bad "5 overflow: $(result "$WORK/5.jsonl")"; fi
if MINDSLICE_WORKSPACE="$WORK/big" "$PLUGIN/bin/mindslice" plugin-status > /dev/null; then bad "5 plugin-status exit 0"; else pass "5 plugin-status non-zero"; fi

exit $fail
