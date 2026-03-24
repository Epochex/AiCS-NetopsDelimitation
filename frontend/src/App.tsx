import { useMemo, useState } from 'react'
import './App.css'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LiveFlowConsole } from './components/LiveFlowConsole'
import { PipelineTopologyView } from './components/PipelineTopologyView'
import { runtimeSnapshot } from './data/runtimeModel'
import { useRuntimeSnapshot } from './hooks/useRuntimeSnapshot'

type ViewMode = 'console' | 'topology'

function App() {
  const { snapshot, connectionState } = useRuntimeSnapshot()
  const suggestionPool =
    snapshot.suggestions.length > 0
      ? snapshot.suggestions
      : runtimeSnapshot.suggestions
  const defaultSuggestionId =
    snapshot.defaultSuggestionId || suggestionPool[0]?.id || runtimeSnapshot.defaultSuggestionId
  const [view, setView] = useState<ViewMode>('console')
  const [preferredSuggestionId, setPreferredSuggestionId] =
    useState(defaultSuggestionId)
  const activeSuggestionId = suggestionPool.some(
    (suggestion) => suggestion.id === preferredSuggestionId,
  )
    ? preferredSuggestionId
    : defaultSuggestionId

  const selectedSuggestion = useMemo(
    () =>
      suggestionPool.find(
        (suggestion) => suggestion.id === activeSuggestionId,
      ) ?? suggestionPool[0],
    [activeSuggestionId, suggestionPool],
  )

  if (!selectedSuggestion) {
    return (
      <div className="app-shell">
        <section className="page" style={{ borderRight: 'none' }}>
          <section className="section error-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">No Suggestion Available</h2>
                <span className="section-subtitle">
                  The frontend has no suggestion slice to bind the current
                  runtime story to.
                </span>
              </div>
              <span className="section-kicker">empty runtime selection</span>
            </div>
            <div className="error-panel-body">
              <strong>Check `/api/runtime/snapshot` and the local fallback model.</strong>
            </div>
          </section>
        </section>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Hybrid NetOps / Narrative Runtime Console</p>
          <h1>Live Flow Console</h1>
          <p className="lede">
            Process-centric frontend for a real FortiGate -{'>'} Kafka -{'>'}{' '}
            Correlator -{'>'} AIOps runtime.
          </p>
        </div>
        <div className="topbar-meta">
          <div className="meta-block">
            <span className="meta-label">Branch</span>
            <strong>{snapshot.repo.branch}</strong>
          </div>
          <div className="meta-block">
            <span className="meta-label">Baseline</span>
            <strong>{snapshot.repo.validation}</strong>
          </div>
          <div className="meta-block">
            <span className="meta-label">Latest Suggestion</span>
            <strong>{snapshot.runtime.latestSuggestionTs}</strong>
          </div>
          <div className="meta-block">
            <span className="meta-label">Feed Mode</span>
            <strong>{connectionState}</strong>
            <span className={`status-pill status-${connectionState}`}>
              {connectionState}
            </span>
          </div>
        </div>
      </header>

      <nav className="view-switch" aria-label="Primary views">
        <button
          type="button"
          className={view === 'console' ? 'tab is-active' : 'tab'}
          onClick={() => setView('console')}
        >
          Live Flow Console
        </button>
        <button
          type="button"
          className={view === 'topology' ? 'tab is-active' : 'tab'}
          onClick={() => setView('topology')}
        >
          Pipeline Topology
        </button>
      </nav>

      <main className="workspace">
        <ErrorBoundary title="Primary View">
          {view === 'console' ? (
            <LiveFlowConsole
              snapshot={snapshot}
              selectedSuggestionId={selectedSuggestion.id}
              onSelectSuggestion={setPreferredSuggestionId}
            />
          ) : (
            <PipelineTopologyView
              snapshot={snapshot}
              selectedSuggestionId={selectedSuggestion.id}
              onSelectSuggestion={setPreferredSuggestionId}
            />
          )}
        </ErrorBoundary>

        <ErrorBoundary title="Evidence Drawer">
          <EvidenceDrawer
            suggestion={selectedSuggestion}
            controls={snapshot.strategyControls}
          />
        </ErrorBoundary>
      </main>
    </div>
  )
}

export default App
