import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { RuntimeConnectionState } from '../hooks/useRuntimeSnapshot'
import type {
  FeedEvent,
  RuntimeSnapshot,
  RuntimeStreamDelta,
  StageLink,
  StageNode,
  StageTelemetry,
  StrategyControl,
  SuggestionRecord,
} from '../types'
import {
  formatDurationMs,
  formatMaybeTimestamp,
  parseTimestamp,
  timestampTooltip,
} from '../utils/time'

const TopologyCanvas = lazy(() =>
  import('./TopologyCanvas').then((module) => ({
    default: module.TopologyCanvas,
  })),
)

interface LiveFlowConsoleProps {
  connectionState: RuntimeConnectionState
  snapshot: RuntimeSnapshot
  latestDelta: RuntimeStreamDelta | null
  selectedSuggestion: SuggestionRecord
  onSelectSuggestion: (suggestionId: string) => void
  transportIssue?: string | null
  locale: 'en' | 'zh'
  onOpenEvidence: () => void
  onOpenRuntimeSheet: () => void
}

interface LifecycleBand {
  mode: StageTelemetry['mode']
  state: StageTelemetry['state']
  label: string
  value: string
  detail: string
  stamp?: string
  meter: number
  durationMs?: number | null
  tone: 'raw' | 'alert' | 'suggestion' | 'neutral' | 'planned'
}

interface LifecyclePhase {
  id: string
  title: string
  purpose: string
  systems: string
  status: StageNode['status']
  stageIds: string[]
  facts: string[]
  band: LifecycleBand
}

interface LifecycleIntegrityIssue {
  id: string
  detail: string
  severity: 'hard' | 'soft'
}

interface HistoricalIncidentEvent extends FeedEvent {
  dedupeKey: string
  mergedSuggestionCount: number
  firstSeenTs: string
  lastSeenTs: string
  problem: string
  inference: string
  recommendation: string
  scopeMeaning: string
}

interface GuidedStage {
  id: string
  title: string
  summary: string
  value: string
  detail: string
  tone: LifecycleBand['tone']
  status: StageNode['status']
  phaseIds: string[]
  facts: string[]
  stamp?: string
  durationMs?: number | null
}

interface StoryCopy {
  eyebrow: string
  headline: string
  headlineAccent: string
  summary: string
  whatHappenedLabel: string
  whatHappened: string
  whyLabel: string
  why: string
  nextLabel: string
  next: string
}

function controlValue(controls: StrategyControl[], label: string) {
  return controls.find((control) => control.label === label)?.currentValue ?? 'n/a'
}

function stageMetricValue(node: StageNode | undefined, label: string) {
  return node?.metrics.find((metric) => metric.label === label)?.value ?? 'n/a'
}

function buildLifecycle(
  snapshot: RuntimeSnapshot,
  linkedSuggestion: SuggestionRecord,
): LifecyclePhase[] {
  const stageLookup = new Map(snapshot.stageNodes.map((node) => [node.id, node]))
  const telemetryLookup = new Map(
    (linkedSuggestion.stageTelemetry ?? []).map((item) => [item.stageId, item]),
  )
  const clusterTarget = Number.parseInt(
    controlValue(snapshot.strategyControls, 'AIOPS_CLUSTER_MIN_ALERTS'),
    10,
  )
  const clusterWindow = Number.parseInt(
    controlValue(snapshot.strategyControls, 'AIOPS_CLUSTER_WINDOW_SEC'),
    10,
  )
  const safeClusterTarget = Number.isFinite(clusterTarget) ? clusterTarget : 3
  const safeClusterWindow = Number.isFinite(clusterWindow) ? clusterWindow : 600
  const clusterProgress = Math.max(
    0,
    ...snapshot.clusterWatch.map((item) => item.progress),
  )
  const clusterRemaining = Math.max(0, safeClusterTarget - clusterProgress)
  const fortigate = stageLookup.get('fortigate')
  const ingest = stageLookup.get('ingest')
  const forwarder = stageLookup.get('forwarder')
  const rawTopic = stageLookup.get('raw-topic')
  const correlator = stageLookup.get('correlator')
  const alertsTopic = stageLookup.get('alerts-topic')
  const aiopsAgent = stageLookup.get('aiops-agent')
  const suggestionsTopic = stageLookup.get('suggestions-topic')
  const remediation = stageLookup.get('remediation')
  const sourceTs =
    telemetryLookup.get('raw-topic')?.endedAt ??
    telemetryLookup.get('ingest')?.endedAt ??
    telemetryLookup.get('fortigate')?.endedAt
  const handoffTs =
    telemetryLookup.get('raw-topic')?.endedAt ??
    telemetryLookup.get('forwarder')?.endedAt ??
    telemetryLookup.get('ingest')?.endedAt
  const alertTs =
    telemetryLookup.get('alerts-topic')?.endedAt ??
    telemetryLookup.get('correlator')?.endedAt
  const suggestionTs =
    telemetryLookup.get('suggestions-topic')?.endedAt ??
    telemetryLookup.get('aiops-agent')?.endedAt
  const clusterTelemetry = telemetryLookup.get('cluster-window')
  const clusterState: StageNode['status'] =
    linkedSuggestion.scope === 'cluster'
      ? 'flowing'
      : clusterProgress > 0
        ? 'watch'
        : 'steady'

  return [
    {
      id: 'source-signal',
      title: 'Source Signal',
      purpose: 'A real device log has entered the platform.',
      systems: 'FortiGate',
      status: fortigate?.status ?? 'steady',
      stageIds: ['fortigate'],
      facts: [
        stageMetricValue(fortigate, 'mode'),
        stageMetricValue(fortigate, 'signal'),
      ],
      band: {
        mode: 'timestamp',
        state: 'active',
        label: 'seen',
        value: sourceTs ? formatMaybeTimestamp(sourceTs, 'time') : 'live',
        detail: 'source plane stays hot until a new raw fact arrives',
        stamp: sourceTs,
        meter: 100,
        durationMs: 0,
        tone: 'raw',
      },
    },
    {
      id: 'edge-handoff',
      title: 'Edge Parse + Handoff',
      purpose: 'The edge normalizes, checkpoints, and hands the fact to the raw stream.',
      systems: 'fortigate-ingest -> edge-forwarder -> netops.facts.raw.v1',
      status:
        rawTopic?.status === 'flowing' || ingest?.status === 'flowing'
          ? 'flowing'
          : 'steady',
      stageIds: ['ingest', 'forwarder', 'raw-topic'],
      facts: [
        `parsed ${stageMetricValue(ingest, 'parsed')}`,
        `freshness ${stageMetricValue(rawTopic, 'freshness')}`,
        `drop local deny ${stageMetricValue(forwarder, 'drop local deny')}`,
      ],
      band: {
        mode: 'timestamp',
        state: 'complete',
        label: 'handoff',
        value: handoffTs ? formatMaybeTimestamp(handoffTs, 'time') : 'ready',
        detail: `backlog ${stageMetricValue(ingest, 'backlog')} · raw topic ready`,
        stamp: handoffTs,
        meter: 100,
        durationMs: 0,
        tone: 'raw',
      },
    },
    {
      id: 'deterministic-alert',
      title: 'Deterministic Alert',
      purpose: 'The correlator decides whether the event crosses the rule threshold.',
      systems: 'core-correlator -> netops.alerts.v1',
      status:
        alertsTopic?.status === 'flowing' || correlator?.status === 'flowing'
          ? 'flowing'
          : 'steady',
      stageIds: ['correlator', 'alerts-topic'],
      facts: [
        `threshold ${stageMetricValue(correlator, 'deny threshold')}`,
        `latest ${stageMetricValue(alertsTopic, 'latest')}`,
      ],
      band: {
        mode: telemetryLookup.get('correlator')?.mode ?? 'duration',
        state: telemetryLookup.get('correlator')?.state ?? 'steady',
        label: 'elapsed',
        value: formatDurationMs(telemetryLookup.get('correlator')?.durationMs),
        detail:
          alertTs && sourceTs
            ? `${formatMaybeTimestamp(sourceTs, 'time')} -> ${formatMaybeTimestamp(alertTs, 'time')}`
            : 'source fact to alert emission',
        stamp: alertTs,
        meter: 100,
        durationMs: telemetryLookup.get('correlator')?.durationMs,
        tone: 'alert',
      },
    },
    {
      id: 'cluster-gate',
      title: 'Cluster Gate',
      purpose: 'Repeated same-key alerts are counted until they become cluster-legible.',
      systems: 'same-key aggregation window',
      status: clusterState,
      stageIds: ['cluster-window'],
      facts: [
        `${clusterProgress}/${safeClusterTarget} in ${safeClusterWindow}s`,
        linkedSuggestion.scope === 'cluster'
          ? 'cluster path already reached'
          : `${clusterRemaining} more needed for cluster trigger`,
      ],
      band: {
        mode: 'gate',
        state: clusterTelemetry?.state ?? (clusterProgress > 0 ? 'watch' : 'steady'),
        label: 'progress',
        value: `${clusterProgress}/${safeClusterTarget}`,
        detail:
          linkedSuggestion.scope === 'cluster'
            ? `cluster gate reached inside ${safeClusterWindow}s`
            : `${clusterRemaining} more matching alert(s) needed inside ${safeClusterWindow}s`,
        stamp: clusterTelemetry?.endedAt,
        meter:
          safeClusterTarget > 0
            ? Math.max(10, Math.min(100, (clusterProgress / safeClusterTarget) * 100))
            : 0,
        durationMs: clusterTelemetry?.durationMs,
        tone: 'alert',
      },
    },
    {
      id: 'suggestion-emission',
      title: 'AIOps Suggestion',
      purpose: 'Evidence is bundled into structured operator guidance.',
      systems: 'core-aiops-agent -> netops.aiops.suggestions.v1',
      status:
        suggestionsTopic?.status === 'flowing' || aiopsAgent?.status === 'flowing'
          ? 'flowing'
          : 'steady',
      stageIds: ['aiops-agent', 'suggestions-topic'],
      facts: [
        `${linkedSuggestion.scope}-scope via ${linkedSuggestion.context.provider}`,
        stageMetricValue(suggestionsTopic, 'current day'),
      ],
      band: {
        mode: telemetryLookup.get('aiops-agent')?.mode ?? 'duration',
        state: telemetryLookup.get('aiops-agent')?.state ?? 'steady',
        label: 'elapsed',
        value: formatDurationMs(telemetryLookup.get('aiops-agent')?.durationMs),
        detail:
          suggestionTs && alertTs
            ? `${formatMaybeTimestamp(alertTs, 'time')} -> ${formatMaybeTimestamp(suggestionTs, 'time')}`
            : 'alert evidence to suggestion emission',
        stamp: suggestionTs,
        meter: 100,
        durationMs: telemetryLookup.get('aiops-agent')?.durationMs,
        tone: 'suggestion',
      },
    },
    {
      id: 'remediation-boundary',
      title: 'Remediation Boundary',
      purpose: 'Approval, execution, and feedback stay visible as the next control surface.',
      systems: 'approval -> execution -> feedback',
      status: remediation?.status ?? 'planned',
      stageIds: ['remediation'],
      facts: [
        stageMetricValue(remediation, 'status'),
        stageMetricValue(remediation, 'feedback'),
      ],
      band: {
        mode: 'reserved',
        state: 'planned',
        label: 'boundary',
        value: 'manual',
        detail: 'reserved control point · execution path not wired',
        meter: 10,
        durationMs: null,
        tone: 'planned',
      },
    },
  ]
}

