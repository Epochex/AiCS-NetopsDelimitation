# LCORE-D Window Dual-Review Protocol

This protocol is for the independent dual review of LCORE-D incident windows sampled from the current
sessionized `2283`-window denominator.

## Artifacts

The packet generator writes:

- `window_dual_review_master.jsonl`
- `window_dual_review_reviewer_a.jsonl`
- `window_dual_review_reviewer_b.jsonl`
- `window_dual_review_sheet.csv`
- `window_dual_review_summary.json`

The reviewer files are identical except for the pre-filled reviewer name. Reviewers should not see each
other's decisions before submission.

## Review Fields

Each sampled window should receive the following judgments:

- `should_invoke_external`
  - `true` if the window should enter external interpretation under the paper's bounded-advisory model.
  - `false` if local handling is sufficient.
- `representative_alert_sufficient`
  - `true` if the selected representative alerts are enough to represent the window for bounded external review.
  - `false` if the representative set omits a critical alert or modality.
- `selected_device_covered`
  - `true` if the selected evidence covers the device scope needed for the judgment.
- `selected_path_covered`
  - `true` if the selected evidence covers the path or topology scope needed for the judgment.
- `timeline_sufficient`
  - `true` if the window timeline is sufficient to support the judgment.
- `false_skip_if_local`
  - `true` if keeping the window local would be an unsafe skip.
- `boundary_should_split_further`
  - `true` if the current window should be split into smaller windows.
- `boundary_should_merge_adjacent`
  - `true` if the current window should be merged with adjacent context.

Each record also includes `review_notes` for free-form explanation.

## Decision Style

Reviewers should judge the current system object, not an imagined future system.

- Evaluate the current selected or excluded evidence surfaces as written.
- Do not assume access to hidden logs or traces beyond the packet.
- Treat the provider path as bounded and advisory only.
- If the current packet lacks enough evidence, mark the coverage or sufficiency field `false` and explain why.

## High-Priority Strata

The current packet prioritizes windows from these buckets:

- `strict_budget_false_skip`
- `high_value_retained`
- `window_risk_tier_extra`
- `mixed_fault_and_transient`
- `pressure_self_healing`
- `local_single_transient`
- `topology_split_vs_adaptive_merge`

These strata are the main reviewer-facing attack surface for the paper.

## Aggregation

After both reviewers finish, run:

```bash
python3 -m core.benchmark.window_review_agreement \
  --review-jsonl /path/to/window_dual_review_reviewer_a.jsonl \
  --review-jsonl /path/to/window_dual_review_reviewer_b.jsonl \
  --output-json /path/to/window_dual_review_agreement.json \
  --output-adjudicated-jsonl /path/to/window_dual_review_adjudicated.jsonl
```

If a field has a tie, the adjudicated output will mark that window as needing adjudication.
