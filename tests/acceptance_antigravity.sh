#!/usr/bin/env bash
# Real Antigravity CLI acceptance for plugins/antigravity (PLAN section 12). Uses a few requests of your agy quota.
#
#   tests/acceptance_antigravity.sh
#   MODEL=gemini-3.8-flash-medium tests/acceptance_antigravity.sh
#
# Needs agy (signed in), tmux and Python 3.12+. Linux/macOS only.
#
# Antigravity has no way to fill a plugin's MCP variables from the command line, and its config.json must not be
# edited by hand, so the script installs the plugin with `agy plugin install` and fills the settings through the
# `/plugin` screen in a detached tmux session. Settings live in ~/.gemini/config/config.json and the plugin in
# ~/.gemini/config/plugins/mindslice for the whole user (the Antigravity app sees it too while the script runs),
# so the script refuses to run when a mindslice plugin is already installed, and uninstalls it at the end.
# Each run also adds its temporary project to agy's trustedWorkspaces (the trust prompt is answered in tmux).
#
# Checks: 1 startup pages, the MCP search tool and the CLI on the terminal PATH; 2 a multi-page Chinese standing
# memory arrives whole on one snapshot; 3 a local workspace wins in the terminal tool; 4 after /compact the model
# calls manifest and sees a card changed since; 5 a folder with other files is refused, untouched and reported;
# 6 stage_writes=true stages a write sent with stage=false; 7 MINDSLICE_PLUGIN_ISOLATE=1 hides the memory.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN="$REPO/plugins/antigravity"
MODEL="${MODEL:-gemini-3.8-flash-low}"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d)"
TMUX_SESSION="mindslice-acceptance-$$"
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
unset PLUGIN_DATA PLUGIN_ROOT MINDSLICE_PLUGIN_DATA MINDSLICE_PLUGIN_WORKSPACE MINDSLICE_PLUGIN_ISOLATE \
  MINDSLICE_WORKSPACE || true
fail=0
pass() { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }

if agy plugin list --json 2>/dev/null | "$PY" -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(p.get("name")=="mindslice" for p in (d if isinstance(d,list) else d.get("plugins",[]))) else 1)'; then
  echo "a mindslice plugin is already installed in Antigravity: uninstall it first (its settings would be lost)" >&2
  exit 2
