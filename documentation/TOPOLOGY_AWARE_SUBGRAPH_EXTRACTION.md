# Topology-Aware Subgraph Extraction

This note defines the LCORE-era refinement of the alert downstream reasoning layer.

## Goal

The previous AIOps path produced one alert-scope suggestion for every severity-qualified confirmed alert, and produced an extra cluster-scope suggestion when the same-key temporal cluster fired. That is useful as an engineering baseline, but it does not reduce LLM budget for self-healing or low-value events.

The new structure adds a bounded topology-aware subgraph before remote LLM escalation:

`confirmed alert -> candidate_event_graph -> topology_subgraph -> llm_invocation_gate -> stage request`

## Design

The subgraph extractor is deterministic. It does not decide alert validity and it does not execute remediation.

It classifies local evidence into three roles:

- `root_candidate`: the most likely seed device or path from the confirmed alert.
- `symptom`: adjacent topology neighbors, path nodes, and recent similar alert samples.
- `noise`: low-recurrence single-slice evidence, transient/self-healing labels, or missing topology-neighbor context.

The extraction uses only existing bounded context:

- `alert_ref`
- `topology_context`
- `path_context`
- `historical_context`
- `device_context`
- deterministic rule metrics

## LLM Gate

The `llm_invocation_gate` is a selective-invocation hint. A skipped case still gets local/template bounded output, but it does not need external LLM critique/planning.

This lets evaluation compare:

- Full invocation baseline: every qualifying alert is escalated.
- Topology-gated invocation: only high-value subgraphs are escalated.

Primary metrics:

- LLM call reduction ratio.
- High-value alert recall.
- Average selected subgraph size.
- Structured review quality through `ReviewVerdict`.

## Relation To BiAn

BiAn uses topology and timeline as a second-stage integrated reasoning signal, and extracts a smaller sub-topology around suspect devices. This implementation adapts that idea to the current NetOps architecture by keeping the extractor deterministic, post-alert, and contract-bound rather than adding a broad multi-agent planner.


