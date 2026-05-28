#!/usr/bin/env bash
# Adversarial ping-pong review loop between Claude and Codex.
#
# Each round:
#   1. Loads the project's top-level *.md docs (AGENTS.md, CLAUDE.md, DECISIONS.md,
#      README.md, SETUP.md, PROJECT_SUMMARY_*.md) as the rubric.
#   2. Reads the prior round's review file.
#   3. Audits the repo against the rubric AND pokes holes in the prior review.
#   4. Writes its review to reviews/pingpong/round_NNN_<agent>.md.
#
# Cadence: sleeps INTERVAL_SECS (default 1800 = 30 min) between rounds.
#
# Usage:
#   bash reviews/pingpong/run.sh              # foreground, Ctrl+C to stop
#   nohup bash reviews/pingpong/run.sh >/dev/null 2>&1 &   # detached
#   INTERVAL_SECS=600 bash reviews/pingpong/run.sh         # 10-min cadence
#   MAX_ROUNDS=10 bash reviews/pingpong/run.sh             # stop after 10 rounds
#
# Stop:
#   Ctrl+C, or:  pkill -f reviews/pingpong/run.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$REPO_ROOT/reviews/pingpong"
LOG="$OUT_DIR/run.log"
INTERVAL_SECS="${INTERVAL_SECS:-1800}"
MAX_ROUNDS="${MAX_ROUNDS:-0}"      # 0 = unlimited
TIMEOUT_SECS="${TIMEOUT_SECS:-1500}"  # per-round cap so a hung CLI can't stall the loop

mkdir -p "$OUT_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

trap 'log "Interrupted. Exiting."; exit 130' INT TERM

command -v claude >/dev/null || { log "FATAL: claude CLI not on PATH"; exit 1; }
command -v codex  >/dev/null || { log "FATAL: codex CLI not on PATH";  exit 1; }

# Portable per-round timeout (macOS doesn't ship GNU `timeout`).
# Usage:  with_timeout SECONDS cmd args...
# Inherits caller's stdout/stderr redirections. Returns 124 on timeout, else cmd's rc.
with_timeout() {
  local secs="$1"; shift
  local marker; marker="$(mktemp -t pingpong_timeout.XXXXXX)"
  rm -f "$marker"
  "$@" &
  local cmd_pid=$!
  (
    sleep "$secs"
    if kill -0 "$cmd_pid" 2>/dev/null; then
      : >"$marker"
      kill -TERM "$cmd_pid" 2>/dev/null
      sleep 5
      kill -KILL "$cmd_pid" 2>/dev/null
    fi
  ) &
  local watch_pid=$!
  local rc=0
  wait "$cmd_pid" 2>/dev/null || rc=$?
  kill -TERM "$watch_pid" 2>/dev/null
  wait "$watch_pid" 2>/dev/null
  if [[ -e "$marker" ]]; then
    rm -f "$marker"
    return 124
  fi
  return $rc
}

build_prompt() {
  local round="$1" agent="$2" prior_path="$3"
  cat <<EOF
You are agent "${agent}" in an adversarial ping-pong code review of the repository at ${REPO_ROOT} (round ${round}).

STEP 1 — LOAD THE YARDSTICK
Read these top-level Markdown files first and treat them as the rubric for everything that follows:
  - AGENTS.md
  - CLAUDE.md
  - DECISIONS.md
  - README.md
  - SETUP.md
  - any PROJECT_SUMMARY_*.md
  - any other top-level *.md you discover
These documents describe what the project SAYS it is, the decisions that have been made, and how it claims to work. Your job is to find where the actual code, structure, scripts, configs, or behavior diverge from these claims.

STEP 2 — READ THE PRIOR REVIEW
Prior round's review file: ${prior_path}
If that path exists, read it carefully. You will critique it in step 4.

STEP 3 — INDEPENDENT FRESH REVIEW
Walk the repo (agent/, analysis/, serving/, validation/, tasks/, prompts/, Makefile, requirements.txt, etc.). Audit code, structure, tests, scripts, and outputs against the .md yardstick. Flag:
  - Claims in .md docs that the code does not actually deliver
  - Code or behavior that contradicts a stated decision in DECISIONS.md
  - Drift, dead code, half-finished work, or required pieces that are missing
  - Bugs, footguns, security issues, sloppy patterns, unsafe shell, etc.
  - Anything the prior agent missed entirely
Cite file:line for every finding. Severity: [BLOCKER|MAJOR|MINOR|NIT].

STEP 4 — POKE HOLES IN THE PRIOR REVIEW
If a prior review exists, attack it: where is it wrong, overstated, vague, or based on a misreading of the code or the .md docs? Defend the code where the prior agent unfairly criticized it. Quote the prior claim verbatim and explain why it is off.

STEP 5 — OUTPUT
DO NOT modify any files in the repo. Emit your review in this exact Markdown structure to your final message:

# Round ${round} — ${agent}
## Yardstick docs read
- One bullet per .md file with a one-line summary of what it claims.
## Findings (code vs. yardstick)
- One bullet per finding. Tag severity [BLOCKER|MAJOR|MINOR|NIT]. Cite file:line.
## Rebuttals to prior round
- Quote + critique. If no prior review, write "n/a (first round)".
## Open questions / next round should investigate
- Bullets.

Be terse, specific, and adversarial. No filler, no preamble, no closing remarks.
EOF
}