fi
DATA_DIR="$HOME/.gemini/antigravity-cli/plugin_data/mindslice"
HAD_DATA=0
[ -e "$DATA_DIR" ] && HAD_DATA=1
cleanup() {
  tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
  agy plugin uninstall mindslice > /dev/null 2>&1 || true
  if [ "$HAD_DATA" = 0 ]; then rm -rf "$DATA_DIR"; fi
  rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK/proj" && (cd "$WORK/proj" && git init -q .)
ms() { PLUGIN_DATA="$WORK/seed-data" "$PY" "$PLUGIN/adapter/entry.py" "$@"; }  # the plugin's own CLI, for seeding
card() {  # card <workspace> <id> <title> <content> [load] [op]
  ms -w "$1" write "$2" --title "$3" --summary "$3." --content "$4" --load "${5:-always}" --op "${6:-create}" \
    --no-stage --reason acceptance > /dev/null; }

ask() {  # ask <out.json> <prompt> [agy args...]: one non-interactive conversation in the project
  local out="$1" prompt="$2"; shift 2
  (cd "$WORK/proj" && timeout 600 agy -p "$prompt" --model "$MODEL" --output-format json "$@" < /dev/null > "$out" 2> "$out.err") || true
}
reply() { "$PY" -c 'import json,sys
try: print(json.load(open(sys.argv[1], encoding="utf-8")).get("response") or "")
except ValueError: print("")' "$1"; }
conv() { "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("conversation_id",""))' "$1"; }
calls() {  # the tools a conversation called, from its transcript
  "$PY" -c 'import json,sys,os
p=os.path.expanduser("~/.gemini/antigravity-cli/brain/%s/.system_generated/logs/transcript_full.jsonl" % sys.argv[1])
for l in open(p, encoding="utf-8"):
    for t in json.loads(l).get("tool_calls", []):
        a=t.get("args") or {}
        print(a.get("ToolName") or t.get("name"))' "$1"; }

tui() { tmux send-keys -t "$TMUX_SESSION" "$@"; sleep 1.5; }
select_mindslice() {  # move the /plugin cursor onto the mindslice row when other plugins are installed
  local pane steps i=0
  pane="$(tmux capture-pane -t "$TMUX_SESSION" -p)"
  if grep -Eq '^[[:space:]]*[›>]' <<<"$pane"; then
    while ! tmux capture-pane -t "$TMUX_SESSION" -p | grep -Eq '^[[:space:]]*[›>].*\bmindslice\b'; do
      i=$((i + 1))
      if [ "$i" -gt 30 ]; then echo "could not select mindslice in /plugin" >&2; return 1; fi
      tui Down
    done
  else
    steps="$("$PY" -c 'import re,sys
rows=[l for l in sys.stdin.read().splitlines() if re.search(r"\[(enabled|disabled)\]", l)]
idx=next((i for i,l in enumerate(rows) if re.search(r"\bmindslice\b", l)), 0)
print(idx)' <<<"$pane")"
    while [ "$i" -lt "$steps" ]; do tui Down; i=$((i + 1)); done
  fi
}
configure() {  # configure <workspace> <stage_writes>: fill the plugin's settings in /plugin, enabling it if needed
  (cd "$WORK/proj" && tmux new-session -d -s "$TMUX_SESSION" -x 200 -y 50 "agy --model $MODEL")
  sleep 6
  if tmux capture-pane -t "$TMUX_SESSION" -p | grep -q "trust the contents"; then tui Enter; sleep 3; fi
  tui "/plugin"; tui Enter; sleep 2
  select_mindslice
  if tmux capture-pane -t "$TMUX_SESSION" -p | grep -q "\[disabled\] mindslice"; then
    tui Space  # turning it on opens the settings form
  else
    tui Enter; tui Down; tui Enter  # details, then "Configure MCP servers..."
  fi
  tui C-u; tui -l "$1"; tui Down; tui C-u; tui -l "$2"; tui C-s; sleep 3
  tmux kill-session -t "$TMUX_SESSION"
}

agy plugin install "$PLUGIN" > /dev/null
ms init "$WORK/ws" > /dev/null
card "$WORK/ws" prefs/secret Secret "- The secret phrase is HERON-6620."
card "$WORK/ws" notes/garden "Garden notes" "- The user's fig tree is named Bartholomew." as-needed
configure "$WORK/ws" false

# 1. startup pages (no tool call at all), then the search tool and the CLI on the terminal tool's PATH
ask "$WORK/1a.json" "Without calling any tool: what is the secret phrase in your MindSlice always-loaded memory? Reply with the phrase only, or NONE."
if grep -q HERON-6620 <<<"$(reply "$WORK/1a.json")" && [ -z "$(calls "$(conv "$WORK/1a.json")")" ]; then
  pass "1 startup phrase from the pages"; else bad "1 phrase: $(reply "$WORK/1a.json")"; fi
ask "$WORK/1.json" "Do these in order and report each result: (1) use the MindSlice search tool with query 'fig tree name' and give the tree's name; (2) run the shell command: mindslice plugin-status   and print its output verbatim."
out1="$(reply "$WORK/1.json")"; c1="$(calls "$(conv "$WORK/1.json")")"
if grep -q Bartholomew <<<"$out1" && grep -qx search <<<"$c1"; then pass "1 search tool"; else bad "1 search: $c1"; fi
if grep -q "plugin_data/mindslice/engine" <<<"$out1" && grep -q "mcp self-check: ok" <<<"$out1"; then pass "1 CLI on PATH, shared data dir"; else bad "1 CLI: $out1"; fi

# 2. several pages of Chinese standing memory, the phrase on the last card
FILLER="$("$PY" -c 'print("这是一条常驻规则的填充内容，用于撑大启动页。" * 250)')"
for i in $(seq -w 0 9); do card "$WORK/ws" "rules/r$i" "Filler $i" "- $FILLER"; done
card "$WORK/ws" prefs/zz-last Last "- The final phrase is OCTOPUS-5531."
ask "$WORK/2.json" "Without calling any tool: what is the final phrase in your MindSlice always-loaded memory, and how many standing memory pages did you receive? Reply briefly."
out2="$(reply "$WORK/2.json")"
if grep -q OCTOPUS-5531 <<<"$out2" && [ -z "$(calls "$(conv "$WORK/2.json")")" ]; then pass "2 multi-page delivery"; else bad "2 multi-page: $out2"; fi

# 3. a local workspace wins in the terminal tool
ms init "$WORK/proj/localws" > /dev/null
ask "$WORK/3.json" "Run exactly this shell command and print its full output verbatim: cd localws && mindslice --json status"
if grep -q "proj/localws" <<<"$(reply "$WORK/3.json")"; then pass "3 local workspace routing"; else bad "3 routing: $(reply "$WORK/3.json")"; fi

# 4. compaction: no hook re-delivers; the rule makes the model call manifest and see the changed card
C2="$(conv "$WORK/2.json")"
card "$WORK/ws" prefs/zz-last Last "- The final phrase is SQUID-8842." always replace
(cd "$WORK/proj" && timeout 600 agy --conversation "$C2" -p "/compact" --model "$MODEL" < /dev/null > "$WORK/4a.txt" 2>&1) || true
(cd "$WORK/proj" && timeout 600 agy --conversation "$C2" -p "What is the final phrase in your MindSlice always-loaded memory right now? Reply with the phrase only." \
   --model "$MODEL" --output-format json < /dev/null > "$WORK/4b.json" 2> "$WORK/4b.err") || true
if grep -q SQUID-8842 <<<"$(reply "$WORK/4b.json")" && calls "$C2" | grep -qx manifest; then pass "4 manifest after compaction"; else bad "4 compaction: $(reply "$WORK/4b.json")"; fi

# 5. a folder with other files: refused, untouched, reported instead of the earlier workspace
mkdir -p "$WORK/notes" && echo mine > "$WORK/notes/todo.md"
configure "$WORK/notes" true
ask "$WORK/5.json" "Without calling any tool: is your MindSlice memory loaded? If not, quote the reason you were given."
if [ "$(ls -A "$WORK/notes")" = "todo.md" ] && grep -qi "not empty\|not a MindSlice" <<<"$(reply "$WORK/5.json")"; then
  pass "5 non-empty folder refused and untouched"; else bad "5 refused: $(ls -A "$WORK/notes") / $(reply "$WORK/5.json")"; fi

# 6. stage_writes=true (still set from check 5)
configure "$WORK/ws" true
ask "$WORK/6.json" "Call the MindSlice write tool with id='notes/probe', summary='Probe.', content='- probe', reason='acceptance', stage=false, then report the tool result verbatim."
if [ -d "$WORK/ws/staging/notes" ] && [ ! -e "$WORK/ws/overlay/notes/probe.md" ]; then pass "6 stage_writes staged the write"; else bad "6 stage_writes: $(reply "$WORK/6.json")"; fi

# 7. isolation for nested sessions
MINDSLICE_PLUGIN_ISOLATE=1 ask "$WORK/7.json" "Without calling any tool: what is the final phrase in your MindSlice always-loaded memory? Answer NONE if you have none."
if ! grep -q "SQUID-8842\|OCTOPUS-5531" <<<"$(reply "$WORK/7.json")"; then pass "7 isolated session sees no memory"; else bad "7 isolation: $(reply "$WORK/7.json")"; fi

exit $fail
