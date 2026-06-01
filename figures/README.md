# Figures

Final-v3 figures are the paper-facing plots. Regenerate them with
`python3 -m analysis.final_v3 traces/final_v3`.

Historical v2 figures are retained as appendix/background material. Regenerate
them with `python3 -m analysis.plots traces/batch_v2/`. They summarize logical
trace-derived memory classes and analytical KV estimates, not hardware counter
measurements or physical memory-tier residency.

## Final-v3 figures

## Recommended paper figure set

If the final report needs a compact differentiated-memory-systems story, lead
with these figures in this order:

1. `final_v3/prompt_cache_reuse` for the coding replay's reused-prefix versus
   new-prefill split.
2. `final_v3/search_prompt_pollution` for the search replay's admission-control
   mechanism: same scan volume, different prompt pollution.
3. `final_v3/compaction_raw_context_kv` for the clearest active-working-set
   reduction result in analytical KV terms.
4. `final_v3/semantic_byte_steps` for the cross-workload semantic inventory on
   the safer step-normalized axis.
5. `fig4_dms_tier_proposal` only after the trace figures above, because it is a
   prescriptive implication diagram rather than direct measured evidence.

The remaining final-v3 figures are best treated as supporting diagnostics or
appendix material unless a specific section needs them.

**final_v3/prompt_cache_reuse** — Cached-token reuse by workflow and condition.
This is the clearest direct vLLM-facing plot: cache-on replay steps show
material prefix reuse while the cache-off ablation does not.

**final_v3/search_prompt_pollution** — Prompt growth in the search replay under
targeted versus broad retrieval. It shows the search-specific mechanism behind
the memory difference: broader retrieval inserts more returned search content
and selected snippets into prompt history, which increases downstream prompt and
KV pressure.

**final_v3/compaction_raw_context_kv** — Analytical KV footprint for the
compaction contrast. This is the most relevant plot for the tier-mapping
argument because it connects prompt-size reduction to KV-cache pressure.

**final_v3/compaction_raw_context_byte_steps** — Logical byte-step comparison
for raw versus compacted context. This is the step-normalized capacity-time
view, so it is the safer cross-workload comparison axis than wall-clock
byte-seconds. Use as supporting evidence; it is less direct than the KV plot.

**final_v3/semantic_byte_steps** — Resident semantic-class byte-steps.
This is the preferred cross-workload semantic inventory view because it keeps
the logical capacity-time signal while avoiding wall-clock drift. It is still
dense, so use it as supporting inventory rather than as the single headline
figure.

**final_v3/semantic_byte_seconds** — Resident semantic-class byte-seconds.
Keep this as supporting timing context only. `search_corpus_scan` is excluded
from both semantic inventory plots and retained only in the search funnel
because it is a scan-pressure proxy rather than resident prompt/KV state.

**final_v3/logical_kv_pressure** — Default-trace logical projected KV bytes by
semantic class. Useful for scale comparison across workloads, but secondary to
the targeted contrast plots.

**final_v3/duplication_factor** — Logical duplication by semantic class. This is
diagnostic support, not a headline result.

**final_v3/lifetime_reuse** — Object reuse versus lifetime by semantic class.
This is useful for checking tier-mapping intuition, with the x-axis using
step-normalized lifetime for cross-workload comparability and bubble area
indicating object bytes.

## Historical v2 figures

**fig1_lifetime_size_scatter** — Object lifetime versus size across historical
v2 traces. It shows the broad split between large analytical KV objects and much
smaller logical content.

**fig2_memory_pressure_timeline** — Dual-axis timeline of live analytical KV
cache versus live logical content for one historical coding replay.

**fig3_capacity_vs_logical_reads** — Side-by-side capacity-time and logical read
event counts. The point is a logical trace dichotomy, not a bandwidth
measurement: analytical KV dominates byte-seconds while logical content
dominates prompt-construction reads.

**fig4_dms_tier_proposal** — Prescriptive tier-mapping implication derived from
the trace patterns. It is a proposal diagram, not evidence that this project
measured physical placement or migration across memory tiers.

**fig5_reuse_vs_lifetime** — Historical per-object reuse count versus lifetime,
with bubble area scaled by object size and multiplicity.

**fig6_reuse_hist_lifetime_stack** — Historical reuse histogram stacked by
time-based lifetime buckets.

**fig7_reuse_hist_memory_class_stack** — Historical reuse histogram stacked by
conceptual memory class.
