export type MetricState = 'ok' | 'watch' | 'alert' | 'neutral'

export interface MetricCard {
  id: string
  label: string
  value: string
  hint: string
  state: MetricState
}

export interface StageMetric {
  label: string
  value: string
}

export type StageTelemetryMode =
  | 'timestamp'
  | 'duration'
  | 'gate'
  | 'status'
  | 'reserved'

export type StageTelemetryState =
  | 'complete'
  | 'active'
  | 'watch'
  | 'steady'
  | 'planned'

export interface StageTelemetry {
  stageId: string
  mode: StageTelemetryMode
  state: StageTelemetryState
  label: string
  value?: string
  startedAt?: string
  endedAt?: string
  durationMs?: number | null
}

export interface StageNode {
  id: string
  title: string
  subtitle: string
  status: 'flowing' | 'steady' | 'watch' | 'planned'
  x: number
  y: number
  metrics: StageMetric[]
}

export interface StageLink {
  id: string
  source: string
  target: string
  state: 'active' | 'steady' | 'planned'
}

export interface TimelineStep {
  id: string
  stageId?: string
  stamp: string
  title: string
  detail: string
  durationMs?: number | null
}

export interface ProjectionBasisEntry {
  label: string
  section: string
  field: string
  value: string
  reason: string
}

export interface SuggestionRecord {
  id: string
  alertId: string
  suggestionTs: string
  scope: 'alert' | 'cluster'
  ruleId: string
  severity: string
  priority: string
  summary: string
  context: {
    service: string
    srcDeviceKey: string
    clusterSize: number
    clusterWindowSec: number
    clusterFirstAlertTs: string
    clusterLastAlertTs: string
    clusterSampleAlertIds: string[]
    recentSimilar1h: number
    provider: string
  }
  evidenceBundle: {
    topology: Record<string, string | string[]>
    device: Record<string, string | string[]>
    change: Record<string, string | number | boolean | string[] | null>
    historical: Record<string, string | number | string[]>
  }
  hypotheses: string[]
  recommendedActions: string[]
  confidence: number
  confidenceLabel: string
  confidenceReason: string
  projectionBasis?: Record<string, ProjectionBasisEntry[]>
  timeline?: TimelineStep[]
  stageTelemetry?: StageTelemetry[]
}

export interface ClusterWatchItem {
  key: string
  service: string
  device: string
  progress: number
  target: number
  windowSec: number
  note: string
}

export interface StrategyControl {
  id: string
  label: string
  currentValue: string
  source: string
  detail: string
}

export interface FeedEvent {
  id: string
  stamp: string
  kind: 'raw' | 'alert' | 'suggestion'
  title: string
  detail: string
  service?: string
  device?: string
  scope?: 'alert' | 'cluster'
  relatedAlertId?: string
  relatedSuggestionId?: string
  provider?: string
  actionCount?: string
  hypothesisCount?: string
  evidence?: string
}

export type RuntimeDeltaKind = FeedEvent['kind'] | 'cluster' | 'system'

export interface RuntimeStreamDelta {
  id: string
  emittedAt: string
  kind: RuntimeDeltaKind
  stageIds: string[]
  feedIds: string[]
  reason: 'feed' | 'cluster-watch' | 'system'
}

export type RuntimeStreamEnvelope =
  | {
      type: 'snapshot'
      emittedAt: string
      snapshot: RuntimeSnapshot
    }
  | {
      type: 'delta'
      emittedAt: string
      snapshot: RuntimeSnapshot
      delta: RuntimeStreamDelta
    }
  | {
      type: 'heartbeat'
      emittedAt: string
    }

export interface RuntimeSnapshot {
  repo: {
    branch: string
    validation: string
  }
  runtime: {
    latestAlertTs: string
    latestSuggestionTs: string
    contextNote: string
  }
  defaultSuggestionId: string
  overviewMetrics: MetricCard[]
  cadence: {
    labels: string[]
    alerts: number[]
    suggestions: number[]
  }
  evidenceCoverage: {
    labels: string[]
    values: number[]
  }
  stageNodes: StageNode[]
  stageLinks: StageLink[]
  timeline: TimelineStep[]
  clusterWatch: ClusterWatchItem[]
  suggestions: SuggestionRecord[]
  strategyControls: StrategyControl[]
  feed: FeedEvent[]
  topologyNotes: Array<{ title: string; detail: string }>
}

