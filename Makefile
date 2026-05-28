# Ping-pong workflow between Claude Code and Codex.
# Each target prints the next steps + the prompt to paste. It does not
# auto-invoke either agent — you stay in control of when each runs.

.DEFAULT_GOAL := help

SEP := ------------------------------------------------------------------

help:
	@echo ""
	@echo "Ping-pong workflow targets:"
	@echo ""
	@echo "  make cycle1-cc    Cycle 1 step 1: Claude Code implements Tracer"
	@echo "  make cycle1-cx    Cycle 1 step 2: Codex reviews Tracer"
	@echo ""
	@echo "  make cycle2-cc    Cycle 2 step 1: Claude Code implements synthetic test"
	@echo "  make cycle2-cx    Cycle 2 step 2: Codex writes adversarial assertions"
	@echo ""
	@echo "  make verify       Run the synthetic test and assertions"
	@echo "  make verify-v3    Dry-run final-v3 traces, validate, and analyze"
	@echo "  make status       Show recent [CC]/[CX]/[H] commits"
	@echo ""

cycle1-cc:
	@echo ""
	@echo "$(SEP)"
	@echo "Cycle 1, step 1: Claude Code implements Tracer"
	@echo "$(SEP)"
	@echo ""
	@echo "1. Branch:"
	@echo "     git checkout -b feat/tracer-cc"
	@echo ""
	@echo "2. Start Claude Code:"
	@echo "     claude"
	@echo ""
	@echo "3. Paste this prompt:"
	@echo "$(SEP)"
	@cat prompts/01-tracer-implement.md
	@echo "$(SEP)"
	@echo ""
	@echo "4. After Claude Code finishes, review and commit:"
	@echo "     git diff agent/tracer.py"
	@echo "     git add agent/tracer.py"
	@echo "     git commit -m '[CC] implement Tracer class'"
	@echo ""

cycle1-cx:
	@echo ""
	@echo "$(SEP)"
	@echo "Cycle 1, step 2: Codex reviews Tracer"
	@echo "$(SEP)"
	@echo ""
	@echo "1. Stay on feat/tracer-cc branch (do NOT switch)"
	@echo ""
	@echo "2. Start Codex:"
	@echo "     codex"
	@echo ""
	@echo "3. Paste this prompt:"
	@echo "$(SEP)"
	@cat prompts/02-tracer-review.md
	@echo "$(SEP)"
	@echo ""
	@echo "4. After Codex saves the review, commit it:"
	@echo "     git add reviews/01-tracer-review.md"
	@echo "     git commit -m '[CX] review of Tracer'"
	@echo ""
	@echo "5. Read the review. Apply [BLOCKER] and [HIGH] fixes:"
	@echo "     - Either by hand, or by starting claude again with the review pasted"
	@echo "     - git commit -m '[H] apply Codex review fixes'"
	@echo ""
	@echo "6. Merge back to main when satisfied:"
	@echo "     git checkout main && git merge feat/tracer-cc"
	@echo ""

cycle2-cc:
	@echo ""
	@echo "$(SEP)"
	@echo "Cycle 2, step 1: Claude Code implements synthetic test"
	@echo "$(SEP)"
	@echo ""
	@echo "1. New branch off main (assumes Cycle 1 merged):"
	@echo "     git checkout main"
	@echo "     git checkout -b feat/synthetic-cc"
	@echo ""
	@echo "2. Start Claude Code:"
	@echo "     claude"
	@echo ""
	@echo "3. Paste this prompt:"
	@echo "$(SEP)"
	@cat prompts/03-synthetic-implement.md
	@echo "$(SEP)"
	@echo ""

cycle2-cx:
	@echo ""
	@echo "$(SEP)"
	@echo "Cycle 2, step 2: Codex writes adversarial assertions"
	@echo "$(SEP)"
	@echo ""
	@echo "1. Stay on feat/synthetic-cc branch"
	@echo ""
	@echo "2. Start Codex:"
	@echo "     codex"
	@echo ""
	@echo "3. Paste this prompt:"
	@echo "$(SEP)"
	@cat prompts/04-assertions-implement.md
	@echo "$(SEP)"
	@echo ""
	@echo "4. After Codex finishes, run verify:"
	@echo "     make verify"
	@echo ""

verify:
	@echo "Running synthetic test..."
	rm -f traces/synthetic.jsonl
	python3 -m validation.synthetic --output traces/synthetic.jsonl
	@echo ""
	@echo "Running adversarial assertions..."
	python3 validation/assert_synthetic.py traces/synthetic.jsonl

verify-v3:
	@echo "WARNING: verify-v3 uses dry-run traces. Dry-run byte-seconds are tracer-overhead-bound"
	@echo "and must not be used for paper figures or cross-condition claims."
	@echo ""
	@echo "Running final-v3 dry-run traces..."
	python3 -m agent.run_final_v3 --all --dry-run --out-dir /tmp/final_v3_dryrun
	@echo ""
	@echo "Validating final-v3 dry-run traces..."
	python3 -m validation.validate_final_v3 /tmp/final_v3_dryrun/*.jsonl
	@echo ""
	@echo "Analyzing final-v3 dry-run traces..."
	python3 -m analysis.final_v3 /tmp/final_v3_dryrun /tmp/final_v3_analysis /tmp/final_v3_figures

status:
	@echo ""
	@echo "Recent ping-pong commits:"
	@echo ""
	@git log --oneline 2>/dev/null | grep -E "\[(CC|CX|H)\]" | head -20 || echo "No tagged commits yet."
	@echo ""

.PHONY: help cycle1-cc cycle1-cx cycle2-cc cycle2-cx verify verify-v3 status