function buildLifecyclePhases(
  snapshot: RuntimeSnapshot,
  linkedSuggestion: SuggestionRecord,
): LifecyclePhase[] {
  return buildLifecycle(snapshot, linkedSuggestion)
}

function pulseKindForDelta(
  kind: RuntimeStreamDelta['kind'] | FeedEvent['kind'] | undefined,
): FeedEvent['kind'] {
  if (kind === 'raw' || kind === 'alert') {
    return kind
  }
  return 'suggestion'
}

function toneForDelta(
  kind: RuntimeStreamDelta['kind'] | FeedEvent['kind'] | undefined,
) {
  if (kind === 'system') {
    return 'live'
  }
  return pulseKindForDelta(kind)
}

function currentPhaseId(
  deltaKind: RuntimeStreamDelta['kind'] | undefined,
  eventKind: FeedEvent['kind'] | undefined,
) {
  if (deltaKind === 'cluster') {
    return 'cluster-gate'
  }

  if (eventKind === 'raw') {
    return 'edge-handoff'
  }

  if (eventKind === 'alert') {
    return 'deterministic-alert'
  }

  return 'suggestion-emission'
}

function suggestionForEvent(
  event: FeedEvent | undefined,
  suggestions: SuggestionRecord[],
  fallback: SuggestionRecord,
) {
  if (!event) {
    return fallback
  }

  if (event.relatedSuggestionId) {
    const direct = suggestions.find(
      (suggestion) => suggestion.id === event.relatedSuggestionId,
    )
    if (direct) {
      return direct
    }
  }

  if (event.relatedAlertId) {
    const fromAlert = suggestions.find(
      (suggestion) => suggestion.alertId === event.relatedAlertId,
    )
    if (fromAlert) {
      return fromAlert
    }
  }

  if (event.service || event.device) {
    const byContext = suggestions.find(
      (suggestion) =>
        suggestion.context.service === event.service &&
        suggestion.context.srcDeviceKey === event.device,
    )
    if (byContext) {
      return byContext
    }
  }

  return fallback
}

function canonicalDeviceIdentity(suggestion: SuggestionRecord) {
  const srcmac = suggestion.evidenceBundle.device.srcmac
  if (
    typeof srcmac === 'string' &&
    srcmac.trim().length > 0 &&
    srcmac.trim().toLowerCase() !== 'none'
  ) {
    return srcmac.trim().toLowerCase()
  }

  const deviceName = suggestion.evidenceBundle.device.device_name
  if (typeof deviceName === 'string' && deviceName.trim().length > 0) {
    return deviceName.trim().toLowerCase()
  }

  return suggestion.context.srcDeviceKey.trim().toLowerCase()
}

function incidentKeyForSuggestion(suggestion: SuggestionRecord) {
  return [
    suggestion.ruleId.trim().toLowerCase(),
    suggestion.scope,
    suggestion.context.service.trim().toLowerCase(),
    canonicalDeviceIdentity(suggestion),
  ].join('::')
}

function incidentProblemSummary(
  suggestion: SuggestionRecord,
  locale: 'en' | 'zh',
) {
  const ruleLabel = prettyRuleName(suggestion.ruleId)
  const deviceLabel = friendlyDeviceName(suggestion)

  if (locale === 'zh') {
    return `${ruleLabel} 在 ${deviceLabel} 的 ${suggestion.context.service} 路径上命中了确定性阈值。`
  }

  return `${ruleLabel} crossed its deterministic threshold on ${deviceLabel} for ${suggestion.context.service}.`
}

function incidentInferenceSummary(
  suggestion: SuggestionRecord,
  locale: 'en' | 'zh',
) {
  const hypothesis = suggestion.hypotheses[0]
  if (hypothesis) {
    return hypothesis
  }

  return locale === 'zh'
    ? '当前没有单独的假设文本，先沿着附带证据继续检查。'
    : 'No standalone hypothesis text is attached yet, so continue from the evidence already attached.'
}

