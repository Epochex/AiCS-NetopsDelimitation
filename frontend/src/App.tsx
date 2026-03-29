import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import './App.css'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LiveFlowConsole } from './components/LiveFlowConsole'
import { PipelineTopologyView } from './components/PipelineTopologyView'
import { runtimeSnapshot } from './data/runtimeModel'
import { useRuntimeSnapshot } from './hooks/useRuntimeSnapshot'
import { formatMaybeTimestamp, timestampTooltip } from './utils/time'

type ViewMode = 'console' | 'topology' | 'compare'
type Locale = 'en' | 'zh'

const CompareModeView = lazy(() =>
  import('./components/CompareModeView').then((module) => ({
    default: module.CompareModeView,
  })),
)

function metricValue(snapshot: ReturnType<typeof useRuntimeSnapshot>['snapshot'], id: string) {
  return snapshot.overviewMetrics.find((metric) => metric.id === id)?.value ?? 'n/a'
}

function firstDeviceName(snapshot: ReturnType<typeof useRuntimeSnapshot>['snapshot']) {
  const suggestion = snapshot.suggestions[0]
  const deviceName = suggestion?.evidenceBundle.device.device_name
  return typeof deviceName === 'string' && deviceName ? deviceName : null
}

function selectedDeviceLabel(
  snapshot: ReturnType<typeof useRuntimeSnapshot>['snapshot'],
  suggestion: ReturnType<typeof useRuntimeSnapshot>['snapshot']['suggestions'][number],
) {
  const deviceName = suggestion?.evidenceBundle.device.device_name
  if (typeof deviceName === 'string' && deviceName.trim().length > 0) {
    return deviceName
  }

  return firstDeviceName(snapshot) ?? suggestion.context.srcDeviceKey
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
  const [locale, setLocale] = useState<Locale>('en')
  const [showSurfacePanel, setShowSurfacePanel] = useState(false)
  const [showEvidenceDrawer, setShowEvidenceDrawer] = useState(false)
  const [showSurfaceDock, setShowSurfaceDock] = useState(true)
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
  const copy = useMemo(
    () =>
      locale === 'zh'
        ? {
            kicker: 'Hybrid NetOps / 运行事件总览',
            titleConsole: '运行事件总览',
            titleTopology: '系统链路地图',
            titleCompare: '策略对比',
            navConsole: '首页总览',
            navTopology: '链路地图',
            navCompare: '对比模式',
            labels: {
              service: '当前服务',
              device: '当前设备',
              judgment: '当前判断',
              stream: '数据流状态',
              latestSuggestion: '最新建议',
              nextAction: '下一步动作',
              branch: '分支',
              validation: '验证状态',
              latestAlert: '最新告警',
              closure: '闭环状态',
            },
          }
        : {
            kicker: 'Hybrid NetOps / Runtime Incident Overview',
            titleConsole: 'Runtime Incident Overview',
            titleTopology: 'System Flow Map',
            titleCompare: 'Compare Mode',
            navConsole: 'Overview',
            navTopology: 'Flow Map',
            navCompare: 'Compare',
            labels: {
              service: 'active service',
              device: 'active device',
              judgment: 'current judgment',
              stream: 'stream state',
              latestSuggestion: 'latest suggestion',
              nextAction: 'next action',
              branch: 'branch',
              validation: 'validation',
              latestAlert: 'latest alert',
              closure: 'closure',
            },
          },
    [locale],
  )
  const utilityItems = useMemo(
    () =>
      view === 'console'
        ? [
            { label: copy.labels.service, value: selectedSuggestion.context.service },
            {
              label: copy.labels.device,
              value:
                firstDeviceName(snapshot) ??
                selectedSuggestion.context.srcDeviceKey,
            },
            {
              label: copy.labels.judgment,
              value: `${selectedSuggestion.scope} · ${selectedSuggestion.confidenceLabel}`,
            },
            { label: copy.labels.stream, value: connectionState, tone: connectionState },
            {
              label: copy.labels.latestSuggestion,
              value: snapshot.runtime.latestSuggestionTs,
            },
            {
              label: copy.labels.nextAction,
              value:
                selectedSuggestion.recommendedActions[0] ??
                'inspect evidence bundle',
            },
          ]
        : [
            { label: copy.labels.branch, value: snapshot.repo.branch },
            { label: copy.labels.validation, value: snapshot.repo.validation },
            { label: copy.labels.stream, value: connectionState, tone: connectionState },
            { label: copy.labels.latestAlert, value: snapshot.runtime.latestAlertTs },
            {
              label: copy.labels.latestSuggestion,
              value: snapshot.runtime.latestSuggestionTs,
            },
            { label: copy.labels.closure, value: metricValue(snapshot, 'closure') },
          ],
    [connectionState, copy, selectedSuggestion, snapshot, view],
  )
  const dockSummary = useMemo(
    () =>
      locale === 'zh'
        ? `${selectedSuggestion.context.service} · ${selectedDeviceLabel(snapshot, selectedSuggestion)} · ${selectedSuggestion.confidenceLabel}`
        : `${selectedSuggestion.context.service} · ${selectedDeviceLabel(snapshot, selectedSuggestion)} · ${selectedSuggestion.confidenceLabel}`,
    [locale, selectedSuggestion, snapshot],
  )
  const primaryTitle =
    view === 'console'
      ? copy.titleConsole
      : view === 'topology'
        ? copy.titleTopology
        : copy.titleCompare
  const canCollapseDock =
    view === 'console' && !showSurfacePanel && !showEvidenceDrawer

  useEffect(() => {
    if (!canCollapseDock) {
      setShowSurfaceDock(true)
      return
    }

    let previousY = window.scrollY

    const handleScroll = () => {
      const currentY = window.scrollY
      const scrollingDown = currentY > previousY

      if (currentY <= 20) {
        setShowSurfaceDock(true)
      } else if (scrollingDown && currentY > 40) {
        setShowSurfaceDock(false)
      } else if (!scrollingDown && previousY - currentY > 10) {
        setShowSurfaceDock(true)
      }

      previousY = currentY
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [canCollapseDock])

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
    <div
      className={`app-shell ${canCollapseDock && !showSurfaceDock ? 'dock-collapsed' : ''}`}
    >
      <header
        className={`surface-dock ${canCollapseDock && !showSurfaceDock ? 'is-hidden' : ''}`}
      >
        <div className="surface-dock-brand">
          <span className="surface-dock-kicker">{copy.kicker}</span>
          <div className="surface-dock-title">
            <strong>{primaryTitle}</strong>
            <span
              className={`live-dot state-${connectionState}`}
              aria-hidden="true"
            />
          </div>
          <span className="surface-dock-summary">{dockSummary}</span>
        </div>

        <div className="surface-dock-controls">
          <nav className="view-switch surface-switch" aria-label="Primary views">
            <button
              type="button"
              className={view === 'console' ? 'tab is-active' : 'tab'}
              onClick={() => {
                setView('console')
                setShowSurfacePanel(false)
              }}
            >
              {copy.navConsole}
            </button>
            <button
              type="button"
              className={view === 'topology' ? 'tab is-active' : 'tab'}
              onClick={() => {
                setView('topology')
                setShowSurfacePanel(false)
              }}
            >
              {copy.navTopology}
            </button>
            <button
              type="button"
              className={view === 'compare' ? 'tab is-active' : 'tab'}
              onClick={() => {
                setView('compare')
                setShowSurfacePanel(false)
                setShowEvidenceDrawer(false)
              }}
            >
              {copy.navCompare}
            </button>
          </nav>

          <div className="locale-switch surface-switch" aria-label="Language switch">
            <button
              type="button"
              className={locale === 'en' ? 'tab is-active' : 'tab'}
              onClick={() => setLocale('en')}
            >
              EN
            </button>
            <button
              type="button"
              className={locale === 'zh' ? 'tab is-active' : 'tab'}
              onClick={() => setLocale('zh')}
            >
              中文
            </button>
          </div>

          <div className="surface-dock-actions">
            <button
              type="button"
              className={showSurfacePanel ? 'tab is-active' : 'tab'}
              onClick={() => setShowSurfacePanel((open) => !open)}
            >
              {locale === 'zh' ? '运行概览' : 'Runtime Sheet'}
            </button>

            {view !== 'compare' ? (
              <button
                type="button"
                className={showEvidenceDrawer ? 'tab is-active' : 'tab'}
                onClick={() => setShowEvidenceDrawer((open) => !open)}
              >
                {locale === 'zh' ? '当前建议' : 'Current Brief'}
              </button>
            ) : null}
          </div>
        </div>
      </header>

      {showSurfacePanel ? (
        <>
          <button
            type="button"
            className="surface-backdrop"
            aria-label={locale === 'zh' ? '关闭运行概览' : 'Close runtime sheet'}
            onClick={() => setShowSurfacePanel(false)}
          />
          <aside className="surface-panel">
            <div className="surface-panel-header">
              <div>
                <span className="section-kicker">
                  {locale === 'zh' ? '折叠运行面板' : 'collapsed runtime surface'}
                </span>
                <h2>{locale === 'zh' ? '运行概览' : 'Runtime Sheet'}</h2>
              </div>
              <button
                type="button"
                className="surface-close"
                onClick={() => setShowSurfacePanel(false)}
              >
                {locale === 'zh' ? '关闭' : 'Close'}
              </button>
            </div>

            <div className="utility-track surface-track">
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
          </aside>
        </>
      ) : null}

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
              locale={locale}
              onOpenEvidence={() => setShowEvidenceDrawer(true)}
              onOpenRuntimeSheet={() => setShowSurfacePanel(true)}
            />
          ) : view === 'topology' ? (
            <PipelineTopologyView snapshot={snapshot} />
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
      </main>

      {view === 'console' && !showEvidenceDrawer ? (
        <button
          type="button"
          className="drawer-launcher"
          onClick={() => setShowEvidenceDrawer(true)}
        >
          <span>{locale === 'zh' ? '展开当前建议' : 'Open current brief'}</span>
          <strong>
            {selectedSuggestion.context.service} ·{' '}
            {selectedDeviceLabel(snapshot, selectedSuggestion)}
          </strong>
        </button>
      ) : null}

      {view === 'console' && showEvidenceDrawer ? (
        <div className="drawer-overlay">
          <button
            type="button"
            className="drawer-backdrop"
            aria-label={locale === 'zh' ? '关闭当前建议' : 'Close current brief'}
            onClick={() => setShowEvidenceDrawer(false)}
          />
          <div className="drawer-shell">
            <ErrorBoundary title="Evidence Drawer">
              <EvidenceDrawer
                key={selectedSuggestion.id}
                suggestion={selectedSuggestion}
                controls={snapshot.strategyControls}
                locale={locale}
                onClose={() => setShowEvidenceDrawer(false)}
              />
            </ErrorBoundary>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default App
