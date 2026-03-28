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

export interface CompareWindow {
  start: string
  end: string
  label: string
}

export interface CompareCurrentSlice {
  title: string
  alertId: string
  service: string
  device: string
  ruleId: string
  focus: string
}

export interface CompareMetrics {
  alertCount: number
  clusterTriggerCount: number
  suggestionEmissionCount: number
  operatorActionCount: number
  remediationClosureCount: number
  medianTransitionMs: number
  tokenCost: number
  cpuProxyPct: number
}

export interface CompareTimelineStep {
  stamp: string
  title: string
  detail: string
  state: 'observed' | 'gated' | 'generated' | 'acted' | 'closed' | 'reserved'
}

export interface CompareControlBoundary {
  status: string
  detail: string
  exportReadiness: 'ready' | 'partial' | 'blocked'
}

export interface CompareExportArtifacts {
  status: 'ready' | 'partial' | 'blocked'
  detail: string
  items: string[]
}

export interface CompareFixtureBranch {
  id: string
  label: string
  mode: 'rule-only' | 'agent-enhanced'
  timeWindow: CompareWindow
  summary: string
  currentSlice: CompareCurrentSlice
  metrics: CompareMetrics
  timeline: CompareTimelineStep[]
  controlBoundary: CompareControlBoundary
  exportArtifacts: CompareExportArtifacts
}

export interface CompareHighlight {
  label: string
  ruleOnly: string
  agentEnhanced: string
  delta: string
}

export interface RuntimeUiScenario {
  id: string
  label: string
  state: string
  why: string
  propsPreview: string[]
}

export interface RuntimeUiStory {
  componentId: string
  intent: string
  scenarios: RuntimeUiScenario[]
}

export interface RuntimeUiStoryCatalog {
  components: RuntimeUiStory[]
}