function incidentScopeMeaning(
  suggestion: SuggestionRecord,
  locale: 'en' | 'zh',
) {
  if (suggestion.scope === 'cluster') {
    return locale === 'zh'
      ? '这表示同一键值的重复告警已经跨过聚合门槛，问题不再是单次孤立波动。'
      : 'This means repeated same-key alerts crossed the cluster gate, so the issue is no longer an isolated one-off path.'
  }

  return locale === 'zh'
    ? '这表示证据目前仍然集中在一条服务/设备路径上，还没有扩展成重复模式事件。'
    : 'This means the evidence is still concentrated on one service/device path and has not widened into a repeated-pattern incident yet.'
}

function groupedRefreshLabel(
  mergedSuggestionCount: number,
  locale: 'en' | 'zh',
) {
  if (locale === 'zh') {
    return mergedSuggestionCount > 1
      ? `已合并 ${mergedSuggestionCount} 次建议刷新`
      : '当前只有 1 次建议刷新'
  }

  return mergedSuggestionCount > 1
    ? `merged ${mergedSuggestionCount} suggestion refreshes`
    : 'single suggestion refresh'
}

function historicalIncidentQueue(
  suggestions: SuggestionRecord[],
  locale: 'en' | 'zh',
): HistoricalIncidentEvent[] {
  const sortedSuggestions = suggestions
    .slice()
    .sort((left, right) => {
      const leftTs = parseTimestamp(left.suggestionTs)?.getTime() ?? 0
      const rightTs = parseTimestamp(right.suggestionTs)?.getTime() ?? 0
      return rightTs - leftTs
    })

  const groupedSuggestions = new Map<string, SuggestionRecord[]>()
  sortedSuggestions.forEach((suggestion) => {
    const key = incidentKeyForSuggestion(suggestion)
    const existing = groupedSuggestions.get(key)
    if (existing) {
      existing.push(suggestion)
      return
    }
    groupedSuggestions.set(key, [suggestion])
  })

  return Array.from(groupedSuggestions.entries()).map(([dedupeKey, bucket]) => {
    const latestSuggestion = bucket[0]
    const earliestSuggestion = bucket[bucket.length - 1]
    const deviceLabel = friendlyDeviceName(latestSuggestion)
    const refreshLabel = groupedRefreshLabel(bucket.length, locale)

    return {
      id: `incident-${dedupeKey}`,
      dedupeKey,
      stamp: latestSuggestion.suggestionTs,
      kind: 'suggestion' as const,
      title:
        locale === 'zh'
          ? `${latestSuggestion.context.service} 在 ${deviceLabel} 上出现问题`
          : `${latestSuggestion.context.service} anomaly on ${deviceLabel}`,
      detail:
        locale === 'zh'
          ? `${refreshLabel}；${incidentScopeMeaning(latestSuggestion, locale)}`
          : `${refreshLabel}; ${incidentScopeMeaning(latestSuggestion, locale)}`,
      scope: latestSuggestion.scope,
      relatedAlertId: latestSuggestion.alertId,
      relatedSuggestionId: latestSuggestion.id,
      service: latestSuggestion.context.service,
      device: deviceLabel,
      provider: latestSuggestion.context.provider,
      actionCount: String(latestSuggestion.recommendedActions.length),
      hypothesisCount: String(latestSuggestion.hypotheses.length),
      evidence: evidenceKinds(latestSuggestion).join(' + '),
      mergedSuggestionCount: bucket.length,
      firstSeenTs: earliestSuggestion.suggestionTs,
      lastSeenTs: latestSuggestion.suggestionTs,
      problem: incidentProblemSummary(latestSuggestion, locale),
      inference: incidentInferenceSummary(latestSuggestion, locale),
      recommendation: primaryRecommendation(latestSuggestion),
      scopeMeaning: incidentScopeMeaning(latestSuggestion, locale),
    }
  })
}

function phasesForGuidedStage(
  lifecycle: LifecyclePhase[],
  selectedGuidedStage: GuidedStage,
) {
  return lifecycle.filter((phase) =>
    phase.stageIds.some((stageId) => selectedGuidedStage.phaseIds.includes(stageId)),
  )
}

function stageNodeTitle(
  snapshot: RuntimeSnapshot,
  stageId: string,
  locale: 'en' | 'zh',
) {
  const matched = snapshot.stageNodes.find((node) => node.id === stageId)
  if (matched) {
    return matched.title
  }
  if (stageId === 'cluster-window') {
    return locale === 'zh' ? '聚合窗口' : 'Cluster window'
  }
  return stageId
}

function stageNodeSubtitle(
  snapshot: RuntimeSnapshot,
  stageId: string,
  locale: 'en' | 'zh',
) {
  const matched = snapshot.stageNodes.find((node) => node.id === stageId)
  if (matched) {
    return matched.subtitle
  }
  if (stageId === 'cluster-window') {
    return locale === 'zh'
      ? '相同键值重复统计'
      : 'same-key aggregation window'
  }
  return locale === 'zh' ? '运行阶段' : 'runtime stage'
}

function stageNodeMetrics(
  snapshot: RuntimeSnapshot,
  stageId: string,
  locale: 'en' | 'zh',
  phase?: LifecyclePhase,
) {
  const matched = snapshot.stageNodes.find((node) => node.id === stageId)
  if (matched) {
    return matched.metrics
  }

  if (stageId === 'cluster-window') {
    return [
      {
        label: locale === 'zh' ? '门槛' : 'gate',
        value: phase?.band.value ?? 'n/a',
      },
      {
        label: locale === 'zh' ? '说明' : 'detail',
        value: phase?.band.detail ?? (locale === 'zh' ? '聚合窗口' : 'aggregation window'),
      },
    ]
  }

  return []
}

function stageLinkStateFromStatus(status: StageNode['status']): StageLink['state'] {
  if (status === 'planned') {
    return 'planned'
  }

  return status === 'steady' || status === 'watch' ? 'steady' : 'active'
}

function buildStageProcessGraph(
  snapshot: RuntimeSnapshot,
  selectedStagePhases: LifecyclePhase[],
  locale: 'en' | 'zh',
) {
  const orderedStageIds = Array.from(
    new Set(selectedStagePhases.flatMap((phase) => phase.stageIds)),
  )

  const graphNodes: StageNode[] = orderedStageIds.map((stageId, index) => {
    const phase = selectedStagePhases.find((item) => item.stageIds.includes(stageId))
    const matched = snapshot.stageNodes.find((node) => node.id === stageId)

    return {
      id: stageId,
      title: stageNodeTitle(snapshot, stageId, locale),
      subtitle:
        matched?.subtitle ??
        phase?.title ??
        stageNodeSubtitle(snapshot, stageId, locale),
      status: matched?.status ?? phase?.status ?? 'steady',
      x: index * 290,
      y: index % 2 === 0 ? 64 : 136,
      metrics: stageNodeMetrics(snapshot, stageId, locale, phase).slice(0, 3),
    }
  })

  const graphLinks: StageLink[] = orderedStageIds.slice(0, -1).map((stageId, index) => {
    const target = orderedStageIds[index + 1]
    const targetNode = graphNodes.find((node) => node.id === target)

    return {
      id: `selected-stage-link-${stageId}-${target}`,
      source: stageId,
      target,
      state: stageLinkStateFromStatus(targetNode?.status ?? 'steady'),
    }
  })

  return {
    nodes: graphNodes,
    links: graphLinks,
  }
}

