import { lazy, Suspense } from 'react'
import { ErrorBoundary } from './ErrorBoundary'
import type { RuntimeSnapshot } from '../types'

const TrendChart = lazy(() =>
  import('./TrendChart').then((module) => ({ default: module.TrendChart })),
)
const TopologyCanvas = lazy(() =>
  import('./TopologyCanvas').then((module) => ({
    default: module.TopologyCanvas,
  })),
)

interface LiveFlowConsoleProps {
  snapshot: RuntimeSnapshot
  selectedSuggestionId: string
  onSelectSuggestion: (suggestionId: string) => void
}

export function LiveFlowConsole({
  snapshot,
  selectedSuggestionId,
  onSelectSuggestion,
}: LiveFlowConsoleProps) {
  return (
    <section className="page">
      <div className="section">
        <div className="section-header">
          <div>
            <h2 className="section-title">Global Runtime Overview</h2>
            <span className="section-subtitle">
              Not a panel wall. A compact situational rail for freshness,
              backlog, day volume, and closure state.
            </span>
          </div>
          <span className="section-kicker">{snapshot.runtime.contextNote}</span>
        </div>
        <div className="overview-grid">
          {snapshot.overviewMetrics.map((metric) => (
            <article
              key={metric.id}
              className={`metric-card state-${metric.state}`}
            >
              <span className="metric-label">{metric.label}</span>
              <strong className="metric-value">{metric.value}</strong>
              <span className="metric-hint">{metric.hint}</span>
            </article>
          ))}
        </div>
      </div>

      <div className="page-grid">
        <aside className="stack">
          <section className="section aside-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">Cadence</h2>
                <span className="section-subtitle">
                  Alerts and suggestions move together when the slow path is
                  healthy.
                </span>
              </div>
              <span className="section-kicker">current-day activity</span>
            </div>
            <ErrorBoundary title="Cadence Chart">
              <Suspense fallback={<div className="chart-shell chart-fallback">loading chart...</div>}>
                <div className="chart-shell">
                  <TrendChart
                    title="Alert vs Suggestion cadence"
                    labels={snapshot.cadence.labels}
                    series={[
                      {
                        name: 'alerts',
                        data: snapshot.cadence.alerts,
                        color: '#ff7a20',
                      },
                      {
                        name: 'suggestions',
                        data: snapshot.cadence.suggestions,
                        color: '#69f9ff',
                      },
                    ]}
                  />
                </div>
              </Suspense>
            </ErrorBoundary>
          </section>

          <section className="section aside-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">Evidence Thickness</h2>
                <span className="section-subtitle">
                  Today’s sample suggests the evidence path is no longer thin.
                </span>
              </div>
              <span className="section-kicker">current-day alert sample</span>
            </div>
            <ErrorBoundary title="Evidence Coverage Chart">
              <Suspense fallback={<div className="chart-shell chart-fallback">loading chart...</div>}>
                <div className="chart-shell">
                  <TrendChart
                    title="Evidence presence"
                    labels={snapshot.evidenceCoverage.labels}
                    series={[
                      {
                        name: 'coverage',
                        data: snapshot.evidenceCoverage.values,
                        color: '#6cff9b',
                      },
                    ]}
                    unit="%"
                  />
                </div>
              </Suspense>
            </ErrorBoundary>
          </section>

          <section className="section aside-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">Cluster Pre-Trigger Watch</h2>
                <span className="section-subtitle">
                  Same aggregator semantics as the backend: rule + severity +
                  service + src_device_key.
                </span>
              </div>
              <span className="section-kicker">600s / min=3 watch</span>
            </div>
            <ul className="cluster-list">
              {snapshot.clusterWatch.map((item) => (
                <li key={item.key} className="cluster-item">
                  <div className="cluster-row">
                    <div className="cluster-key">
                      <strong>{item.service}</strong>
                      <span className="cluster-meta">{item.device}</span>
                    </div>
                    <span className="cluster-ratio">
                      {item.progress}/{item.target}
                    </span>
                  </div>
                  <div className="progress" aria-hidden="true">
                    <span
                      style={{
                        width: `${(item.progress / item.target) * 100}%`,
                      }}
                    />
                  </div>
                  <p className="cluster-meta">{item.note}</p>
                </li>
              ))}
            </ul>
          </section>
        </aside>

        <div className="canvas-stack">
          <section className="section">
            <div className="section-header">
              <div>
                <h2 className="section-title">Event Flow / Pipeline Topology</h2>
                <span className="section-subtitle">
                  Every major block maps to a real runtime module, Kafka topic,
                  or control boundary in the repository.
                </span>
              </div>
              <span className="section-kicker">tactical topology, not dashboard</span>
            </div>
            <ErrorBoundary title="Pipeline Topology Canvas">
              <Suspense fallback={<div className="flow-frame compact chart-fallback">loading topology...</div>}>
                <TopologyCanvas
                  nodes={snapshot.stageNodes}
                  links={snapshot.stageLinks}
                  compact
                />
              </Suspense>
            </ErrorBoundary>
            <div className="flow-stage-footer">
              <div className="stage-footnote">
                <strong>Deterministic core first</strong>
                <span>
                  Correlator and alerts stay visually ahead of AIOps so the main
                  chain remains explainable.
                </span>
              </div>
              <div className="stage-footnote">
                <strong>Cluster path stays visible</strong>
                <span>
                  Cluster-scope is shown as a live watch surface even when no new
                  natural cluster hit is present.
                </span>
              </div>
              <div className="stage-footnote">
                <strong>Execution boundary stays honest</strong>
                <span>
                  Remediation is presented as the next control point instead of a
                  fake active runtime stage.
                </span>
              </div>
            </div>
          </section>

          <div className="activity-grid">
            <section className="section">
              <div className="section-header">
                <div>
                  <h2 className="section-title">Runtime Chain</h2>
                  <span className="section-subtitle">
                    One event story, flattened into readable causality rather than
                    independent panels.
                  </span>
                </div>
                <span className="section-kicker">
                  selected flow: {selectedSuggestionId}
                </span>
              </div>
              <ol className="timeline-list">
                {snapshot.timeline.map((step) => (
                  <li key={step.id} className="timeline-item">
                    <div className="timeline-stamp">{step.stamp}</div>
                    <div>
                      <h3>{step.title}</h3>
                      <p>{step.detail}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </section>

            <section className="section">
              <div className="section-header">
                <div>
                  <h2 className="section-title">Live Suggestion Slice</h2>
                  <span className="section-subtitle">
                    The right drawer always reflects the selected suggestion.
                  </span>
                </div>
                <span className="section-kicker">real payloads, current day</span>
              </div>
              <div className="storyboard">
                <p>
                  Select a suggestion to pivot the evidence drawer. This keeps the
                  center pane process-centric while the right pane stays
                  explanation-centric.
                </p>
                <ul className="summary-list">
                  {snapshot.suggestions.map((suggestion) => (
                    <li key={suggestion.id}>
                      <button
                        type="button"
                        className={
                          selectedSuggestionId === suggestion.id
                            ? 'tab is-active'
                            : 'tab'
                        }
                        onClick={() => onSelectSuggestion(suggestion.id)}
                      >
                        {suggestion.context.service}
                      </button>
                      <strong>{suggestion.context.srcDeviceKey}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          </div>
        </div>
      </div>

      <section className="section">
        <div className="section-header">
          <div>
            <h2 className="section-title">Bottom Real-Time Feed</h2>
            <span className="section-subtitle">
              Raw, alert, and suggestion are kept in one live strip so the story
              stays chronological.
            </span>
          </div>
          <span className="section-kicker">chronology over panel sprawl</span>
        </div>
        <ul className="feed-list">
          {snapshot.feed.map((event) => (
            <li key={event.id} className="feed-item">
              <span className="feed-stamp">{event.stamp}</span>
              <span className={`feed-kind kind-${event.kind}`}>{event.kind}</span>
              <div className="feed-body">
                <strong>{event.title}</strong>
                <span>{event.detail}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </section>
  )
}
