import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import './App.css'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LiveFlowConsole } from './components/LiveFlowConsole'
import { PipelineTopologyView } from './components/PipelineTopologyView'
import { runtimeSnapshot } from './data/runtimeModel'
import { useRuntimeSnapshot } from './hooks/useRuntimeSnapshot'
import { pick, type UiLocale } from './i18n'
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
  const [locale, setLocale] = useState<UiLocale>('en')
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
            {
              label: pick(locale, 'active service', '当前服务'),
              value: selectedSuggestion.context.service,
            },
            {
              label: pick(locale, 'active device', '当前设备'),
              value: selectedSuggestion.context.srcDeviceKey,
            },
            {
              label: pick(locale, 'judgment', '系统判断'),
              value: `${selectedSuggestion.scope} · ${selectedSuggestion.confidenceLabel}`,
            },
            {
              label: pick(locale, 'stream', '流状态'),
              value: connectionState,
              tone: connectionState,
            },
            {
              label: pick(locale, 'latest suggestion', '最新建议'),
              value: snapshot.runtime.latestSuggestionTs,
            },
            {
              label: pick(locale, 'next action', '下一动作'),
              value:
                selectedSuggestion.recommendedActions[0] ??
                pick(locale, 'inspect evidence bundle', '检查证据包'),
            },
          ]
        : [
            { label: pick(locale, 'branch', '分支'), value: snapshot.repo.branch },
            { label: pick(locale, 'validation', '校验'), value: snapshot.repo.validation },
            {
              label: pick(locale, 'stream', '流状态'),
              value: connectionState,
              tone: connectionState,
            },
            {
              label: pick(locale, 'latest alert', '最新告警'),
              value: snapshot.runtime.latestAlertTs,
            },
            {
              label: pick(locale, 'latest suggestion', '最新建议'),
              value: snapshot.runtime.latestSuggestionTs,
            },
            { label: pick(locale, 'closure', '闭环状态'), value: metricValue(snapshot, 'closure') },
          ],
    [connectionState, locale, selectedSuggestion, snapshot, view],
  )
  const primaryTitle =
    view === 'console'
      ? pick(locale, 'Guided Runtime Overview', '运行总览')
      : view === 'topology'
        ? pick(locale, 'Pipeline Topology', '拓扑视图')
        : pick(locale, 'Compare Mode', '对照模式')

  if (!selectedSuggestion) {
    return (
      <div className="app-shell">
        <section className="page" style={{ borderRight: 'none' }}>
          <section className="section error-panel">
            <div className="section-header">
              <div>
                <h2 className="section-title">No Suggestion Available</h2>
                <span className="section-subtitle">
                  {pick(
                    locale,
                    'The frontend has no suggestion slice to bind the current runtime story to.',
                    '当前前端没有可绑定的 suggestion slice，所以无法建立运行时故事线。',
                  )}
                </span>
              </div>
              <span className="section-kicker">
                {pick(locale, 'empty runtime selection', '运行时选择为空')}
              </span>
            </div>
            <div className="error-panel-body">
              <strong>
                {pick(
                  locale,
                  'Check `/api/runtime/snapshot` and the local fallback model.',
                  '检查 `/api/runtime/snapshot` 与本地 fallback model。',
                )}
              </strong>
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
          <p className="rail-kicker">
            {pick(
              locale,
              'Hybrid NetOps / Tactical Runtime Console',
              '混合式 NetOps / 战术运行时控制台',
            )}
          </p>
          <div className="rail-title-row">
            <h1>{primaryTitle}</h1>
            <span
              className={`live-dot state-${connectionState}`}
              aria-hidden="true"
            />
          </div>
          <span className="surface-dock-summary">{dockSummary}</span> 
        </div>

        <nav className="view-switch" aria-label="Primary views">
          <button
            type="button"
            className={view === 'console' ? 'tab is-active' : 'tab'}
            onClick={() => setView('console')}
          >
            {pick(locale, 'Guided Overview', '首页总览')}
          </button>
          <button
            type="button"
            className={view === 'topology' ? 'tab is-active' : 'tab'}
            onClick={() => setView('topology')}
          >
            {pick(locale, 'Pipeline Topology', '管线拓扑')}
          </button>
          <button
            type="button"
            className={view === 'compare' ? 'tab is-active' : 'tab'}
            onClick={() => setView('compare')}
          >
            {pick(locale, 'Compare Mode', '对照模式')}
          </button>
        </nav>

        <div className="locale-switch" aria-label="Language switch">
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

        <div className="utility-track">
          {utilityItems.map((item) => (
            <div
              key={item.label}
              className={`utility-item tone-${item.tone ?? 'neutral'}`}
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
            />
          ) : view === 'topology' ? (
            <PipelineTopologyView snapshot={snapshot} locale={locale} />
          ) : (
            <Suspense
              fallback={
                <section className="page">
                  <section className="section chart-fallback">
                    {pick(locale, 'loading compare mode...', '正在加载对照模式...')}
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
              locale={locale}
            />
          </ErrorBoundary>
        ) : null}
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