function reconstructedTimeline(
  linkedSuggestion: SuggestionRecord,
  snapshot: RuntimeSnapshot,
  lifecycle: LifecyclePhase[],
) {
  const existingTimeline =
    linkedSuggestion.timeline && linkedSuggestion.timeline.length > 0
      ? linkedSuggestion.timeline
      : snapshot.timeline

  if (existingTimeline.length > 0) {
    return existingTimeline
  }

  return lifecycle.map((phase) => ({
    id: `reconstructed-${phase.id}`,
    stageId: phase.stageIds[0],
    stamp:
      phase.band.stamp ??
      linkedSuggestion.suggestionTs ??
      snapshot.runtime.latestSuggestionTs,
    title: phase.title,
    detail: `${phase.purpose} ${phase.facts.join(' · ')}`.trim(),
    durationMs: phase.band.durationMs,
  }))
}

function currentDayVolume(snapshot: RuntimeSnapshot) {
  const metric = snapshot.overviewMetrics.find(
    (item) => item.id === 'current-day-volume',
  )
  if (!metric) {
    return null
  }

  const match = metric.value.match(/(\d+)\s*\/\s*(\d+)/)
  if (!match) {
    return null
  }

  return {
    alerts: Number.parseInt(match[1], 10),
    suggestions: Number.parseInt(match[2], 10),
  }
}

function lifecycleIntegrityIssues(
  snapshot: RuntimeSnapshot,
  linkedSuggestion: SuggestionRecord,
  connectionState: RuntimeConnectionState,
  transportIssue?: string | null,
): LifecycleIntegrityIssue[] {
  const issues: LifecycleIntegrityIssue[] = []
  if (transportIssue) {
    issues.push({
      id: 'transport-issue',
      detail: transportIssue,
      severity: 'hard',
    })
  }
  const missingTimeline = (linkedSuggestion.timeline?.length ?? 0) === 0
  const missingTelemetry = (linkedSuggestion.stageTelemetry?.length ?? 0) === 0

  if (
    connectionState !== 'fallback' &&
    connectionState !== 'connecting' &&
    (missingTimeline || missingTelemetry)
  ) {
    issues.push({
      id: 'missing-telemetry',
      detail:
        'Live snapshot for the active suggestion is missing timeline/stageTelemetry, so lifecycle timing cannot be trusted.',
      severity: 'hard',
    })
  }

  const latestAlert = parseTimestamp(snapshot.runtime.latestAlertTs)
  const latestSuggestion = parseTimestamp(snapshot.runtime.latestSuggestionTs)
  if (latestAlert && latestSuggestion) {
    const skewMs = latestSuggestion.getTime() - latestAlert.getTime()
    if (skewMs > 15 * 60_000) {
      issues.push({
        id: 'stream-skew',
        detail: `Latest suggestion timestamp leads the latest alert timestamp by ${formatDurationMs(skewMs)}.`,
        severity: 'soft',
      })
    }
  }

  const volume = currentDayVolume(snapshot)
  if (volume && volume.alerts === 0 && volume.suggestions > 0) {
    issues.push({
      id: 'volume-skew',
      detail: `Current-day volume is skewed: ${volume.alerts} alerts / ${volume.suggestions} suggestions.`,
      severity: 'soft',
    })
  }

  return issues
}

function primaryRecommendation(suggestion: SuggestionRecord) {
  return (
    suggestion.recommendedActions[0] ??
    'Inspect the evidence bundle before widening operator action.'
  )
}

function friendlyDeviceName(suggestion: SuggestionRecord) {
  const deviceName = suggestion.evidenceBundle.device.device_name
  if (typeof deviceName === 'string' && deviceName.trim().length > 0) {
    return deviceName.trim()
  }
  return suggestion.context.srcDeviceKey
}