run_claude() {
  local prompt="$1" out="$2"
  with_timeout "$TIMEOUT_SECS" claude -p "$prompt" \
    --add-dir "$REPO_ROOT" \
    --allowedTools "Read" "Glob" "Grep" "Bash(ls:*)" "Bash(cat:*)" "Bash(find:*)" "Bash(wc:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(git log:*)" "Bash(git diff:*)" "Bash(git status:*)" "Bash(git show:*)" "Bash(git ls-files:*)" \
    >"$out" 2>>"$LOG"
}

run_codex() {
  local prompt="$1" out="$2"
  # -s read-only sandbox: codex can read but cannot modify the repo.
  # -o writes the final agent message to $out; event stream goes to $LOG.
  with_timeout "$TIMEOUT_SECS" codex exec \
    -C "$REPO_ROOT" \
    -s read-only \
    -o "$out" \
    "$prompt" \
    >>"$LOG" 2>&1
}

log "=== Adversarial ping-pong started. interval=${INTERVAL_SECS}s max_rounds=${MAX_ROUNDS} ==="

while true; do
  last_n=$(ls "$OUT_DIR"/round_*.md 2>/dev/null \
    | sed -E 's|.*round_0*([0-9]+)_.*|\1|' \
    | sort -n | tail -1)
  next_n=$(( ${last_n:-0} + 1 ))

  if (( MAX_ROUNDS > 0 && next_n > MAX_ROUNDS )); then
    log "Reached MAX_ROUNDS=$MAX_ROUNDS. Exiting."
    exit 0
  fi

  printf -v round "%03d" "$next_n"

  # Alternation: opposite of the most recent file's agent. Falls back to claude on first round.
  # Overridable via FORCE_AGENT=claude|codex (single-round nudge; clear it for normal ping-pong).
  prior=$(ls "$OUT_DIR"/round_*.md 2>/dev/null | sort | tail -1)
  prior_path="${prior:-NONE}"
  if [[ -n "${FORCE_AGENT:-}" ]]; then
    agent="$FORCE_AGENT"
  elif [[ "$prior_path" =~ _claude\.md$ ]]; then
    agent="codex"
  elif [[ "$prior_path" =~ _codex\.md$ ]]; then
    agent="claude"
  else
    agent="claude"
  fi
  out="$OUT_DIR/round_${round}_${agent}.md"

  log "Round ${round} (${agent}) start. Prior=${prior_path}"
  prompt="$(build_prompt "$round" "$agent" "$prior_path")"

  start_ts=$(date +%s)
  rc=0
  if [[ "$agent" == "claude" ]]; then
    run_claude "$prompt" "$out" || rc=$?
  else
    run_codex "$prompt" "$out" || rc=$?
  fi
  dur=$(( $(date +%s) - start_ts ))

  if (( rc == 124 )); then
    log "  ${agent} TIMED OUT after ${TIMEOUT_SECS}s"
  elif (( rc != 0 )); then
    log "  ${agent} exited non-zero (rc=${rc})"
  fi

  if [[ ! -s "$out" ]]; then
    # Stub on failure so last_n advances and the loop doesn't lock on this round.
    cat >"$out" <<STUB
# Round ${round} — ${agent} — FAILED

Agent exited rc=${rc} with no usable output.
Timestamp: $(date '+%Y-%m-%d %H:%M:%S')
Duration: ${dur}s

See \`reviews/pingpong/run.log\` around this timestamp for the underlying error.
STUB
    log "Round ${round} (${agent}) FAILED (rc=${rc}) — wrote stub → $out"
  else
    log "Round ${round} (${agent}) done in ${dur}s → $out ($(wc -l <"$out" | tr -d ' ') lines)"
  fi

  log "Sleeping ${INTERVAL_SECS}s..."
  sleep "$INTERVAL_SECS"
done
