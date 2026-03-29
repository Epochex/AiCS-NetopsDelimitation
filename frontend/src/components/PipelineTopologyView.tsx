import { lazy, Suspense } from 'react'
import { ErrorBoundary } from './ErrorBoundary'
import type { RuntimeSnapshot, SuggestionRecord } from '../types'

const TopologyCanvas = lazy(() =>
  import('./TopologyCanvas').then((module) => ({
    default: module.TopologyCanvas,
  })),
)

interface PipelineTopologyViewProps {
  snapshot: RuntimeSnapshot
}

function byLatestSuggestion(a: SuggestionRecord, b: SuggestionRecord) {
  return (
    new Date(b.suggestionTs).getTime() - new Date(a.suggestionTs).getTime()
  )
}

function mostFrequent(items: string[]) {
  const counts = new Map<string, number>()

  items
    .map((item) => item.trim())
    .filter(Boolean)
    .forEach((item) => {
      counts.set(item, (counts.get(item) ?? 0) + 1)
    })

  return [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0]
}

function formatStageState(status: RuntimeSnapshot['stageNodes'][number]['status']) {
  switch (status) {
    case 'flowing':
      return 'live path'
    case 'watch':
      return 'watch gate'
    case 'planned':
      return 'reserved boundary'
    default:
      return 'steady lane'
  }
}

export function PipelineTopologyView({ snapshot }: PipelineTopologyViewProps) {
  const suggestions = [...snapshot.suggestions].sort(byLatestSuggestion)
  const latestSuggestion = suggestions[0]

  const serviceCount = new Set(
    suggestions.map((suggestion) => suggestion.context.service).filter(Boolean),
  ).size
  const deviceCount = new Set(
    suggestions
      .map((suggestion) => suggestion.context.srcDeviceKey)
      .filter(Boolean),
  ).size
  const clusterIncidentCount = suggestions.filter(
    (suggestion) => suggestion.scope === 'cluster',
  ).length
  const singlePathCount = suggestions.length - clusterIncidentCount
  const readyClusterCount = snapshot.clusterWatch.filter(
    (item) => item.progress >= item.target,
  ).length
  const warmingClusterCount = snapshot.clusterWatch.filter(
    (item) => item.progress < item.target,
  ).length
  const dominantAction =
    mostFrequent(
      suggestions.flatMap((suggestion) => suggestion.recommendedActions),
    ) ?? 'No remediation action has been emitted yet.'
  const dominantRule =
    mostFrequent(suggestions.map((suggestion) => suggestion.ruleId)) ??
    'No dominant rule in the current slice'
  const highlightedStages = snapshot.stageNodes.filter(
    (node) => node.status === 'flowing' || node.status === 'watch',
  )
  const stageFocus =
    highlightedStages.length > 0 ? highlightedStages : snapshot.stageNodes
  const activeStageSummary =
    stageFocus.length > 0
      ? stageFocus
          .slice(0, 3)
          .map((node) => node.title)
          .join(' -> ')
      : 'No active runtime path is available in the current snapshot.'
  const systemVerdict = latestSuggestion
    ? clusterIncidentCount > 0
      ? `${clusterIncidentCount} repeated-pattern incident(s) already crossed the cluster gate, so this map is currently showing a system-level pattern instead of a single noisy port.`
      : `${singlePathCount} single-path incident(s) are still below cluster gate, so the system is tracking isolated pressure before it becomes a repeated pattern.`
    : 'No live suggestion is currently active, so the map is acting as a structural reference view.'
  const focusExplanation = latestSuggestion
    ? `${latestSuggestion.summary} Dominant rule: ${dominantRule}. Latest scope: ${latestSuggestion.scope === 'cluster' ? 'repeated-pattern incident' : 'single-path incident'}.`
    : 'Suggestions have not populated yet, so use this view as the end-to-end system map only.'

  return (
    <section className="page system-flow-page">
      <section className="section system-flow-stage">
        <div className="system-flow-map-shell">
          <div className="system-flow-topband">
            <div className="system-flow-heading">
              <span className="section-kicker">integrated runtime map</span>
              <h2 className="section-title">System Flow Map</h2>
              <span className="section-subtitle">
                This page now stays system-wide. It explains the whole incident
                posture first and leaves per-incident evidence to the Current
                Brief on the console page instead of making you pick one
                suggestion at a time.
              </span>
            </div>

            <div className="system-flow-stat-strip">
              <article className="system-flow-stat-card">
                <span>Active incidents</span>
                <strong>{suggestions.length}</strong>
                <p>
                  {clusterIncidentCount} repeated-pattern / {singlePathCount}{' '}
                  single-path
                </p>
              </article>
              <article className="system-flow-stat-card">
                <span>Affected footprint</span>
                <strong>
                  {serviceCount} service{serviceCount === 1 ? '' : 's'}
                </strong>
                <p>
                  {deviceCount} device{deviceCount === 1 ? '' : 's'} in the
                  current slice
                </p>
              </article>
              <article className="system-flow-stat-card">
                <span>Cluster posture</span>
                <strong>{readyClusterCount}</strong>
                <p>
                  {warmingClusterCount} watch slot
                  {warmingClusterCount === 1 ? '' : 's'} still warming
                </p>
              </article>
              <article className="system-flow-stat-card">
                <span>Dominant next action</span>
                <strong>{dominantRule}</strong>
                <p>{dominantAction}</p>
              </article>
            </div>
          </div>

          <div className="system-flow-overlay system-flow-overlay-start">
            <article className="system-flow-callout">
              <span className="section-kicker">system interpretation</span>
              <h3>
                {latestSuggestion?.summary ??
                  'No live suggestion is available right now.'}
              </h3>
              <p>{systemVerdict}</p>
            </article>

            <article className="system-flow-callout">
              <span className="section-kicker">how to read this map</span>
              <dl className="system-flow-definition-list">
                <div>
                  <dt>Problem focus</dt>
                  <dd>{focusExplanation}</dd>
                </div>
                <div>
                  <dt>Current stage focus</dt>
                  <dd>{activeStageSummary}</dd>
                </div>
                <div>
                  <dt>Recommended action</dt>
                  <dd>{dominantAction}</dd>
                </div>
                <div>
                  <dt>Single-path means</dt>
                  <dd>
                    The evidence is still concentrated on one service-device
                    path and has not crossed the repetition threshold that would
                    turn it into a grouped historical event.
                  </dd>
                </div>
              </dl>
            </article>
          </div>

          <div className="system-flow-overlay system-flow-overlay-end">
            <article className="system-flow-callout">
              <span className="section-kicker">live stage registry</span>
              <div className="system-flow-stage-list">
                {snapshot.stageNodes.map((node) => (
                  <div key={node.id} className="system-flow-stage-item">
                    <strong>{node.title}</strong>
                    <span>{formatStageState(node.status)}</span>
                    <p>{node.subtitle}</p>
                  </div>
                ))}
              </div>
            </article>
          </div>

          <ErrorBoundary title="System Flow Map">
            <Suspense
              fallback={
                <div className="flow-frame system-flow-frame chart-fallback">
                  loading system flow map...
                </div>
              }
            >
              <div className="system-flow-canvas-layer">
                <TopologyCanvas
                  nodes={snapshot.stageNodes}
                  links={snapshot.stageLinks}
                />
              </div>
            </Suspense>
          </ErrorBoundary>

          <div className="system-flow-bottom-rail">
            {snapshot.topologyNotes.slice(0, 4).map((note) => (
              <article key={note.title} className="system-flow-note-pill">
                <strong>{note.title}</strong>
                <p>{note.detail}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    </section>
  )
}
