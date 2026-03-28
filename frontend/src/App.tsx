import { lazy, Suspense, useMemo, useState } from 'react'
import './App.css'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LiveFlowConsole } from './components/LiveFlowConsole'
import { PipelineTopologyView } from './components/PipelineTopologyView'
import { runtimeSnapshot } from './data/runtimeModel'
import { useRuntimeSnapshot } from './hooks/useRuntimeSnapshot'
import { formatMaybeTimestamp, timestampTooltip } from './utils/time'

type ViewMode = 'console' | 'topology' | 'compare'

const CompareModeView = lazy(() =>
  import('./components/CompareModeView').then((module) => ({
    default: module.CompareModeView,
  })),
)

function metricValue(snapshot: ReturnType<typeof useRuntimeSnapshot>['snapshot'], id: string) {
  return snapshot.overviewMetrics.find((metric) => metric.id === id)?.value ?? 'n/a'
}

function App() {
  const { snapshot, latestDelta, connectionState, transportIssue } =
    useRuntimeSnapshot()
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
    () =>
      view === 'console'
        ? [
            { label: 'active service', value: selectedSuggestion.context.service },
            { label: 'active device', value: selectedSuggestion.context.srcDeviceKey },
            {
              label: 'judgment',
              value: `${selectedSuggestion.scope} · ${selectedSuggestion.confidenceLabel}`,
            },
            { label: 'stream', value: connectionState, tone: connectionState },
            { label: 'latest suggestion', value: snapshot.runtime.latestSuggestionTs },
            {
              label: 'next action',
              value:
                selectedSuggestion.recommendedActions[0] ??
                'inspect evidence bundle',
            },
          ]
        : [
            { label: 'branch', value: snapshot.repo.branch },
            { label: 'validation', value: snapshot.repo.validation },
            { label: 'stream', value: connectionState, tone: connectionState },
            { label: 'latest alert', value: snapshot.runtime.latestAlertTs },
            { label: 'latest suggestion', value: snapshot.runtime.latestSuggestionTs },
            { label: 'closure', value: metricValue(snapshot, 'closure') },
          ],
    [connectionState, selectedSuggestion, snapshot, view],
  )
  const primaryTitle =
    view === 'console'
      ? 'Guided Runtime Overview'
      : view === 'topology'
        ? 'Pipeline Topology'
        : 'Compare Mode'

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
            <h1>{primaryTitle}</h1>
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
            Guided Overview
          </button>
          <button
            type="button"
            className={view === 'topology' ? 'tab is-active' : 'tab'}
            onClick={() => setView('topology')}
          >
            Pipeline Topology
          </button>
          <button
            type="button"
            className={view === 'compare' ? 'tab is-active' : 'tab'}
            onClick={() => setView('compare')}
          >
            Compare Mode
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

      <main className={view === 'compare' ? 'workspace workspace-compare' : 'workspace'}>
        <ErrorBoundary title="Primary View">
          {view === 'console' ? (
            <LiveFlowConsole
              connectionState={connectionState}
              snapshot={snapshot}
              latestDelta={latestDelta}
              selectedSuggestion={selectedSuggestion}
              onSelectSuggestion={setPreferredSuggestionId}
              transportIssue={transportIssue}
            />
          ) : view === 'topology' ? (
            <PipelineTopologyView
              snapshot={snapshot}
              selectedSuggestionId={selectedSuggestion.id}
              onSelectSuggestion={setPreferredSuggestionId}
            />
          ) : (
            <Suspense
              fallback={
                <section className="page">
                  <section className="section chart-fallback">
                    loading compare mode...
                  </section>
                </section>
              }
            >
              <CompareModeView />
            </Suspense>
          )}
        </ErrorBoundary>

        {view !== 'compare' ? (
          <ErrorBoundary title="Evidence Drawer">
            <EvidenceDrawer
              key={selectedSuggestion.id}
              suggestion={selectedSuggestion}
              controls={snapshot.strategyControls}
            />
          </ErrorBoundary>
        ) : null}
      </main>
    </div>
  )
}

export default App
