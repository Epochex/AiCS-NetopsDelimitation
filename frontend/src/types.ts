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
  stamp: string
  title: string
  detail: string
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
