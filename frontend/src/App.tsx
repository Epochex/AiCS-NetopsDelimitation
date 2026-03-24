import { useMemo, useState } from 'react'
import './App.css'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LiveFlowConsole } from './components/LiveFlowConsole'
import { PipelineTopologyView } from './components/PipelineTopologyView'
import { runtimeSnapshot } from './data/runtimeModel'
import { useRuntimeSnapshot } from './hooks/useRuntimeSnapshot'
import { formatMaybeTimestamp, timestampTooltip } from './utils/time'

type ViewMode = 'console' | 'topology'

function metricValue(snapshot: ReturnType<typeof useRuntimeSnapshot>['snapshot'], id: string) {
  return snapshot.overviewMetrics.find((metric) => metric.id === id)?.value ?? 'n/a'
}

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
  const utilityItems = useMemo(
    () => [
      { label: 'branch', value: snapshot.repo.branch },
      { label: 'validation', value: snapshot.repo.validation },
      { label: 'stream', value: connectionState, tone: connectionState },
      { label: 'latest alert', value: snapshot.runtime.latestAlertTs },
      { label: 'latest suggestion', value: snapshot.runtime.latestSuggestionTs },
      { label: 'closure', value: metricValue(snapshot, 'closure') },
    ],
    [connectionState, snapshot],
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
      <header className="utility-rail">
        <div className="rail-brand">
          <p className="rail-kicker">Hybrid NetOps / Tactical Runtime Console</p>
          <div className="rail-title-row">
            <h1>Live Flow Console</h1>
            <span
              className={`live-dot state-${connectionState}`}
              aria-hidden="true"
            />
          </div>
        </div>

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

        <div className="utility-track">
          {utilityItems.map((item) => (
            <div
              key={item.label}
              className={`utility-item tone-${item.tone ?? 'neutral'}`}
            >
              <span className="utility-label">{item.label}</span>
              <strong
                className="utility-value"
                title={timestampTooltip(item.value)}
              >
                {formatMaybeTimestamp(item.value)}
              </strong>
            </div>
          ))}
        </div>
      </header>

      <main className="workspace">
        <ErrorBoundary title="Primary View">
          {view === 'console' ? (
            <LiveFlowConsole
              snapshot={snapshot}
              selectedSuggestion={selectedSuggestion}
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
            key={selectedSuggestion.id}
            suggestion={selectedSuggestion}
            controls={snapshot.strategyControls}
          />
        </ErrorBoundary>
      </main>
    </div>
  )
}

export default App
