import { useState } from 'react'
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
import { pick, type UiLocale } from '../i18n'
import { RuntimeVisualPanels } from './RuntimeVisualPanels'
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
  locale: UiLocale
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
  locale: UiLocale,
  transportIssue?: string | null,
): LifecycleIntegrityIssue[] {
  const t = (en: string, zh: string) => pick(locale, en, zh)
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
      detail: t(
        'Live snapshot for the active suggestion is missing timeline/stageTelemetry, so lifecycle timing cannot be trusted.',
        '当前活动建议对应的 live snapshot 缺少 timeline/stageTelemetry，所以生命周期计时不可信。',
      ),
    })
  }

  const latestAlert = parseTimestamp(snapshot.runtime.latestAlertTs)
  const latestSuggestion = parseTimestamp(snapshot.runtime.latestSuggestionTs)
  if (latestAlert && latestSuggestion) {
    const skewMs = latestSuggestion.getTime() - latestAlert.getTime()
    if (skewMs > 15 * 60_000) {
      issues.push({
        id: 'stream-skew',
        detail: t(
          `Suggestion stream leads alert stream by ${formatDurationMs(skewMs)}.`,
          `建议流领先告警流 ${formatDurationMs(skewMs)}。`,
        ),
      })
    }
  }

  const volume = currentDayVolume(snapshot)
  if (volume && volume.alerts === 0 && volume.suggestions > 0) {
    issues.push({
      id: 'volume-skew',
      detail: t(
        `Current-day volume is skewed: ${volume.alerts} alerts / ${volume.suggestions} suggestions.`,
        `当天流量失衡：${volume.alerts} 条告警 / ${volume.suggestions} 条建议。`,
      ),
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

function whyThisMatters(suggestion: SuggestionRecord, locale: UiLocale) {
  const attached = evidenceKinds(suggestion)
  const evidenceSummary =
    attached.length > 0 ? attached.join(' + ') : 'minimal context'
  const recentSimilar = suggestion.context.recentSimilar1h

  if (locale === 'zh') {
    return `${suggestion.context.srcDeviceKey} 上的 ${suggestion.context.service} 已进入 ${suggestion.scope}-scope 研判，并附带 ${evidenceSummary} 上下文${recentSimilar > 0 ? `，最近 1 小时内有 ${recentSimilar} 条相似告警` : ''}。`
  }

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
  const attachedKinds = evidenceKinds(linkedSuggestion)
  const t = (en: string, zh: string) => pick(locale, en, zh)
  const stageTitle = (id: string, fallback: string) => {
    switch (id) {
      case 'guided-source':
        return t('Source Signal', '源信号')
      case 'guided-alert':
        return t('Deterministic Alert', '确定性告警')
      case 'guided-cluster':
        return t('Cluster Gate', '聚类门控')
      case 'guided-suggestion':
        return t('AIOps Suggestion', 'AIOps 建议')
      case 'guided-operator':
        return t('Operator Action', '操作动作')
      default:
        return fallback
    }
  }
  const relatedTimelineSteps = (linkedSuggestion.timeline ?? snapshot.timeline).filter(
    (step) => step.stageId && selectedGuidedStage.phaseIds.includes(step.stageId),
  )
  const integrityIssues = lifecycleIntegrityIssues(
    snapshot,
    linkedSuggestion,
    connectionState,
    locale,
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
              <h2 className="section-title">
                {t('Runtime Integrity Warning', '运行时完整性警告')}
              </h2>
              <span className="section-subtitle">
                {t(
                  'This console detected live snapshot drift instead of silently pretending lifecycle timing is valid.',
                  '控制台检测到了 live snapshot 漂移，而不是继续假装生命周期计时仍然有效。',
                )}
              </span>
            </div>
            <span className="section-kicker">
              {t('hard warning / not cosmetic', '硬警告 / 非装饰性提示')}
            </span>
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
              {t('Guided Incident Overview', '引导式事件总览')}
            </h2>
            <span className="section-subtitle">
              {t(
                'Outcome first for the current active slice. Open tactical detail only when you need it.',
                '先给出当前事件切片的结论，再按需展开战术细节。',
              )}
            </span>
          </div>
          <div className="annotation-stack">
            <span className="section-kicker">
              {t('first-entry page / result first', '入口首页 / 结果优先')}
            </span>
            <span className={`signal-chip tone-${pulseTone}`}>{pulseTone}</span>
          </div>
        </div>

        <div className="incident-overview-grid">
          <article className="incident-hero-card">
            <div className="incident-hero-layout">
              <div className="incident-hero-copy">
                <p className="story-marker">{t('current active incident', '当前活动事件')}</p>
                <h3 className="incident-title">{linkedSuggestion.summary}</h3>
                <p className="incident-copy">
                  {activeSummary?.detail ?? linkedSuggestion.confidenceReason}
                </p>

                <div className="story-badges">
                  <span className="signal-chip tone-suggestion">
                    {linkedSuggestion.context.service}
                  </span>
                  <span className="signal-chip tone-neutral">
                    {linkedSuggestion.context.srcDeviceKey}
                  </span>
                  <span className="signal-chip tone-alert">
                    {linkedSuggestion.priority}
                  </span>
                  <span className="signal-chip tone-live">
                    {linkedSuggestion.context.provider}
                  </span>
                </div>
              </div>

              <div className="incident-scene" aria-hidden="true">
                <div className="incident-scene-grid" />
                <div className="scene-core">
                  <span className="scene-core-kicker">
                    {t('live verdict', '实时判定')}
                  </span>
                  <strong>{stageTitle(selectedGuidedStage.id, selectedGuidedStage.title)}</strong>
                  <p>{judgmentSummary(linkedSuggestion)}</p>
                </div>

                <div className="scene-orbit-field">
                  {(attachedKinds.length > 0 ? attachedKinds : ['minimal']).map(
                    (kind, index) => (
                      <span
                        key={`${kind}-${index}`}
                        className={`scene-orbit kind-${kind}`}
                        style={{ animationDelay: `${index * 220}ms` }}
                      >
                        {kind}
                      </span>
                    ),
                  )}
                </div>

                <div className="scene-path">
                  {guidedStages.map((stage, index) => {
                    const isReached = index <= activeGuidedIndex
                    const isCurrent = stage.id === activeGuidedStageId
                    return (
                      <div
                        key={`scene-${stage.id}`}
                        className={`scene-stage ${isReached ? 'is-reached' : ''} ${isCurrent ? 'is-current' : ''} tone-${stage.tone}`}
                      >
                        <div className="scene-node">
                          <i />
                        </div>
                        <span>{stageTitle(stage.id, stage.title)}</span>
                        <small>{stage.value}</small>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            <div className="incident-action-stack">
              <article className="incident-action-card">
                <span className="section-kicker">{t('recommended action', '推荐动作')}</span>
                <strong>{primaryRecommendation(linkedSuggestion)}</strong>
                <p>
                  {linkedSuggestion.recommendedActions.length > 1
                    ? t(
                        `+${linkedSuggestion.recommendedActions.length - 1} more operator action(s) are available in the evidence drawer.`,
                        `证据抽屉里还有 ${linkedSuggestion.recommendedActions.length - 1} 条额外操作建议。`,
                      )
                    : t(
                        'Open the evidence drawer for field-level inspection.',
                        '打开证据抽屉查看字段级细节。',
                      )}
                </p>
              </article>

              <article className="incident-action-card">
                <span className="section-kicker">
                  {t('why this result matters', '为什么这个结果重要')}
                </span>
                <strong>{judgmentSummary(linkedSuggestion)}</strong>
                <p>{whyThisMatters(linkedSuggestion, locale)}</p>
              </article>
            </div>
          </article>

          <div className="incident-judgement-stack">
            <article className="incident-info-card">
              <span className="section-kicker">{t('system judgment', '系统判断')}</span>
              <strong>{judgmentSummary(linkedSuggestion)}</strong>
              <p>
                {t(
                  'Severity, scope, and confidence for the currently selected slice.',
                  '展示当前事件切片的严重度、范围和置信度。',
                )}
              </p>
            </article>

            <article className="incident-info-card">
              <span className="section-kicker">{t('current stage', '当前阶段')}</span>
              <strong>{stageTitle(selectedGuidedStage.id, selectedGuidedStage.title)}</strong>
              <p>{selectedGuidedStage.summary}</p>
            </article>

            <article className="incident-info-card">
              <span className="section-kicker">{t('attached evidence', '附带证据')}</span>
              <strong>
                {attachedKinds.join(' + ') || 'minimal context'}
              </strong>
              <p>
                {t(
                  'Evidence stays available, but field-level dumps are no longer first-screen.',
                  '证据依然保留，但字段级内容不再占据首屏。',
                )}
              </p>
            </article>
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
            <h2 className="section-title">{t('Process To Result', '过程到结果')}</h2>
            <span className="section-subtitle">
              {t(
                'Follow one active incident from source signal to operator boundary. Click a stage to expand its meaning.',
                '沿着一条活动事件，从源信号一直看到操作边界。点击阶段即可展开语义。',
              )}
            </span>
          </div>
          <span className="section-kicker">
            {t('progressive disclosure / active slice', '渐进展开 / 活动切片')}
          </span>
        </div>

        <div className="guided-stage-strip">
          {guidedStages.map((stage, index) => {
            const isActive = stage.id === selectedGuidedStage.id
            const isReached = index <= activeGuidedIndex
            return (
              <button
                key={stage.id}
                type="button"
                className={`guided-stage-step state-${stage.status} tone-${stage.tone} ${isActive ? 'is-active' : ''} ${isReached ? 'is-reached' : ''}`}
                onClick={() => setExpandedStageId(stage.id)}
              >
                <span className="guided-stage-index">
                  {(index + 1).toString().padStart(2, '0')}
                </span>
                <strong>{stageTitle(stage.id, stage.title)}</strong>
                <span className="guided-stage-summary">{stage.summary}</span>
                <div className="guided-stage-meta">
                  <span className={`signal-chip tone-${stage.tone}`}>{stage.value}</span>
                  <span className="guided-stage-status">
                    {stage.status === 'flowing'
                      ? t('active', '激活')
                      : stage.status === 'watch'
                        ? t('watch', '观察')
                        : stage.status === 'planned'
                          ? t('pending', '待定')
                          : t('ready', '就绪')}
                  </span>
                </div>
              </button>
            )
          })}
        </div>

        <div className="guided-stage-detail">
          <div className="guided-stage-detail-head">
            <div>
              <span className="section-kicker">{t('selected stage', '当前阶段')}</span>
              <h3>{stageTitle(selectedGuidedStage.id, selectedGuidedStage.title)}</h3>
              <p>{selectedGuidedStage.summary}</p>
            </div>
            <span className={`signal-chip tone-${selectedGuidedStage.tone}`}>
              {selectedGuidedStage.value}
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

          <p className="guided-stage-detail-copy">{selectedGuidedStage.detail}</p>

          <div className="guided-stage-note-grid">
            <article className="guided-note-card">
              <span>{t('time', '时间')}</span>
              <strong title={timestampTooltip(selectedGuidedStage.stamp)}>
                {formatMaybeTimestamp(selectedGuidedStage.stamp, 'time')}
              </strong>
            </article>

            <article className="guided-note-card">
              <span>{t('transition', '转场耗时')}</span>
              <strong>{formatDurationMs(selectedGuidedStage.durationMs)}</strong>
            </article>

            <article className="guided-note-card">
              <span>{t('operator takeaway', '操作提示')}</span>
              <strong>{primaryRecommendation(linkedSuggestion)}</strong>
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
              ))}
            </ol>
          ) : null}
        </div>
      </section>

      <section className="section story-theater">
        <div className="section-header">
          <div>
            <h2 className="section-title">
              {t('Incident Story And Supporting Visuals', '事件故事与支撑可视化')}
            </h2>
            <span className="section-subtitle">
              {t(
                'This is now a full-stage data theater: charts, queue, and story timeline all stay visible and linked.',
                '这里不再是小折叠，而是完整的数据舞台：图表、队列、故事时间线全部联动可见。',
              )}
            </span>
          </div>
          <span className="section-kicker">
            {t('global stage / data theater', '全局舞台 / 数据剧场')}
          </span>
        </div>

        <div className="tactical-detail-stack story-theater-stack">
          <RuntimeVisualPanels
            snapshot={snapshot}
            selectedSuggestion={linkedSuggestion}
            locale={locale}
          />

          <div className="story-theater-grid">
            <section className="section story-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">
                  {t('Selected Runtime Story', '当前运行时故事')}
                </h2>
                <span className="section-subtitle">
                  {t(
                    'Timeline-driven explanation for the active suggestion slice.',
                    '围绕当前建议切片的时间线驱动解释。',
                  )}
                </span>
              </div>
              <span className="section-kicker">{linkedSuggestion.scope}-scope</span>
            </div>

            <div className="story-summary">
              <div>
                <p className="story-marker">{t('active slice', '当前切片')}</p>
                <h3>{linkedSuggestion.summary}</h3>
              </div>
              <div className="story-badges">
                <span className="signal-chip tone-suggestion">
                  {linkedSuggestion.context.service}
                </span>
                <span className="signal-chip tone-neutral">
                  {linkedSuggestion.context.srcDeviceKey}
                </span>
                <span className="signal-chip tone-alert">
                  {linkedSuggestion.priority}
                </span>
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
                </li>
              ))}
            </ol>
            </section>

            <section className="section event-stack-panel story-queue-panel">
              <div className="section-header">
                <div>
                  <h2 className="section-title">{t('Event Queue', '事件队列')}</h2>
                  <span className="section-subtitle">
                    {t(
                      'Use the queue as a live interaction rail. Click an event to rewrite the active story.',
                      '把队列当作交互轨道来用。点击任一事件，首页故事线会立刻重写。',
                    )}
                  </span>
                </div>
                <span className="section-kicker">
                  {t('newest first / linked focus', '最新优先 / 联动聚焦')}
                </span>
              </div>

              <div className="event-stack">
                {queueEvents.map((event, index) => {
                  const isLead = latestDelta?.feedIds.includes(event.id) ?? index === 0
                  const isActive = activeEvent?.id === event.id

                  return (
                    <button
                      key={`story-${event.id}`}
                      type="button"
                      className={`event-row kind-${event.kind} ${isLead ? 'is-lead' : ''} ${isActive ? 'is-active' : ''}`}
                      onClick={() => {
                        setSelectedEventId(event.id)
                        const suggestion = suggestionForEvent(
                          event,
                          snapshot.suggestions,
                          selectedSuggestion,
                        )
                        if (suggestion.id !== selectedSuggestion.id) {
                          onSelectSuggestion(suggestion.id)
                        }
                      }}
                    >
                      <div className="event-row-head">
                        <span className={`signal-chip tone-${event.kind}`}>
                          {event.scope ? `${event.kind}/${event.scope}` : event.kind}
                        </span>
                        <span className="event-stamp" title={timestampTooltip(event.stamp)}>
                          {formatMaybeTimestamp(event.stamp, 'time')}
                        </span>
                      </div>
                      <strong>{event.title}</strong>
                      <p>{event.detail}</p>
                      <div className="event-row-meta">
                        <span>{event.service ?? 'n/a'}</span>
                        <span>{event.device ?? event.provider ?? 'runtime'}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </section>
          </div>
        </div>
      </section>

      <details className="section tactical-disclosure">
        <summary>
          <div>
            <h2 className="section-title">Tactical Console</h2>
            <span className="section-subtitle">
              Expand for cluster watch, event queue, and runtime inspection panels.
            </span>
          </div>
          <span className="section-kicker">expert detail / click to inspect</span>
        </summary>

        <div className="console-core">
          <section className="section cluster-rail">
            <div className="section-header">
              <div>
                <h2 className="section-title">Cluster Watch</h2>
                <span className="section-subtitle">
                  Which repeated alert paths are closest to becoming cluster-scope suggestions.
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
                  </div>
                  <p>
                    {item.progress >= item.target
                      ? `Reached cluster threshold inside the last ${item.windowSec}s.`
                      : `${item.progress} matching alert(s) in the last ${item.windowSec}s; ${item.target - item.progress} more needed.`}
                  </p>
                </li>
              ))}
            </ul>
          </section>

          <section className="section event-focus-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">{t('Event Focus', '事件聚焦')}</h2>
                <span className="section-subtitle">
                  {t(
                    'Drill into the active event instead of reading every panel at once.',
                    '不要一次读完所有面板，直接聚焦当前事件。',
                  )}
                </span>
              </div>
              <span className="section-kicker">
                {activeEvent?.kind ?? t('waiting', '等待中')}
              </span>
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
                    <strong>{t('linked analysis', '联动分析')}</strong>
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
