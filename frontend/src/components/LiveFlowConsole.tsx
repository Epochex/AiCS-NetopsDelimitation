import { lazy, Suspense, useState } from 'react'
import type { RuntimeConnectionState } from '../hooks/useRuntimeSnapshot'
import type {
  FeedEvent,
  RuntimeSnapshot,
  RuntimeStreamDelta,
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

interface LiveFlowConsoleProps {
  connectionState: RuntimeConnectionState
  snapshot: RuntimeSnapshot
  latestDelta: RuntimeStreamDelta | null
  selectedSuggestion: SuggestionRecord
  onSelectSuggestion: (suggestionId: string) => void
  transportIssue?: string | null
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

const RuntimeVisualPanels = lazy(() =>
  import('./RuntimeVisualPanels').then((module) => ({
    default: module.RuntimeVisualPanels,
  })),
)

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

function eventPath(event: FeedEvent, linkedSuggestion: SuggestionRecord) {
  if (event.kind === 'raw') {
    return ['fortigate', 'ingest', 'forwarder', 'raw-topic']
  }

  if (event.kind === 'alert') {
    return ['raw-topic', 'correlator', 'alerts-topic', 'cluster-window']
  }

  return linkedSuggestion.scope === 'cluster'
    ? [
        'alerts-topic',
        'cluster-window',
        'aiops-agent',
        'suggestions-topic',
        'remediation',
      ]
    : ['alerts-topic', 'aiops-agent', 'suggestions-topic', 'remediation']
}

function eventSummary(event: FeedEvent, linkedSuggestion: SuggestionRecord) {
  if (event.kind === 'raw') {
    return {
      heading: 'raw ingest sample',
      detail: `service=${event.service ?? 'unknown'} device=${event.device ?? 'unknown'} entered the live edge path.`,
      annotations: [
        `path=${eventPath(event, linkedSuggestion).join(' -> ')}`,
        'status=awaiting deterministic correlation',
      ],
    }
  }

  if (event.kind === 'alert') {
    return {
      heading: 'deterministic alert fired',
      detail: event.detail,
      annotations: [
        `path=${eventPath(event, linkedSuggestion).join(' -> ')}`,
        `evidence=${event.evidence ?? 'none'}`,
      ],
    }
  }

  return {
    heading: `${event.scope ?? 'alert'}-scope suggestion emitted`,
    detail: event.detail,
    annotations: [
      `provider=${event.provider ?? linkedSuggestion.context.provider}`,
      `actions=${event.actionCount ?? linkedSuggestion.recommendedActions.length}`,
      `hypotheses=${event.hypothesisCount ?? linkedSuggestion.hypotheses.length}`,
    ],
  }
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
    })
  }

  const latestAlert = parseTimestamp(snapshot.runtime.latestAlertTs)
  const latestSuggestion = parseTimestamp(snapshot.runtime.latestSuggestionTs)
  if (latestAlert && latestSuggestion) {
    const skewMs = latestSuggestion.getTime() - latestAlert.getTime()
    if (skewMs > 15 * 60_000) {
      issues.push({
        id: 'stream-skew',
        detail: `Suggestion stream leads alert stream by ${formatDurationMs(skewMs)}.`,
      })
    }
  }

  const volume = currentDayVolume(snapshot)
  if (volume && volume.alerts === 0 && volume.suggestions > 0) {
    issues.push({
      id: 'volume-skew',
      detail: `Current-day volume is skewed: ${volume.alerts} alerts / ${volume.suggestions} suggestions.`,
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

export function LiveFlowConsole({
  connectionState,
  snapshot,
  latestDelta,
  selectedSuggestion,
  onSelectSuggestion,
  transportIssue,
}: LiveFlowConsoleProps) {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [expandedStageId, setExpandedStageId] = useState<string | null>(null)

  const queueEvents = snapshot.feed.slice(0, 10)
  const compactMetrics = snapshot.overviewMetrics.filter((metric) =>
    ['raw-freshness', 'backlog', 'current-day-volume', 'closure'].includes(
      metric.id,
    ),
  )

  const activeEvent =
    queueEvents.find((event) => event.id === selectedEventId) ?? queueEvents[0]
  const linkedSuggestion = suggestionForEvent(
    activeEvent,
    snapshot.suggestions,
    selectedSuggestion,
  )
  const lifecycle = buildLifecyclePhases(snapshot, linkedSuggestion)
  const pulseKind = pulseKindForDelta(latestDelta?.kind ?? snapshot.feed[0]?.kind)
  const pulseTone = toneForDelta(latestDelta?.kind ?? snapshot.feed[0]?.kind)
  const currentPhase = currentPhaseId(latestDelta?.kind, activeEvent?.kind ?? pulseKind)
  const activeStageIndex = lifecycle.findIndex((phase) => phase.id === currentPhase)
  const activeSummary = activeEvent
    ? eventSummary(activeEvent, linkedSuggestion)
    : null
  const guidedStages = buildGuidedStages(lifecycle)
  const activeGuidedStageId = guidedStageIdForPhase(currentPhase)
  const selectedGuidedStage =
    guidedStages.find(
      (stage) => stage.id === (expandedStageId ?? activeGuidedStageId),
    ) ?? guidedStages[0]
  const activeGuidedIndex = guidedStages.findIndex(
    (stage) => stage.id === activeGuidedStageId,
  )
  const relatedTimelineSteps = (linkedSuggestion.timeline ?? snapshot.timeline).filter(
    (step) => step.stageId && selectedGuidedStage.phaseIds.includes(step.stageId),
  )
  const integrityIssues = lifecycleIntegrityIssues(
    snapshot,
    linkedSuggestion,
    connectionState,
    transportIssue,
  )
  return (
    <section className="page console-page">
      {integrityIssues.length > 0 ? (
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
            {integrityIssues.map((issue) => (
              <li key={issue.id}>{issue.detail}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="section incident-overview">
        <div className="section-header">
          <div>
            <h2 className="section-title">Guided Incident Overview</h2>
            <span className="section-subtitle">
              Outcome first for the current active slice. Open tactical detail only when
              you need it.
            </span>
          </div>
          <div className="annotation-stack">
            <span className="section-kicker">first-entry page / result first</span>
            <span className={`signal-chip tone-${pulseTone}`}>{pulseTone}</span>
          </div>
        </div>

        <div className="incident-overview-grid">
          <article className="incident-hero-card">
            <p className="story-marker">current active incident</p>
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

            <div className="incident-action-stack">
              <article className="incident-action-card">
                <span className="section-kicker">recommended action</span>
                <strong>{primaryRecommendation(linkedSuggestion)}</strong>
                <p>
                  {linkedSuggestion.recommendedActions.length > 1
                    ? `+${linkedSuggestion.recommendedActions.length - 1} more operator action(s) are available in the evidence drawer.`
                    : 'Open the evidence drawer for field-level inspection.'}
                </p>
              </article>

              <article className="incident-action-card">
                <span className="section-kicker">why this result matters</span>
                <strong>{judgmentSummary(linkedSuggestion)}</strong>
                <p>{whyThisMatters(linkedSuggestion)}</p>
              </article>
            </div>
          </article>

          <div className="incident-judgement-stack">
            <article className="incident-info-card">
              <span className="section-kicker">system judgment</span>
              <strong>{judgmentSummary(linkedSuggestion)}</strong>
              <p>Severity, scope, and confidence for the currently selected slice.</p>
            </article>

            <article className="incident-info-card">
              <span className="section-kicker">current stage</span>
              <strong>{selectedGuidedStage.title}</strong>
              <p>{selectedGuidedStage.summary}</p>
            </article>

            <article className="incident-info-card">
              <span className="section-kicker">attached evidence</span>
              <strong>
                {evidenceKinds(linkedSuggestion).join(' + ') || 'minimal context'}
              </strong>
              <p>Evidence stays available, but field-level dumps are no longer first-screen.</p>
            </article>
          </div>
        </div>

        <div className="micro-metric-rail">
          {compactMetrics.map((metric) => (
            <div key={metric.id} className={`micro-metric state-${metric.state}`}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="section guided-stage-section">
        <div className="section-header">
          <div>
            <h2 className="section-title">Process To Result</h2>
            <span className="section-subtitle">
              Follow one active incident from source signal to operator boundary.
              Click a stage to expand its meaning.
            </span>
          </div>
          <span className="section-kicker">progressive disclosure / active slice</span>
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
                <strong>{stage.title}</strong>
                <span className="guided-stage-summary">{stage.summary}</span>
                <div className="guided-stage-meta">
                  <span className={`signal-chip tone-${stage.tone}`}>{stage.value}</span>
                  <span className="guided-stage-status">
                    {stage.status === 'flowing'
                      ? 'active'
                      : stage.status === 'watch'
                        ? 'watch'
                        : stage.status === 'planned'
                          ? 'pending'
                          : 'ready'}
                  </span>
                </div>
              </button>
            )
          })}
        </div>

        <div className="guided-stage-detail">
          <div className="guided-stage-detail-head">
            <div>
              <span className="section-kicker">selected stage</span>
              <h3>{selectedGuidedStage.title}</h3>
              <p>{selectedGuidedStage.summary}</p>
            </div>
            <span className={`signal-chip tone-${selectedGuidedStage.tone}`}>
              {selectedGuidedStage.value}
            </span>
          </div>

          <p className="guided-stage-detail-copy">{selectedGuidedStage.detail}</p>

          <div className="guided-stage-note-grid">
            <article className="guided-note-card">
              <span>time</span>
              <strong title={timestampTooltip(selectedGuidedStage.stamp)}>
                {formatMaybeTimestamp(selectedGuidedStage.stamp, 'time')}
              </strong>
            </article>

            <article className="guided-note-card">
              <span>transition</span>
              <strong>{formatDurationMs(selectedGuidedStage.durationMs)}</strong>
            </article>

            <article className="guided-note-card">
              <span>operator takeaway</span>
              <strong>{primaryRecommendation(linkedSuggestion)}</strong>
            </article>
          </div>

          <ul className="guided-stage-facts">
            {selectedGuidedStage.facts.map((fact) => (
              <li key={`${selectedGuidedStage.id}-${fact}`}>{fact}</li>
            ))}
          </ul>

          {relatedTimelineSteps.length > 0 ? (
            <ol className="guided-stage-timeline">
              {relatedTimelineSteps.map((step) => (
                <li key={`${selectedGuidedStage.id}-${step.id}`}>
                  <span title={timestampTooltip(step.stamp)}>
                    {formatMaybeTimestamp(step.stamp, 'time')}
                  </span>
                  <div>
                    <strong>{step.title}</strong>
                    <p>{step.detail}</p>
                  </div>
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      </section>

      <details className="section tactical-disclosure">
        <summary>
          <div>
            <h2 className="section-title">Incident Story And Supporting Visuals</h2>
            <span className="section-subtitle">
              Expand to inspect charts and the full story timeline for the active slice.
            </span>
          </div>
          <span className="section-kicker">expand supporting evidence</span>
        </summary>

        <div className="tactical-detail-stack">
          <Suspense
            fallback={
              <section className="section chart-fallback">
                loading meaningful runtime visuals...
              </section>
            }
          >
            <RuntimeVisualPanels
              snapshot={snapshot}
              selectedSuggestion={linkedSuggestion}
            />
          </Suspense>

          <section key={linkedSuggestion.id} className="section story-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">Selected Runtime Story</h2>
                <span className="section-subtitle">
                  Timeline-driven explanation for the active suggestion slice.
                </span>
              </div>
              <span className="section-kicker">{linkedSuggestion.scope}-scope</span>
            </div>

            <div className="story-summary">
              <div>
                <p className="story-marker">active slice</p>
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
            </div>

            <ol className="timeline-list">
              {(linkedSuggestion.timeline ?? snapshot.timeline).map((step, index) => (
                <li
                  key={`${linkedSuggestion.id}-${step.id}`}
                  className={`timeline-item ${index <= activeStageIndex ? 'is-active' : ''}`}
                  style={{ animationDelay: `${index * 90}ms` }}
                >
                  <span className="timeline-stamp" title={timestampTooltip(step.stamp)}>
                    {formatMaybeTimestamp(step.stamp)}
                  </span>
                  <div className="timeline-body">
                    <h3>{step.title}</h3>
                    <p>{step.detail}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </details>

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
              <span className="section-kicker">600s / min=3</span>
            </div>
            <ul className="cluster-list">
              {snapshot.clusterWatch.map((item) => (
                <li key={item.key} className="cluster-item">
                  <div className="cluster-head">
                    <div>
                      <strong>{item.service}</strong>
                      <span>{item.device}</span>
                    </div>
                    <span className="cluster-ratio">
                      {item.progress}/{item.target}
                    </span>
                  </div>
                  <div className="cluster-progress" aria-hidden="true">
                    <span
                      style={{
                        width: `${Math.min(100, (item.progress / item.target) * 100)}%`,
                      }}
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

          <section className="section event-stack-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">Event Queue</h2>
                <span className="section-subtitle">
                  Click one event to promote it into the active explanation path.
                </span>
              </div>
              <span className="section-kicker">newest first / click to inspect</span>
            </div>

            <div className="event-stack">
              {queueEvents.map((event, index) => {
                const isLead = latestDelta?.feedIds.includes(event.id) ?? index === 0
                const isActive = activeEvent?.id === event.id

                return (
                  <button
                    key={event.id}
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
                      <span
                        className="event-stamp"
                        title={timestampTooltip(event.stamp)}
                      >
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

          <section className="section event-focus-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">Event Focus</h2>
                <span className="section-subtitle">
                  Drill into the active event instead of reading every panel at once.
                </span>
              </div>
              <span className="section-kicker">
                {activeEvent?.kind ?? 'waiting'}
              </span>
            </div>

            {activeEvent && activeSummary ? (
              <div key={activeEvent.id} className="event-focus-body">
                <div className="event-focus-summary">
                  <div className="event-focus-topline">
                    <span className={`signal-chip tone-${activeEvent.kind}`}>
                      {activeEvent.scope
                        ? `${activeEvent.kind}/${activeEvent.scope}`
                        : activeEvent.kind}
                    </span>
                    <span
                      className="event-focus-stamp"
                      title={timestampTooltip(activeEvent.stamp)}
                    >
                      {formatMaybeTimestamp(activeEvent.stamp, 'time')}
                    </span>
                  </div>
                  <h3>{activeEvent.title}</h3>
                  <p>{activeSummary.detail}</p>
                </div>

                <div className="event-focus-grid">
                  <article className="focus-card">
                    <strong>{activeSummary.heading}</strong>
                    <ul className="focus-list">
                      {activeSummary.annotations.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </article>

                  <article className="focus-card">
                    <strong>linked analysis</strong>
                    <ul className="focus-list">
                      <li>service={linkedSuggestion.context.service}</li>
                      <li>device={linkedSuggestion.context.srcDeviceKey}</li>
                      <li>confidence={linkedSuggestion.confidenceLabel}</li>
                      <li>actions={linkedSuggestion.recommendedActions.length}</li>
                    </ul>
                  </article>
                </div>

                <div className="event-path">
                  {eventPath(activeEvent, linkedSuggestion).map((step, index) => (
                    <div key={`${activeEvent.id}-${step}`} className="event-path-step">
                      <span>{step}</span>
                      {index < eventPath(activeEvent, linkedSuggestion).length - 1 ? (
                        <i aria-hidden="true" />
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        </div>
      </details>
    </section>
  )
}
