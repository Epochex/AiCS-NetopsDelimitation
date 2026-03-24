import { lazy, Suspense } from 'react'
import { ErrorBoundary } from './ErrorBoundary'
import type { RuntimeSnapshot } from '../types'

const TopologyCanvas = lazy(() =>
  import('./TopologyCanvas').then((module) => ({
    default: module.TopologyCanvas,
  })),
)

interface PipelineTopologyViewProps {
  snapshot: RuntimeSnapshot
  selectedSuggestionId: string
  onSelectSuggestion: (suggestionId: string) => void
}

export function PipelineTopologyView({
  snapshot,
  selectedSuggestionId,
  onSelectSuggestion,
}: PipelineTopologyViewProps) {
  return (
    <section className="page">
      <div className="topology-layout">
        <section className="section">
          <div className="section-header">
            <div>
              <h2 className="section-title">Pipeline Topology</h2>
              <span className="section-subtitle">
                Watch Dogs-style network legibility without drifting into fake
                sci-fi decoration.
              </span>
            </div>
            <span className="section-kicker">module / topic / control graph</span>
          </div>
          <ErrorBoundary title="Topology Graph">
            <Suspense fallback={<div className="flow-frame chart-fallback">loading topology...</div>}>
              <TopologyCanvas
                nodes={snapshot.stageNodes}
                links={snapshot.stageLinks}
              />
            </Suspense>
          </ErrorBoundary>
        </section>

        <section className="section">
          <div className="section-header">
            <div>
              <h2 className="section-title">Registry</h2>
              <span className="section-subtitle">
                Each block is mapped to a repository module or a runtime sink.
              </span>
            </div>
            <span className="section-kicker">semantic map</span>
          </div>
          <ul className="registry-list">
            {snapshot.stageNodes.map((node) => (
              <li key={node.id} className="registry-item">
                <h3>{node.title}</h3>
                <p>{node.subtitle}</p>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="page-grid">
        <div className="stack">
          <section className="section">
            <div className="section-header">
              <div>
                <h2 className="section-title">Topology Reading Notes</h2>
                <span className="section-subtitle">
                  This view is designed to help backend strategy tuning, not only
                  runtime monitoring.
                </span>
              </div>
              <span className="section-kicker">why this shape</span>
            </div>
            <div className="hint-grid">
              {snapshot.topologyNotes.map((note) => (
                <article key={note.title} className="hint-card">
                  <strong>{note.title}</strong>
                  <p>{note.detail}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="section">
            <div className="section-header">
              <div>
                <h2 className="section-title">Suggestion Selector</h2>
                <span className="section-subtitle">
                  Keep topology and evidence coupled by selecting a live suggestion
                  slice.
                </span>
              </div>
              <span className="section-kicker">
                active selection: {selectedSuggestionId}
              </span>
            </div>
            <ul className="summary-list" style={{ padding: '0 1rem 1rem' }}>
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
          </section>
        </div>

        <div className="stack">
          <section className="section">
            <div className="section-header">
              <div>
                <h2 className="section-title">Control Boundary</h2>
                <span className="section-subtitle">
                  The topology page keeps remediation visible as a future boundary,
                  so tuning and closure do not blur together.
                </span>
              </div>
              <span className="section-kicker">operator feedback path</span>
            </div>
            <div className="hint-grid">
              <article className="hint-card">
                <strong>Observe</strong>
                <p>
                  Real-time cadence, lag posture, and current-day evidence quality
                  stay on the console page.
                </p>
              </article>
              <article className="hint-card">
                <strong>Explain</strong>
                <p>
                  Selected suggestion detail stays in the evidence drawer with
                  hypotheses and actions.
                </p>
              </article>
              <article className="hint-card">
                <strong>Act</strong>
                <p>
                  Strategy controls are visible, but execution stays explicit as a
                  not-yet-wired control surface.
                </p>
              </article>
              <article className="hint-card">
                <strong>Feed Back</strong>
                <p>
                  This makes the frontend useful for adjusting thresholds and
                  cluster semantics later, rather than only observing them.
                </p>
              </article>
            </div>
          </section>
        </div>
      </div>
    </section>
  )
}
