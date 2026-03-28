# Runtime UI Semantic Map

## Core Runtime Story

- Source signal: `fortigate`
- Edge handoff: `ingest`, `forwarder`, `raw-topic`
- Deterministic alert: `correlator`, `alerts-topic`
- Cluster gate: `clusterWatch` plus `cluster-window` telemetry
- Suggestion emission: `aiops-agent`, `suggestions-topic`
- Control boundary: `remediation`

## Component Contracts

### `CurrentSliceHeader`

- Must answer: what happened, where it is now, and what the operator should inspect next
- Use active event data plus linked suggestion context
- Keep the header tied to one incident slice, not the whole dashboard

### `LifecyclePhaseStrip`

- Each phase maps to a real pipeline transition or a real control boundary
- `timestamp` means seen at a real time
- `duration` means measured elapsed transition time
- `gate` means threshold progress toward a cluster trigger
- `reserved` means visible but intentionally not live

### `TransitionTimingChip`

- Only use real transition timing
- Never show a full-progress bar for a static note

### `ClusterThresholdBar`

- Use `clusterWatch.progress / target`
- Wording must distinguish "close to trigger" from "already cluster-scope"

### `EvidenceDrawer`

- Context comes from `suggestion.context`
- Topology/device/change/historical sections come from `suggestion.evidenceBundle`
- Confidence remains evidence-backed and must not drift into marketing tone

### `ControlBoundaryCard`

- Shows approval, execution, and feedback posture
- Must preserve the distinction between visible and wired

### `CompareBranchPanel`

- Compare the same time window across branches
- Minimum metric set:
  - `alertCount`
  - `clusterTriggerCount`
  - `suggestionEmissionCount`
  - `operatorActionCount`
  - `remediationClosureCount`
  - `medianTransitionMs`
  - `tokenCost`
  - `cpuProxyPct`

### `ExportMetricsPanel`

- Treat export and replay as first-class artifacts
- Must make it obvious whether a branch can support review, conference figures, or operator replay