function prettyRuleName(ruleId: string) {
  return ruleId
    .replace(/_v\d+$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function storyScopeLabel(
  suggestion: SuggestionRecord,
  locale: 'en' | 'zh',
) {
  if (locale === 'zh') {
    return suggestion.scope === 'cluster' ? '重复模式事件' : '单路径事件'
  }
  return suggestion.scope === 'cluster' ? 'repeated-pattern incident' : 'single-path incident'
}

function storyCopy(
  suggestion: SuggestionRecord,
  locale: 'en' | 'zh',
): StoryCopy {
  const deviceName = friendlyDeviceName(suggestion)
  const scopeLabel = storyScopeLabel(suggestion, locale)
  const ruleLabel = prettyRuleName(suggestion.ruleId)
  const recentSimilar = suggestion.context.recentSimilar1h

  if (locale === 'zh') {
    return {
      eyebrow: '当前运行事件',
      headline: '重复 deny 流量',
      headlineAccent: suggestion.context.service,
      summary: `${deviceName} 的 ${suggestion.context.service} 在规则窗口内连续命中阈值，系统已给出一条可审查的${scopeLabel}建议。`,
      whatHappenedLabel: '发生了什么',
      whatHappened: `${ruleLabel} 在 ${friendlyDeviceName(suggestion)} 上被触发，当前焦点是 ${suggestion.context.service} 这条通信路径。`,
      whyLabel: '为什么重要',
      why: recentSimilar > 0
        ? `过去 1 小时内还有 ${recentSimilar} 次相似告警，说明这不是一次孤立波动。`
        : '这次告警已经附带设备、拓扑和变化上下文，可以直接进入判断。',
      nextLabel: '下一步该做什么',
      next: primaryRecommendation(suggestion),
    }
  }

  return {
    eyebrow: 'Live incident',
    headline: 'Repeated deny bursts',
    headlineAccent: `on ${suggestion.context.service}`,
    summary: `${deviceName} crossed the rule threshold for ${suggestion.context.service}, and the system has prepared one ${scopeLabel} suggestion for review.`,
    whatHappenedLabel: 'What happened',
    whatHappened: `${ruleLabel} fired on ${friendlyDeviceName(suggestion)}. The current slice is the ${suggestion.context.service} traffic path.`,
    whyLabel: 'Why it matters',
    why: recentSimilar > 0
      ? `${recentSimilar} similar alerts were seen in the last hour, so this is no longer a one-off spike.`
      : 'Device, topology, and change context are already attached, so this incident is ready for review.',
    nextLabel: 'What to do next',
    next: primaryRecommendation(suggestion),
  }
}

function evidenceKinds(suggestion: SuggestionRecord) {
  return [
    Object.keys(suggestion.evidenceBundle.topology).length > 0 ? 'topology' : null,
    Object.keys(suggestion.evidenceBundle.device).length > 0 ? 'device' : null,
    Object.keys(suggestion.evidenceBundle.change).length > 0 ? 'change' : null,
    Object.keys(suggestion.evidenceBundle.historical).length > 0 ? 'historical' : null,
  ].filter((item): item is string => item !== null)
}

function whyThisMatters(suggestion: SuggestionRecord) {
  const attached = evidenceKinds(suggestion)
  const evidenceSummary =
    attached.length > 0 ? attached.join(' + ') : 'minimal context'
  const recentSimilar = suggestion.context.recentSimilar1h

  return `${suggestion.context.service} on ${suggestion.context.srcDeviceKey} reached ${suggestion.scope}-scope review with ${evidenceSummary} attached${recentSimilar > 0 ? ` and ${recentSimilar} similar alert(s) in the last hour` : ''}.`
}

function judgmentSummary(suggestion: SuggestionRecord) {
  return `${suggestion.priority} / ${suggestion.scope}-scope / ${suggestion.confidenceLabel}`
}

function buildGuidedStages(lifecycle: LifecyclePhase[]): GuidedStage[] {
  const [source, handoff, alert, cluster, suggestion, remediation] = lifecycle

  return [
    {
      id: 'guided-source',
      title: 'Source Signal',
      summary: 'Signal entered the platform and was handed to the raw path.',
      value: handoff.band.value,
      detail: handoff.band.detail,
      tone: 'raw',
      status:
        handoff.status === 'flowing' || source.status === 'flowing'
          ? 'flowing'
          : source.status,
      phaseIds: [...source.stageIds, ...handoff.stageIds],
      facts: [source.facts[1], handoff.facts[0]],
      stamp: handoff.band.stamp ?? source.band.stamp,
      durationMs: handoff.band.durationMs,
    },
    {
      id: 'guided-alert',
      title: 'Deterministic Alert',
      summary: alert.purpose,
      value: alert.band.value,
      detail: alert.band.detail,
      tone: 'alert',
      status: alert.status,
      phaseIds: alert.stageIds,
      facts: alert.facts,
      stamp: alert.band.stamp,
      durationMs: alert.band.durationMs,
    },
    {
      id: 'guided-cluster',
      title: 'Cluster Gate',
      summary: cluster.purpose,
      value: cluster.band.value,
      detail: cluster.band.detail,
      tone: 'alert',
      status: cluster.status,
      phaseIds: cluster.stageIds,
      facts: cluster.facts,
      stamp: cluster.band.stamp,
      durationMs: cluster.band.durationMs,
    },
    {
      id: 'guided-suggestion',
      title: 'AIOps Suggestion',
      summary: suggestion.purpose,
      value: suggestion.band.value,
      detail: suggestion.band.detail,
      tone: 'suggestion',
      status: suggestion.status,
      phaseIds: suggestion.stageIds,
      facts: suggestion.facts,
      stamp: suggestion.band.stamp,
      durationMs: suggestion.band.durationMs,
    },
    {
      id: 'guided-operator',
      title: 'Operator Action',
      summary: 'Approval and execution stay available as the next control boundary.',
      value: remediation.band.value,
      detail: remediation.band.detail,
      tone: 'neutral',
      status: remediation.status,
      phaseIds: remediation.stageIds,
      facts: remediation.facts,
      stamp: remediation.band.stamp,
      durationMs: remediation.band.durationMs,
    },
  ]
}

function guidedStageIdForPhase(phaseId: string) {
  if (phaseId === 'source-signal' || phaseId === 'edge-handoff') {
    return 'guided-source'
  }
  if (phaseId === 'deterministic-alert') {
    return 'guided-alert'
  }
  if (phaseId === 'cluster-gate') {
    return 'guided-cluster'
  }
  if (phaseId === 'suggestion-emission') {
    return 'guided-suggestion'
  }
  return 'guided-operator'
}

function localizedStageTitle(stageId: string, locale: 'en' | 'zh') {
  const mapping: Record<
    string,
    {
      en: string
      zh: string
    }
  > = {
    'guided-source': { en: 'Input Received', zh: '信号进入' },
    'guided-alert': { en: 'Rule Threshold Hit', zh: '规则触发' },
    'guided-cluster': { en: 'Pattern Check', zh: '模式检查' },
    'guided-suggestion': { en: 'Suggestion Ready', zh: '建议生成' },
    'guided-operator': { en: 'Human Review', zh: '人工处置' },
  }

  return mapping[stageId]?.[locale] ?? stageId
}

export function LiveFlowConsole({
  connectionState,
  snapshot,
  latestDelta,
  selectedSuggestion,
  onSelectSuggestion,
  transportIssue,
  locale,
  onOpenEvidence,
  onOpenRuntimeSheet,
}: LiveFlowConsoleProps) {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [expandedStageSelection, setExpandedStageSelection] = useState<{
    suggestionId: string
    stageId: string | null
  } | null>(null)
  const [isIncidentGraphExpanded, setIsIncidentGraphExpanded] = useState(false)
  const stageDetailRef = useRef<HTMLElement | null>(null)
  const pendingStageRevealRef = useRef(false)

  const queueEvents = historicalIncidentQueue(snapshot.suggestions, locale)
  const compactMetrics = snapshot.overviewMetrics.filter((metric) =>
    ['raw-freshness', 'alert-latest', 'suggestion-latest', 'closure'].includes(
      metric.id,
    ),
  )

  const activeEvent =
    queueEvents.find((event) => event.id === selectedEventId) ??
    queueEvents.find(
      (event) => event.dedupeKey === incidentKeyForSuggestion(selectedSuggestion),
    ) ??
    queueEvents[0]
  const linkedSuggestion = suggestionForEvent(
    activeEvent,
    snapshot.suggestions,
    selectedSuggestion,
  )
  const expandedStageId =
    expandedStageSelection?.suggestionId === linkedSuggestion.id
      ? expandedStageSelection.stageId
      : null
  const lifecycle = buildLifecyclePhases(snapshot, linkedSuggestion)
  const pulseKind = pulseKindForDelta(latestDelta?.kind ?? snapshot.feed[0]?.kind)
  const pulseTone = toneForDelta(latestDelta?.kind ?? snapshot.feed[0]?.kind)
  const currentPhase = currentPhaseId(latestDelta?.kind, activeEvent?.kind ?? pulseKind)
  const guidedStages = buildGuidedStages(lifecycle)
  const activeGuidedStageId = guidedStageIdForPhase(currentPhase)
  const selectedGuidedStage =
    guidedStages.find(
      (stage) => stage.id === (expandedStageId ?? activeGuidedStageId),
    ) ?? guidedStages[0]
  const selectedStagePhases = phasesForGuidedStage(lifecycle, selectedGuidedStage)
  const selectedStageGraph = buildStageProcessGraph(
    snapshot,
    selectedStagePhases,
    locale,
  )
  const incidentProcessGraph = buildStageProcessGraph(
    snapshot,
    lifecycle,
    locale,
  )
  const incidentTimeline = reconstructedTimeline(linkedSuggestion, snapshot, lifecycle)
  const activeGuidedIndex = guidedStages.findIndex(
    (stage) => stage.id === activeGuidedStageId,
  )
  const story = storyCopy(linkedSuggestion, locale)
  const relatedTimelineSteps = incidentTimeline.filter(
    (step) => step.stageId && selectedGuidedStage.phaseIds.includes(step.stageId),
  )
  const integrityIssues = lifecycleIntegrityIssues(
    snapshot,
    linkedSuggestion,
    connectionState,
    transportIssue,
  )
  const hardIntegrityIssues = integrityIssues.filter(
    (issue) => issue.severity === 'hard',
  )
  const softIntegrityIssues = integrityIssues.filter(
    (issue) => issue.severity === 'soft',
  )
  const clusterGateValue =
    linkedSuggestion.stageTelemetry?.find(
      (item) => item.stageId === 'cluster-window',
    )?.value ??
    (linkedSuggestion.context.clusterWindowSec > 0
      ? `${linkedSuggestion.context.clusterSize}/${linkedSuggestion.context.clusterWindowSec}s`
      : locale === 'zh'
        ? '未达到自然聚合门槛'
        : 'cluster gate not naturally met yet')
  const selectedProblem =
    activeEvent?.problem ?? incidentProblemSummary(linkedSuggestion, locale)
  const selectedInference =
    activeEvent?.inference ?? incidentInferenceSummary(linkedSuggestion, locale)
  const selectedRecommendation =
    activeEvent?.recommendation ?? primaryRecommendation(linkedSuggestion)
  const selectedScopeMeaning =
    activeEvent?.scopeMeaning ?? incidentScopeMeaning(linkedSuggestion, locale)
  const selectedRefreshSummary = groupedRefreshLabel(
    activeEvent?.mergedSuggestionCount ?? 1,
    locale,
  )
  const selectedWindowSummary = activeEvent
    ? `${formatMaybeTimestamp(activeEvent.firstSeenTs, 'time')} - ${formatMaybeTimestamp(activeEvent.lastSeenTs, 'time')}`
    : `${formatMaybeTimestamp(linkedSuggestion.context.clusterFirstAlertTs, 'time')} - ${formatMaybeTimestamp(linkedSuggestion.context.clusterLastAlertTs, 'time')}`

  useEffect(() => {
    if (!pendingStageRevealRef.current) {
      return
    }

    stageDetailRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    })
    pendingStageRevealRef.current = false
  }, [linkedSuggestion.id, selectedGuidedStage.id])

  const selectIncident = (event: HistoricalIncidentEvent) => {
    const nextSuggestion = suggestionForEvent(
      event,
      snapshot.suggestions,
      selectedSuggestion,
    )
    setSelectedEventId(event.id)
    setExpandedStageSelection(null)
    if (nextSuggestion.id !== selectedSuggestion.id) {
      onSelectSuggestion(nextSuggestion.id)
    }
  }

  const handleSelectGuidedStage = (stageId: string) => {
    if (selectedGuidedStage.id === stageId) {
      stageDetailRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
      return
    }

    pendingStageRevealRef.current = true
    setExpandedStageSelection({
      suggestionId: linkedSuggestion.id,
      stageId,
    })
  }

  return (
    <section className="page console-page">
      {hardIntegrityIssues.length > 0 ? (
        <section className="section integrity-warning">
          <div className="section-header">
            <div>
              <h2 className="section-title">Runtime Integrity Warning</h2>
              <span className="section-subtitle">
                This console detected live snapshot drift instead of silently pretending
                lifecycle timing is valid.
              </span>
            </div>
            <span className="section-kicker">hard warning / not cosmetic</span>
          </div>
          <ul className="integrity-list">
            {hardIntegrityIssues.map((issue) => (
              <li key={issue.id}>{issue.detail}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="section story-stage-shell">
        <div className="section-header story-stage-header">
          <div>
            <h2 className="section-title">
              {locale === 'zh' ? '事件主画面' : 'Incident Main Stage'}
            </h2>
            <span className="section-subtitle">
              {locale === 'zh'
                ? '先看发生了什么、影响谁、系统准备做什么，再按阶段继续往下钻。'
                : 'See what happened, who it affects, and what the system prepared before drilling into deeper details.'}
            </span>
          </div>
          <div className="annotation-stack">
            <span className="section-kicker">
              {locale === 'zh' ? '全屏主画面 / 结果优先' : 'full-screen stage / result first'}
            </span>
            <div className="story-stage-actions">
              <span className={`signal-chip tone-${pulseTone}`}>{pulseTone}</span>
              <button type="button" className="story-stage-action" onClick={onOpenRuntimeSheet}>
                {locale === 'zh' ? '运行概览' : 'Runtime Sheet'}
              </button>
              <button type="button" className="story-stage-action is-bright" onClick={onOpenEvidence}>
                {locale === 'zh' ? '当前建议' : 'Current Brief'}
              </button>
            </div>
          </div>
        </div>

        <div className="story-stage-canvas">
          <aside className="story-stage-darkside story-stage-rail">
            <div className="story-stage-tag">
              <span>{locale === 'zh' ? '事件队列' : 'event queue'}</span>
              <strong>
                {locale === 'zh'
                  ? `${queueEvents.length} 条历史问题事件`
                  : `${queueEvents.length} historical incidents`}
              </strong>
            </div>

            <div className="story-stage-queue-head">
              <span className="section-kicker">
                {locale === 'zh'
                  ? '触发簇 / 历史事件主控'
                  : 'trigger clusters / incident controller'}
              </span>
              <p>
                {locale === 'zh'
                  ? '这里的 1 行就是 1 个已聚合的历史事件。相同服务 / 设备 / 规则的重复 suggestion 会合并成一次事件刷新，不再把同一个问题刷成多条。'
                  : 'Each row here is one grouped historical incident. Repeated suggestions for the same rule/service/device are merged into one incident instead of flooding the queue as duplicates.'}
              </p>
            </div>

            <div className="story-stage-queue">
              {queueEvents.map((event, index) => {
                const isLead = index === 0
                const isActive = activeEvent?.id === event.id

                return (
                  <button
                    key={event.id}
                    type="button"
                    className={`event-row kind-${event.kind} ${isLead ? 'is-lead' : ''} ${isActive ? 'is-active' : ''}`}
                    onClick={() => selectIncident(event)}
                  >
                    <div className="event-row-head">
                      <span className={`signal-chip tone-${event.kind}`}>
                        {event.scope ? `${event.kind}/${event.scope}` : event.kind}
                      </span>
                      <div className="event-row-topline">
                        <span className="event-row-count">
                          {groupedRefreshLabel(event.mergedSuggestionCount, locale)}
                        </span>
                        <span
                          className="event-stamp"
                          title={timestampTooltip(event.stamp)}
                        >
                          {formatMaybeTimestamp(event.stamp, 'time')}
                        </span>
                      </div>
                    </div>
                    <strong>{event.title}</strong>
                    <p>{event.detail}</p>
                    <div className="event-row-meta">
                      <span>{event.service ?? 'n/a'}</span>
                      <span>{event.device ?? event.provider ?? 'runtime'}</span>
                      <span>{event.scopeMeaning}</span>
                    </div>
                  </button>
                )
              })}
            </div>

            <div className="story-stage-stack">
              <article className="story-stage-card">
                <span>{locale === 'zh' ? '发现的问题' : 'problem detected'}</span>
                <strong>{activeEvent?.title ?? story.whatHappened}</strong>
                <p>{selectedProblem}</p>
              </article>
              <article className="story-stage-card">
                <span>{locale === 'zh' ? '系统推断' : 'system inference'}</span>
                <strong>{selectedInference}</strong>
                <p>{linkedSuggestion.confidenceReason}</p>
              </article>
              <article className="story-stage-card">
                <span>{locale === 'zh' ? '建议动作' : 'recommended next action'}</span>
                <strong>{selectedRecommendation}</strong>
                <p>
                  {locale === 'zh'
                    ? `证据已附带 ${evidenceKinds(linkedSuggestion).join(' + ')}。`
                    : `Evidence already attached: ${evidenceKinds(linkedSuggestion).join(' + ')}.`}
                </p>
              </article>
              <article className="story-stage-card">
                <span>
                  {locale === 'zh'
                    ? `${storyScopeLabel(linkedSuggestion, locale)}是什么意思`
                    : `what ${storyScopeLabel(linkedSuggestion, locale)} means`}
                </span>
                <strong>{selectedRefreshSummary}</strong>
                <p>{selectedScopeMeaning}</p>
                <p>{selectedWindowSummary}</p>
              </article>
              {softIntegrityIssues.length > 0 ? (
                <article className="story-stage-card story-stage-card-note">
                  <span>{locale === 'zh' ? '运行提示' : 'runtime notes'}</span>
                  <strong>
                    {locale === 'zh'
                      ? '实时连接已经恢复，但当前快照仍存在跨流时间窗偏差。'
                      : 'Live transport has recovered, but the current snapshot still carries cross-stream timing skew.'}
                  </strong>
                  <ul className="story-note-list">
                    {softIntegrityIssues.map((issue) => (
                      <li key={issue.id}>{issue.detail}</li>
                    ))}
                  </ul>
                </article>
              ) : null}
            </div>

            <div className="story-stage-mini-metrics">
              {compactMetrics.map((metric) => (
                <article key={metric.id} className={`story-mini-card state-${metric.state}`}>
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                </article>
              ))}
            </div>
          </aside>

          <div className="story-stage-center">
            <div className={`story-focus-core tone-${selectedGuidedStage.tone}`}>
              <span className="story-focus-kicker">
                {locale === 'zh' ? '当前阶段' : 'current stage'}
              </span>
              <strong>{localizedStageTitle(selectedGuidedStage.id, locale)}</strong>
              <p>{selectedGuidedStage.detail}</p>
            </div>

            <div className="story-focus-rings" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>

            <div className="story-center-line story-center-line-a" aria-hidden="true" />
            <div className="story-center-line story-center-line-b" aria-hidden="true" />
            <div className="story-center-line story-center-line-c" aria-hidden="true" />
          </div>

          <article className="story-stage-brightside">
            <p className="story-hero-kicker">{story.eyebrow}</p>
            <h3 className="story-hero-headline">
              <span>{story.headline}</span>
              <span>{story.headlineAccent}</span>
            </h3>
            <p className="story-hero-summary">{story.summary}</p>

            <div className="story-badges story-badges-hero">
              <span className="signal-chip tone-suggestion">
                {linkedSuggestion.context.service}
              </span>
              <span className="signal-chip tone-neutral">
                {friendlyDeviceName(linkedSuggestion)}
              </span>
              <span className="signal-chip tone-alert">
                {linkedSuggestion.priority}
              </span>
              <span className="signal-chip tone-live">
                {storyScopeLabel(linkedSuggestion, locale)}
              </span>
            </div>

            <div className="story-insight-grid">
              <article className="story-insight-card">
                <span>{locale === 'zh' ? '系统判断' : 'system judgment'}</span>
                <strong>{judgmentSummary(linkedSuggestion)}</strong>
                <p>{linkedSuggestion.confidenceReason}</p>
              </article>

              <article className="story-insight-card">
                <span>{locale === 'zh' ? '附带上下文' : 'attached context'}</span>
                <strong>
                  {evidenceKinds(linkedSuggestion).join(' + ') || 'minimal context'}
                </strong>
                <p>{whyThisMatters(linkedSuggestion)}</p>
              </article>
            </div>

            <div className="story-hero-actions">
              <button
                type="button"
                className="story-stage-action is-bright"
                onClick={onOpenEvidence}
              >
                {locale === 'zh' ? '展开证据与建议' : 'Open evidence and actions'}
              </button>
              <button
                type="button"
                className="story-stage-action"
                onClick={onOpenRuntimeSheet}
              >
                {locale === 'zh' ? '查看运行概览' : 'Open runtime sheet'}
              </button>
            </div>
          </article>

          <div className="story-axis-guide">
            <span className="section-kicker">
              {locale === 'zh'
                ? '唯一可点击的 01-05'
                : 'the only clickable 01-05 strip'}
            </span>
            <p>
              {locale === 'zh'
                ? '点击这里的阶段卡后，页面会自动跳到下面的“阶段拆解”。下方流程图区不再重复放一排 01-05。'
                : 'Click a stage card here to jump straight into the stage breakdown below. The lower pipeline area no longer repeats another numbered 01-05 strip.'}
            </p>
          </div>

          <div className="story-axis">
            {guidedStages.map((stage, index) => {
              const isActive = stage.id === selectedGuidedStage.id
              const isReached = index <= activeGuidedIndex
              return (
                <button
                  key={stage.id}
                  type="button"
                  className={`story-axis-step state-${stage.status} tone-${stage.tone} ${isActive ? 'is-active' : ''} ${isReached ? 'is-reached' : ''}`}
                  onClick={() => handleSelectGuidedStage(stage.id)}
                >
                  <span className="story-axis-index">
                    {(index + 1).toString().padStart(2, '0')}
                  </span>
                  <strong>{localizedStageTitle(stage.id, locale)}</strong>
                  <span className="story-axis-summary">{stage.summary}</span>
                  <div className="story-axis-meta">
                    <span>{stage.value}</span>
                    <i aria-hidden="true" />
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      </section>

      <section className="section incident-pipeline-shell">
        <div className="section-header incident-pipeline-header">
          <div>
            <h2 className="section-title">
              {locale === 'zh' ? '历史事件流程图' : 'Historical Incident Pipeline'}
            </h2>
            <span className="section-subtitle">
              {locale === 'zh'
                ? '以触发簇作为历史事件中心，把所有模块、主题、关卡和人工边界还原成一张可展开的横向流程图。'
                : 'Treat the trigger cluster as one historical incident and restore the full module, topic, gate, and operator path as an expandable horizontal pipeline.'}
            </span>
          </div>
          <div className="incident-pipeline-actions">
            <span className="section-kicker">
              {locale === 'zh' ? '全屏展开 / 事件中心' : 'expand full screen / incident-centric'}
            </span>
            <button
              type="button"
              className="story-stage-action is-bright"
              onClick={() => setIsIncidentGraphExpanded(true)}
            >
              {locale === 'zh' ? '全屏展开流程图' : 'Expand Pipeline'}
            </button>
          </div>
        </div>

        <div className="incident-pipeline-layout">
          <aside className="incident-pipeline-sidebar">
            <article className="incident-pipeline-card">
              <span>{locale === 'zh' ? '当前历史事件' : 'selected incident'}</span>
              <strong>{activeEvent?.title ?? linkedSuggestion.summary}</strong>
              <p>{selectedProblem}</p>
            </article>

            <article className="incident-pipeline-card">
              <span>{locale === 'zh' ? '系统推断' : 'system inference'}</span>
              <strong>{selectedInference}</strong>
              <p>{linkedSuggestion.confidenceReason}</p>
            </article>

            <article className="incident-pipeline-card">
              <span>{locale === 'zh' ? '建议动作' : 'recommended action'}</span>
              <strong>{selectedRecommendation}</strong>
              <p>
                {locale === 'zh'
                  ? `证据 ${evidenceKinds(linkedSuggestion).join(' + ')} 已附带，可直接打开证据抽屉继续看。`
                  : `Evidence ${evidenceKinds(linkedSuggestion).join(' + ')} is already attached, so you can open the evidence drawer and continue immediately.`}
              </p>
            </article>

            <article className="incident-pipeline-card">
              <span>{locale === 'zh' ? '事件窗口与含义' : 'event window and meaning'}</span>
              <strong>{selectedWindowSummary}</strong>
              <p>{selectedScopeMeaning}</p>
              <ul className="incident-pipeline-list">
                <li>{selectedRefreshSummary}</li>
                <li>
                  {locale === 'zh'
                    ? `聚合门槛 ${clusterGateValue}`
                    : `cluster gate ${clusterGateValue}`}
                </li>
              </ul>
            </article>
          </aside>

          <div className="incident-pipeline-main">
            <section className="incident-pipeline-graph-shell">
              <div className="incident-pipeline-graph-head">
                <div>
                  <span className="section-kicker">
                    {locale === 'zh' ? '横向流程图' : 'horizontal pipeline'}
                  </span>
                  <h3>{activeEvent?.title ?? story.headline}</h3>
                </div>
                <div className="story-badges">
                  <span className="signal-chip tone-suggestion">
                    {linkedSuggestion.context.service}
                  </span>
                  <span className="signal-chip tone-neutral">
                    {friendlyDeviceName(linkedSuggestion)}
                  </span>
                  <span className="signal-chip tone-alert">
                    {clusterGateValue}
                  </span>
                  <span className="signal-chip tone-live">
                    {selectedRefreshSummary}
                  </span>
                </div>
              </div>

              <Suspense
                fallback={
                  <div className="flow-frame">
                    <div className="flow-surface chart-fallback">
                      {locale === 'zh'
                        ? '正在载入历史事件流程图...'
                        : 'loading historical incident pipeline...'}
                    </div>
                  </div>
                }
              >
                <TopologyCanvas
                  nodes={incidentProcessGraph.nodes}
                  links={incidentProcessGraph.links}
                />
              </Suspense>
            </section>

            <section ref={stageDetailRef} className="stage-process-shell incident-stage-detail-shell">
              <div className="stage-process-headline">
                <div>
                  <span className="section-kicker">
                    {locale === 'zh' ? '阶段拆解' : 'stage breakdown'}
                  </span>
                  <h4>
                    {locale === 'zh'
                      ? '点击上方事件主画面里唯一可点击的 01-05 后，这里会自动跳到对应阶段，并展开动作链与证据读取。'
                      : 'Click the only clickable 01-05 strip in the Incident Main Stage above and this area will jump to the matching stage, action chain, and evidence read.'}
                  </h4>
                </div>
                <span className={`signal-chip tone-${selectedGuidedStage.tone}`}>
                  {localizedStageTitle(selectedGuidedStage.id, locale)}
                </span>
              </div>

              {selectedStageGraph.nodes.length > 0 ? (
                <section className="stage-process-graph-shell">
                  <div className="stage-process-graph-copy">
                    <span className="section-kicker">
                      {locale === 'zh' ? '选中阶段图' : 'selected stage graph'}
                    </span>
                    <p>
                      {locale === 'zh'
                        ? '这里只展开当前选中阶段涉及到的模块、主题与控制边界。'
                        : 'This graph narrows the incident pipeline down to the modules, topics, and boundaries touched by the currently selected stage.'}
                    </p>
                  </div>
                  <Suspense
                    fallback={
                      <div className="flow-frame compact">
                        <div className="flow-surface chart-fallback">
                          {locale === 'zh'
                            ? '正在载入阶段链路图...'
                            : 'loading stage pipeline map...'}
                        </div>
                      </div>
                    }
                  >
                    <TopologyCanvas
                      compact
                      nodes={selectedStageGraph.nodes}
                      links={selectedStageGraph.links}
                    />
                  </Suspense>
                </section>
              ) : null}

              <div className="stage-process-flow">
                {selectedStagePhases.length > 0 ? (
                  selectedStagePhases.map((phase, phaseIndex) => (
                    <div key={`${selectedGuidedStage.id}-${phase.id}`} className="stage-process-segment">
                      <article className={`stage-process-card state-${phase.status}`}>
                        <span className="stage-process-index">
                          {(phaseIndex + 1).toString().padStart(2, '0')}
                        </span>
                        <strong>{phase.title}</strong>
                        <p>{phase.purpose}</p>
                        <p className="stage-process-note">{phase.band.detail}</p>
                        <div className="stage-process-meta">
                          <span>{phase.systems}</span>
                          <span>{phase.band.value}</span>
                        </div>

                        <div className="stage-process-node-strip">
                          {phase.stageIds.map((stageId) => (
                            <article
                              key={`${phase.id}-${stageId}`}
                              className="stage-node-pill"
                            >
                              <strong>{stageNodeTitle(snapshot, stageId, locale)}</strong>
                              <span>{stageNodeSubtitle(snapshot, stageId, locale)}</span>
                              <ul className="stage-node-pill-metrics">
                                {stageNodeMetrics(snapshot, stageId, locale, phase).map(
                                  (metric) => (
                                    <li key={`${phase.id}-${stageId}-${metric.label}`}>
                                      <span>{metric.label}</span>
                                      <strong>{metric.value}</strong>
                                    </li>
                                  ),
                                )}
                              </ul>
                            </article>
                          ))}
                        </div>

                        <ul className="guided-stage-facts">
                          {phase.facts.map((fact) => (
                            <li key={`${phase.id}-${fact}`}>{fact}</li>
                          ))}
                        </ul>
                      </article>
                      {phaseIndex < selectedStagePhases.length - 1 ? (
                        <div className="stage-process-connector" aria-hidden="true">
                          <span />
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <article className="story-empty-panel story-empty-panel-inline">
                    <strong>
                      {locale === 'zh'
                        ? '当前阶段还没有独立动作链'
                        : 'No dedicated action chain for this stage yet'}
                    </strong>
                    <p>
                      {locale === 'zh'
                        ? '请继续切换其他阶段或直接展开全屏流程图。'
                        : 'Switch to another stage or open the fullscreen pipeline for the broader incident path.'}
                    </p>
                  </article>
                )}
              </div>

              <div className="stage-process-detail-grid">
                <article className="focus-card">
                  <strong>{locale === 'zh' ? '本阶段关键事实' : 'stage facts'}</strong>
                  <ul className="focus-list">
                    {selectedGuidedStage.facts.map((fact) => (
                      <li key={`${selectedGuidedStage.id}-${fact}`}>{fact}</li>
                    ))}
                  </ul>
                </article>

                <article className="focus-card">
                  <strong>{locale === 'zh' ? '相关时间点' : 'related timeline steps'}</strong>
                  {relatedTimelineSteps.length > 0 ? (
                    <ul className="focus-list">
                      {relatedTimelineSteps.map((step) => (
                        <li key={`${selectedGuidedStage.id}-${step.id}`}>
                          {formatMaybeTimestamp(step.stamp, 'time')} · {step.title}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <ul className="focus-list">
                      <li>
                        {locale === 'zh'
                          ? '当前阶段没有独立时间点，使用上方动作链描述。'
                          : 'No standalone timeline record for this stage; use the action chain above.'}
                      </li>
                    </ul>
                  )}
                </article>

                <article className="focus-card">
                  <strong>{locale === 'zh' ? '本阶段读取 / 输出' : 'read / output'}</strong>
                  <ul className="focus-list">
                    {selectedStagePhases.map((phase) => (
                      <li key={`${selectedGuidedStage.id}-${phase.id}-systems`}>
                        {phase.title}: {phase.systems}
                      </li>
                    ))}
                  </ul>
                </article>
              </div>
            </section>
          </div>
        </div>
      </section>

      {isIncidentGraphExpanded ? (
        <div className="pipeline-overlay">
          <button
            type="button"
            className="pipeline-overlay-backdrop"
            aria-label={locale === 'zh' ? '关闭流程图' : 'Close pipeline'}
            onClick={() => setIsIncidentGraphExpanded(false)}
          />
          <div className="pipeline-overlay-shell">
            <section className="section pipeline-overlay-panel">
              <div className="section-header">
                <div>
                  <h2 className="section-title">
                    {locale === 'zh' ? '历史事件全屏流程图' : 'Fullscreen Incident Pipeline'}
                  </h2>
                  <span className="section-subtitle">
                    {locale === 'zh'
                      ? '当前事件的流程、证据和阶段链路在这里展开到全屏。'
                      : 'Expand the selected incident graph, evidence path, and stage chain into a full-screen workspace.'}
                  </span>
                </div>
                <button
                  type="button"
                  className="story-stage-action"
                  onClick={() => setIsIncidentGraphExpanded(false)}
                >
                  {locale === 'zh' ? '关闭' : 'Close'}
                </button>
              </div>

              <div className="pipeline-overlay-grid">
                <div className="pipeline-overlay-graph">
                  <Suspense
                    fallback={
                      <div className="flow-frame">
                        <div className="flow-surface chart-fallback">
                          {locale === 'zh' ? '正在载入全屏流程图...' : 'loading fullscreen pipeline...'}
                        </div>
                      </div>
                    }
                  >
                    <TopologyCanvas
                      nodes={incidentProcessGraph.nodes}
                      links={incidentProcessGraph.links}
                    />
                  </Suspense>
                </div>

                <aside className="pipeline-overlay-sidebar">
                  <article className="focus-card">
                    <strong>{locale === 'zh' ? '事件摘要' : 'incident summary'}</strong>
                    <ul className="focus-list">
                      <li>{activeEvent?.title ?? linkedSuggestion.summary}</li>
                      <li>{story.summary}</li>
                      <li>{primaryRecommendation(linkedSuggestion)}</li>
                    </ul>
                  </article>

                  <article className="focus-card">
                    <strong>{locale === 'zh' ? '完整时间线' : 'full timeline'}</strong>
                    <ul className="focus-list">
                      {incidentTimeline.map((step) => (
                        <li key={`${linkedSuggestion.id}-overlay-${step.id}`}>
                          {formatMaybeTimestamp(step.stamp, 'time')} · {step.title}
                        </li>
                      ))}
                    </ul>
                  </article>
                </aside>
              </div>
            </section>
          </div>
        </div>
      ) : null}

    </section>
  )
}
