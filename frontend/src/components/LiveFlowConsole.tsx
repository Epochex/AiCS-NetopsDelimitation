import { useMemo, useState } from 'react'
import type {
  FeedEvent,
  RuntimeSnapshot,
  StageNode,
  StrategyControl,
  SuggestionRecord,
} from '../types'
import { formatMaybeTimestamp, timestampTooltip } from '../utils/time'

interface LiveFlowConsoleProps {
  snapshot: RuntimeSnapshot
  selectedSuggestion: SuggestionRecord
  onSelectSuggestion: (suggestionId: string) => void
}

interface LifecycleBlock {
  id: string
  title: string
  subtitle: string
  status: StageNode['status']
  metrics: Array<{ label: string; value: string }>
}

function controlValue(controls: StrategyControl[], label: string) {
  return controls.find((control) => control.label === label)?.currentValue ?? 'n/a'
}

function buildLifecycle(snapshot: RuntimeSnapshot): LifecycleBlock[] {
  const stageLookup = new Map(snapshot.stageNodes.map((node) => [node.id, node]))
  const clusterTarget = Number.parseInt(
    controlValue(snapshot.strategyControls, 'AIOPS_CLUSTER_MIN_ALERTS'),
    10,
  )
  const clusterWindow = controlValue(
    snapshot.strategyControls,
    'AIOPS_CLUSTER_WINDOW_SEC',
  )
  const clusterProgress = Math.max(
    0,
    ...snapshot.clusterWatch.map((item) => item.progress),
  )
  const clusterLive = snapshot.suggestions.some(
    (suggestion) => suggestion.scope === 'cluster',
  )
  const clusterStatus: StageNode['status'] = clusterLive
    ? 'flowing'
    : clusterProgress > 0
      ? 'watch'
      : 'steady'

  const sourceIds = [
    'fortigate',
    'ingest',
    'forwarder',
    'raw-topic',
    'correlator',
    'alerts-topic',
    'aiops-agent',
    'suggestions-topic',
    'remediation',
  ]

  const orderedStages = sourceIds
    .map((id) => stageLookup.get(id))
    .filter((stage): stage is StageNode => Boolean(stage))
    .map((stage) => ({
      id: stage.id,
      title: stage.title,
      subtitle: stage.subtitle,
      status: stage.status,
      metrics: stage.metrics.slice(0, 2),
    }))

  const clusterBlock: LifecycleBlock = {
    id: 'cluster-window',
    title: 'cluster window',
    subtitle: 'same-key aggregation gate',
    status: clusterStatus,
    metrics: [
      {
        label: 'progress',
        value: `${clusterProgress}/${Number.isFinite(clusterTarget) ? clusterTarget : 3}`,
      },
      {
        label: 'window',
        value: `${clusterWindow}s`,
      },
    ],
  }

  return [
    ...orderedStages.slice(0, 6),
    clusterBlock,
    ...orderedStages.slice(6),
  ]
}

function pulseStageIds(kind: FeedEvent['kind'], scope: SuggestionRecord['scope']) {
  if (kind === 'raw') {
    return ['fortigate', 'ingest', 'forwarder', 'raw-topic']
  }

  if (kind === 'alert') {
    return ['correlator', 'alerts-topic', 'cluster-window']
  }

  return scope === 'cluster'
    ? ['cluster-window', 'aiops-agent', 'suggestions-topic', 'remediation']
    : ['aiops-agent', 'suggestions-topic', 'remediation']
}

function currentStageIndex(blocks: LifecycleBlock[], kind: FeedEvent['kind']) {
  if (kind === 'raw') {
    return blocks.findIndex((block) => block.id === 'raw-topic')
  }

  if (kind === 'alert') {
    return blocks.findIndex((block) => block.id === 'cluster-window')
  }

  return blocks.findIndex((block) => block.id === 'suggestions-topic')
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

export function LiveFlowConsole({
  snapshot,
  selectedSuggestion,
  onSelectSuggestion,
}: LiveFlowConsoleProps) {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)

  const pulseKind = snapshot.feed[0]?.kind ?? 'suggestion'
  const lifecycle = useMemo(() => buildLifecycle(snapshot), [snapshot])
  const pulseIds = useMemo(
    () => pulseStageIds(pulseKind, selectedSuggestion.scope),
    [pulseKind, selectedSuggestion.scope],
  )
  const leadEventId =
    snapshot.feed[0]?.id ??
    snapshot.runtime.latestSuggestionTs ??
    snapshot.runtime.latestAlertTs
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
  const activeStageIndex = currentStageIndex(lifecycle, pulseKind)
  const activeSummary = activeEvent
    ? eventSummary(activeEvent, linkedSuggestion)
    : null

  return (
    <section className="page console-page">
      <section className="section lifecycle-stage">
        <div className="section-header">
          <div>
            <h2 className="section-title">Live Event Lifecycle</h2>
            <span className="section-subtitle">
              Process first: ingest, deterministic alerting, cluster gate,
              suggestion, remediation boundary.
            </span>
          </div>
          <div className="annotation-stack">
            <span className="section-kicker">directional runtime flow</span>
            <span className={`signal-chip tone-${pulseKind}`}>{pulseKind}</span>
          </div>
        </div>

        <div className="lifecycle-track">
          {lifecycle.map((block, index) => {
            const isPulsing = pulseIds.includes(block.id)
            const pulseClass = isPulsing ? `pulse-${leadEventId.length % 2}` : ''
            const reached = index <= activeStageIndex ? 'is-reached' : ''

            return (
              <div
                key={`${block.id}-${isPulsing ? leadEventId : 'steady'}`}
                className="stage-segment"
              >
                <article
                  className={`stage-card state-${block.status} ${pulseClass} ${reached}`}
                >
                  <div className="stage-header">
                    <span className="stage-index">
                      {(index + 1).toString().padStart(2, '0')}
                    </span>
                    <div>
                      <strong>{block.title}</strong>
                      <span>{block.subtitle}</span>
                    </div>
                  </div>
                  <ul className="stage-metrics">
                    {block.metrics.map((metric) => (
                      <li key={`${block.id}-${metric.label}`}>
                        <span>{metric.label}</span>
                        <strong>{metric.value}</strong>
                      </li>
                    ))}
                  </ul>
                </article>

                {index < lifecycle.length - 1 ? (
                  <div
                    className={`stage-link ${pulseIds.includes(lifecycle[index + 1].id) ? `pulse-${leadEventId.length % 2}` : ''}`}
                    aria-hidden="true"
                  >
                    <span className="stage-link-line" />
                    <span className="stage-link-runner" />
                  </div>
                ) : null}
              </div>
            )
          })}
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

      <div className="console-core">
        <section className="section cluster-rail">
          <div className="section-header">
            <div>
              <h2 className="section-title">Cluster Watch</h2>
              <span className="section-subtitle">
                Same-key pre-trigger surface for the live cluster path.
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
                <p>{item.note}</p>
              </li>
            ))}
          </ul>
        </section>

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
            {snapshot.timeline.map((step, index) => (
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

        <section className="section event-stack-panel">
          <div className="section-header">
            <div>
              <h2 className="section-title">Event Queue</h2>
              <span className="section-subtitle">
                Static by default. New events push to the top and call attention
                to themselves once.
              </span>
            </div>
            <span className="section-kicker">newest first / click to inspect</span>
          </div>

          <div className="event-stack">
            {queueEvents.map((event, index) => {
              const isLead = index === 0
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
                Drill into the active event instead of watching a decorative
                ticker.
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
    </section>
  )
}