export type CompareProviderType = 'template' | 'llm'
export type CompareProviderStatus = 'ready' | 'placeholder' | 'failed' | 'unavailable'
export type CompareDatasetKind = 'paired-fixture' | 'baseline-only'
export type CompareDatasetSource = 'fixture' | 'runtime'
export type CompareTabId =
  | 'explanation'
  | 'action'
  | 'stability'
  | 'runtime'
export type CompareExportFormat = 'json' | 'csv'

export interface CompareWindow {
  start: string
  end: string
  label: string
}

export interface CompareReplayMetadata {
  replayId: string
  replayLabel: string
  runId: string
  runCount: number
  window: CompareWindow
  source: string
  notes: string[]
}

export interface CompareMetricBundle {
  explanationCompleteness: number | null
  actionability: number | null
  evidenceBinding: number | null
  stability: number | null
  auditability: number | null
  hallucinationRate: number | null
  latencyMs: number | null
  estimatedCostUsd: number | null
  failureRate: number | null
}

export interface CompareOutputBlock {
  kind: 'summary' | 'hypotheses' | 'actions' | 'notes'
  title: string
  lines: string[]
}

export interface CompareEvidenceReference {
  id: string
  claim: string
  sourceSection: 'topology' | 'device' | 'change' | 'historical'
  sourceField: string
  sourceValue: string
  supported: boolean
}

export interface CompareUnsupportedClaim {
  id: string
  claim: string
  reason: string
  severity: 'low' | 'medium' | 'high'
}

export interface CompareProviderRuntimeMetadata {
  latencyMs: number | null
  inputTokens: number | null
  outputTokens: number | null
  estimatedCostUsd: number | null
  failure: boolean
  failureReason: string | null
  replayConsistency: number | null
  auditTrailCoverage: number | null
}

export interface CompareProviderEvaluation {
  providerType: CompareProviderType
  providerName: string
  status: CompareProviderStatus
  availability: 'available' | 'planned'
  metrics: CompareMetricBundle
  outputText: string
  outputBlocks: CompareOutputBlock[]
  recommendedActions: string[]
  evidenceReferences: CompareEvidenceReference[]
  unsupportedClaims: CompareUnsupportedClaim[]
  runtime: CompareProviderRuntimeMetadata
  notes: string[]
}

export interface CompareEvidenceBundle {
  topology: Record<string, string | string[]>
  device: Record<string, string | string[]>
  change: Record<string, string | number | boolean | string[] | null>
  historical: Record<string, string | number | string[]>
}

export interface CompareSampleUnit {
  id: string
  bundleId: string
  alertId: string
  ruleId: string
  severity: string
  service: string
  device: string
  path: string
  baselineStatus: string
  llmStatus: string
  replay: CompareReplayMetadata
  evidenceBundle: CompareEvidenceBundle
  baseline: CompareProviderEvaluation
  llm: CompareProviderEvaluation
  reviewNotes: string[]
}

export interface CompareWorkbenchDataset {
  id: string
  label: string
  kind: CompareDatasetKind
  source: CompareDatasetSource
  description: string
  defaultReplayId: string
  samples: CompareSampleUnit[]
}

export interface CompareDatasetFilters {
  replayId: string
  providerName: string
  severity: string
  ruleId: string
  service: string
  status: string
  query: string
}

export interface CompareKpiCard {
  id: string
  label: string
  ruleValue: number | null
  llmValue: number | null
  ruleDisplay: string
  llmDisplay: string
  deltaDisplay: string
  deltaState: 'improved' | 'regressed' | 'flat' | 'pending'
  note: string
}

export interface CompareTableColumn {
  id: string
  label: string
}
