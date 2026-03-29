import type { RuntimeSnapshot, StageTelemetry, SuggestionRecord } from '../types'
import { pick, type UiLocale } from '../i18n'
import { formatPreciseDurationMs } from '../utils/time'

interface RuntimeVisualPanelsProps {
  snapshot: RuntimeSnapshot
  selectedSuggestion: SuggestionRecord
  locale: UiLocale
}

interface LatencyRow {
  label: string
  durationMs: number
}

interface EvidenceCoverageRow {
  label: string
  value: number
  detail: string
}

interface IncidentEnvelopeRow {
  label: string
  value: string
}

interface ProcessTraceSegment {
  id: string
  title: string
  detail: string
  value: string
  tone: 'raw' | 'alert' | 'suggestion' | 'neutral'
  state: StageTelemetry['state']
}

function buildPolyline(values: number[], width: number, height: number) {
  const max = Math.max(...values, 1)
  const innerWidth = width - 40
  const innerHeight = height - 36
  const step = values.length > 1 ? innerWidth / (values.length - 1) : 0

  return values
    .map((value, index) => {
      const x = 20 + step * index
      const y = 12 + innerHeight - (value / max) * innerHeight
      return `${x},${y}`
    })
    .join(' ')
}

function numericFromValue(value: unknown) {
  return typeof value === 'number' ? value : 0
}

function printableValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.filter((item) => typeof item === 'string' && item.trim().length > 0).join(', ')
  }
  if (typeof value === 'string') {
    return value.trim()
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return ''
}

function hasVisibleValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.some((item) => printableValue(item).length > 0)
  }

  return printableValue(value).length > 0
}

function evidenceCoverageValue(bundle: Record<string, unknown>) {
  const entries = Object.values(bundle)
  if (entries.length === 0) {
    return 0
  }

  const present = entries.filter((value) => hasVisibleValue(value)).length
  return Math.round((present / entries.length) * 100)
}

function evidenceCoverageRows(
  selectedSuggestion: SuggestionRecord,
  locale: 'en' | 'zh',
): EvidenceCoverageRow[] {
  const rows: Array<{
    label: string
    bundle: Record<string, unknown>
    fallback: string
  }> = [
    {
      label: locale === 'zh' ? '拓扑' : 'Topology',
      bundle: selectedSuggestion.evidenceBundle.topology,
      fallback:
        locale === 'zh' ? '当前事件未提供拓扑上下文。' : 'No topology context was attached to this incident.',
    },
    {
      label: locale === 'zh' ? '设备' : 'Device',
      bundle: selectedSuggestion.evidenceBundle.device,
      fallback:
        locale === 'zh' ? '当前事件未提供设备上下文。' : 'No device context was attached to this incident.',
    },
    {
      label: locale === 'zh' ? '变更 / 历史' : 'Change / Historical',
      bundle: {
        ...selectedSuggestion.evidenceBundle.change,
        ...selectedSuggestion.evidenceBundle.historical,
      },
      fallback:
        locale === 'zh'
          ? '当前事件未提供变更或历史上下文。'
          : 'No change or historical context was attached to this incident.',
    },
  ]

  return rows.map(({ label, bundle, fallback }) => {
    const firstFacts = Object.entries(bundle)
      .filter(([, value]) => hasVisibleValue(value))
      .slice(0, 2)
      .map(([key, value]) => `${key}=${printableValue(value)}`)

    return {
      label,
      value: evidenceCoverageValue(bundle),
      detail: firstFacts.join(' · ') || fallback,
    }
  })
}

function incidentEnvelopeRows(
  selectedSuggestion: SuggestionRecord,
  locale: 'en' | 'zh',
): IncidentEnvelopeRow[] {
  const sampleIds = selectedSuggestion.context.clusterSampleAlertIds
    .slice(0, 2)
    .join(', ')

  return [
    {
      label: locale === 'zh' ? '首个告警' : 'first alert',
      value: formatMaybeTimestamp(selectedSuggestion.context.clusterFirstAlertTs) || '-',
    },
    series: [
      {
        name: 'alerts',
        type: 'line',
        smooth: false,
        symbol: 'diamond',
        symbolSize: 8,
        data: snapshot.cadence.alerts,
        lineStyle: { width: 2.2, color: '#ff8a45' },
        itemStyle: { color: '#ff8a45', borderColor: '#1b242c', borderWidth: 1 },
        areaStyle: { color: 'rgba(255, 138, 69, 0.12)' },
      },
      {
        name: 'suggestions',
        type: 'line',
        smooth: false,
        symbol: 'rect',
        symbolSize: 8,
        data: snapshot.cadence.suggestions,
        lineStyle: { width: 2.2, color: '#6fffa8' },
        itemStyle: { color: '#6fffa8', borderColor: '#1b242c', borderWidth: 1 },
        areaStyle: { color: 'rgba(111, 255, 168, 0.1)' },
      },
    ],
  }
}

function processTraceSegments(
  selectedSuggestion: SuggestionRecord,
  locale: 'en' | 'zh',
): ProcessTraceSegment[] {
  const stageLookup = new Map(
    (selectedSuggestion.stageTelemetry ?? []).map((item) => [item.stageId, item]),
  )
  const orderedStages: Array<{
    id: string
    enTitle: string
    zhTitle: string
    tone: ProcessTraceSegment['tone']
    fallbackValue: string
  }> = [
    {
      id: 'fortigate',
      enTitle: 'Source signal',
      zhTitle: '源信号',
      tone: 'raw',
      fallbackValue: locale === 'zh' ? '实时来源' : 'live source',
    },
    {
      id: 'ingest',
      enTitle: 'Edge parse',
      zhTitle: '边缘解析',
      tone: 'raw',
      fallbackValue: locale === 'zh' ? '已解析' : 'parsed',
    },
    {
      id: 'raw-topic',
      enTitle: 'Raw topic',
      zhTitle: '原始主题',
      tone: 'raw',
      fallbackValue: locale === 'zh' ? '已进入流' : 'streamed',
    },
    {
      id: 'correlator',
      enTitle: 'Rule trigger',
      zhTitle: '规则触发',
      tone: 'alert',
      fallbackValue: locale === 'zh' ? '规则判定' : 'rule decision',
    },
    series: [
      {
        type: 'bar',
        data: snapshot.evidenceCoverage.values,
        barWidth: 12,
        label: {
          show: true,
          position: 'right',
          color: '#d7e4ef',
          formatter: '{c}%',
          fontSize: 10,
        },
        itemStyle: {
          color: '#69f9ff',
          borderRadius: 0,
        },
      },
    ],
  }
}

function clusterWatchRows(
  snapshot: RuntimeSnapshot,
  selectedSuggestion: SuggestionRecord,
) {
  const matchesSelection = (item: RuntimeSnapshot['clusterWatch'][number]) =>
    item.service === selectedSuggestion.context.service &&
    item.device === selectedSuggestion.context.srcDeviceKey

  return snapshot.clusterWatch
    .slice()
    .sort((left, right) => {
      const leftMatch = matchesSelection(left) ? 1 : 0
      const rightMatch = matchesSelection(right) ? 1 : 0
      if (leftMatch !== rightMatch) {
        return rightMatch - leftMatch
      }

      const leftRatio = left.target > 0 ? left.progress / left.target : 0
      const rightRatio = right.target > 0 ? right.progress / right.target : 0
      return rightRatio - leftRatio
    })
}

function latencyRows(selectedSuggestion: SuggestionRecord, locale: 'en' | 'zh'): LatencyRow[] {
  const stageLookup = new Map(
    (selectedSuggestion.stageTelemetry ?? []).map((item) => [item.stageId, item]),
  )
  const orderedStages: Array<[string, string, string]> = [
    ['correlator', 'edge -> alert', '边缘到告警'],
    ['cluster-window', 'cluster gate', '聚合门槛'],
    ['aiops-agent', 'alert -> suggestion', '告警到建议'],
  ]

  return orderedStages
    .map(([stageId, enLabel, zhLabel]) => {
      const telemetry = stageLookup.get(stageId)
      if (!telemetry || telemetry.durationMs === null || telemetry.durationMs === undefined) {
        return null
      }

      if (
        stageId === 'cluster-window' &&
        telemetry.mode === 'gate' &&
        telemetry.durationMs <= 0
      ) {
        return null
      }

      return {
        label: locale === 'zh' ? zhLabel : enLabel,
        durationMs: telemetry.durationMs,
      }
    })
    .filter((item): item is LatencyRow => item !== null)
}

function latencyOption(rows: LatencyRow[]): EChartsOption {
  return {
    animationDuration: 700,
    grid: {
      top: 12,
      right: 18,
      bottom: 18,
      left: 92,
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(6, 10, 14, 0.96)',
      borderColor: 'rgba(105, 249, 255, 0.24)',
      textStyle: { color: '#d7e4ef' },
      formatter: (params: unknown) => {
        const [first] = params as Array<{ value: number; name: string }>
        return `${first.name}: ${formatPreciseDurationMs(first.value)}`
      },
    },
    xAxis: {
      type: 'value',
      axisLabel: {
        color: '#91a5b7',
        fontSize: 10,
        formatter: (value: number) => `${(value / 1000).toFixed(3)}s`,
      },
      splitLine: { lineStyle: { color: 'rgba(157, 176, 196, 0.08)' } },
    },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      axisLabel: { color: '#91a5b7', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(157, 176, 196, 0.18)' } },
    },
    series: [
      {
        type: 'bar',
        data: rows.map((row) => row.durationMs),
        barWidth: 12,
        label: {
          show: true,
          position: 'right',
          color: '#d7e4ef',
          formatter: (params: { value?: unknown }) =>
            formatPreciseDurationMs(numericFromValue(params.value)),
          fontSize: 10,
        },
        itemStyle: {
          color: '#6fffa8',
          borderRadius: 0,
        },
      },
    ],
  }
}

function summaryLine(telemetry: StageTelemetry[] | undefined, locale: UiLocale) {
  const measured = (telemetry ?? []).filter(
    (item) =>
      item.mode === 'duration' &&
      item.durationMs !== null &&
      item.durationMs !== undefined,
  )
  const totalMs = measured.reduce((sum, item) => sum + (item.durationMs ?? 0), 0)

  return measured.length > 0
    ? pick(
        locale,
        `Measured transition budget: ${formatPreciseDurationMs(totalMs)}`,
        `已测得转场预算：${formatPreciseDurationMs(totalMs)}`,
      )
    : pick(
        locale,
        'Measured transition budget appears when live stage telemetry is present.',
        '只有存在实时阶段遥测时，才会显示已测得的转场预算。',
      )
}

export function RuntimeVisualPanels({
  snapshot,
  selectedSuggestion,
  locale,
}: RuntimeVisualPanelsProps) {
  const latency = latencyRows(selectedSuggestion)
  const t = (en: string, zh: string) => pick(locale, en, zh)

  return (
    <section className="section visual-strip visual-strip-expanded">
      <div className="section-header">
        <div>
          <h2 className="section-title">
            {t('Meaningful Runtime Visuals', '有意义的运行时可视化')}
          </h2>
          <span className="section-subtitle">
            {t(
              'Curves and bars are only kept when they answer throughput, evidence quality, or transition cost for the active incident slice.',
              '只有当曲线和柱图能解释吞吐、证据质量或转场成本时，它们才会被保留下来。',
            )}
          </span>
        </div>
        <span className="section-kicker">
          {t('signal density with purpose', '有目的的信号密度')}
        </span>
      </div>

      <div className="signal-visual-grid">
        <article className="chart-card chart-card-cadence">
          <div className="chart-meta">
            <strong>{t('Cadence parity', '节奏对齐')}</strong>
            <p>
              {t(
                'Whether suggestion emission stays close to alert arrival across the same window.',
                '同一时间窗内，建议输出是否跟上告警到达的节奏。',
              )}
            </p>
          </div>

          {hasCadence ? (
            <div className="sparkline-shell">
              <div className="sparkline-legend">
                <span className="sparkline-chip tone-alert">
                  {locale === 'zh' ? '告警' : 'alerts'}
                </span>
                <span className="sparkline-chip tone-suggestion">
                  {locale === 'zh' ? '建议' : 'suggestions'}
                </span>
                <strong>
                  {locale === 'zh' ? '峰值' : 'peak'} {cadenceMax}
                </strong>
              </div>

              <svg
                className="sparkline-svg"
                viewBox="0 0 560 220"
                preserveAspectRatio="none"
                role="img"
                aria-label={locale === 'zh' ? '节奏折线' : 'cadence sparkline'}
              >
                {[0, 1, 2, 3].map((index) => {
                  const y = 18 + index * 46
                  return (
                    <line
                      key={y}
                      x1="20"
                      y1={y}
                      x2="540"
                      y2={y}
                      className="sparkline-grid"
                    />
                  )
                })}

                <polyline points={alertPolyline} className="sparkline-path tone-alert" />
                <polyline
                  points={suggestionPolyline}
                  className="sparkline-path tone-suggestion"
                />

                {snapshot.cadence.alerts.map((value, index) => {
                  const x =
                    snapshot.cadence.alerts.length > 1
                      ? 20 + ((560 - 40) / (snapshot.cadence.alerts.length - 1)) * index
                      : 280
                  const y = 12 + (220 - 36) - (value / cadenceMax) * (220 - 36)
                  return (
                    <rect
                      key={`a-${snapshot.cadence.labels[index]}`}
                      x={x - 3.5}
                      y={y - 3.5}
                      width="7"
                      height="7"
                      className="sparkline-point tone-alert"
                    />
                  )
                })}

                {snapshot.cadence.suggestions.map((value, index) => {
                  const x =
                    snapshot.cadence.suggestions.length > 1
                      ? 20 + ((560 - 40) / (snapshot.cadence.suggestions.length - 1)) * index
                      : 280
                  const y = 12 + (220 - 36) - (value / cadenceMax) * (220 - 36)
                  return (
                    <circle
                      key={`s-${snapshot.cadence.labels[index]}`}
                      cx={x}
                      cy={y}
                      r="4"
                      className="sparkline-point tone-suggestion"
                    />
                  )
                })}
              </svg>

              <div className="sparkline-axis">
                {snapshot.cadence.labels.map((label) => (
                  <span key={label}>{label}</span>
                ))}
              </div>
            </div>
          ) : (
            <div className="chart-empty">
              <strong>{locale === 'zh' ? '节奏数据暂不可用' : 'Cadence data unavailable'}</strong>
              <p>
                {locale === 'zh'
                  ? '当前快照没有提供足够的告警 / 建议节奏序列，所以这里先明确显示空态。'
                  : 'The current snapshot does not carry enough alert/suggestion cadence samples, so this panel shows an explicit empty state.'}
              </p>
            </div>
          )}
        </article>

        <article className="chart-card chart-card-evidence">
          <div className="chart-meta">
            <strong>{t('Evidence attachment', '证据附着率')}</strong>
            <p>
              {t(
                'Topology, device, and change context rates on the current runtime path.',
                '当前运行路径上，拓扑、设备与变更上下文的挂载率。',
              )}
            </p>
          </div>

          {hasEvidenceCoverage ? (
            <div className="coverage-stack">
              {evidenceCoverage.map((row) => (
                <article key={row.label} className="coverage-row">
                  <div className="coverage-meta">
                    <strong>{row.label}</strong>
                    <span>{row.value}%</span>
                  </div>
                  <div className="coverage-bar" aria-hidden="true">
                    <span style={{ width: `${Math.max(6, row.value)}%` }} />
                  </div>
                  <p>{row.detail}</p>
                </article>
              ))}
            </div>
          ) : (
            <div className="chart-empty">
              <strong>
                {locale === 'zh' ? '证据覆盖暂不可用' : 'Evidence coverage unavailable'}
              </strong>
              <p>
                {locale === 'zh'
                  ? '当前事件没有足够的拓扑、设备或变化上下文。'
                  : 'The current incident does not carry enough topology, device, or change context.'}
              </p>
            </div>
          )}
        </article>

        <article className="chart-card chart-card-latency">
          <div className="chart-meta">
            <strong>{t('Transition latency', '转场时延')}</strong>
            <p>{summaryLine(selectedSuggestion.stageTelemetry, locale)}</p>
          </div>

          {latency.length > 0 ? (
            <div className="latency-stack">
              {latency.map((row) => (
                <article key={row.label} className="latency-row">
                  <div className="latency-meta">
                    <strong>{row.label}</strong>
                    <span>{formatPreciseDurationMs(row.durationMs)}</span>
                  </div>
                  <div className="latency-bar" aria-hidden="true">
                    <span style={{ width: `${(row.durationMs / latencyMax) * 100}%` }} />
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="chart-empty">
              <strong>{t('Latency telemetry unavailable', '时延遥测不可用')}</strong>
              <p>
                {t(
                  'This panel stays blank rather than inventing timings when the selected suggestion does not carry measured stage telemetry.',
                  '如果当前建议没有携带测得的阶段遥测，这个面板会保持空白，而不是伪造计时。',
                )}
              </p>
            </div>
          )}
        </article>

        <article className="chart-card">
          <div className="chart-meta">
            <strong>{locale === 'zh' ? '历史事件档案' : 'Historical incident dossier'}</strong>
            <p>
              {locale === 'zh'
                ? '把当前历史事件的时间窗、样本和动作规模直接摊开，避免只剩一条摘要。'
                : 'Expose the selected incident window, samples, and action scale directly instead of collapsing everything into one summary.'}
            </p>
          </div>

          <div className="reading-grid incident-envelope-grid">
            {incidentEnvelope.map((row) => (
              <article key={row.label} className="reading-card">
                <span>{row.label}</span>
                <strong>{row.value}</strong>
              </article>
            ))}
          </div>
        </article>

        <article className="chart-card">
          <div className="chart-meta">
            <strong>{locale === 'zh' ? '重复路径监视' : 'Repeated path watch'}</strong>
            <p>
              {locale === 'zh'
                ? '哪些路径最接近从单次告警升级成可聚合的重复模式。'
                : 'Which paths are closest to becoming a repeated pattern instead of a one-off alert.'}
            </p>
          </div>

          {hasClusterWatch ? (
            <div className="cluster-watch-stack">
              {clusterRows.map((item) => {
                const ratio = item.target > 0 ? (item.progress / item.target) * 100 : 0
                const isSelectedPath =
                  item.service === selectedSuggestion.context.service &&
                  item.device === selectedSuggestion.context.srcDeviceKey

                return (
                  <article
                    key={item.key}
                    className={`cluster-watch-row ${isSelectedPath ? 'is-selected' : ''}`}
                  >
                    <div className="cluster-watch-head">
                      <div>
                        <strong>{item.service}</strong>
                        <span>{item.device}</span>
                      </div>
                      <span>
                        {item.progress}/{item.target}
                      </span>
                    </div>
                    <div className="cluster-watch-bar" aria-hidden="true">
                      <span style={{ width: `${Math.max(8, ratio)}%` }} />
                    </div>
                    <p>{item.note}</p>
                  </article>
                )
              })}
            </div>
          ) : (
            <div className="chart-empty">
              <strong>
                {locale === 'zh' ? '重复路径监视暂不可用' : 'Repeated-path watch unavailable'}
              </strong>
              <p>
                {locale === 'zh'
                  ? '当前快照没有可供比较的重复路径统计。'
                  : 'The current snapshot does not carry repeated-path watch rows yet.'}
              </p>
            </div>
          )}
        </article>

        <article className="chart-card chart-card-span-2">
          <div className="chart-meta">
            <strong>{locale === 'zh' ? '事件流程树与关键读数' : 'Incident process tree and readings'}</strong>
            <p>
              {locale === 'zh'
                ? '把当前历史事件从信号进入、规则触发到建议产出完整摊开成流程树，再把关键读数直接并排显示。'
                : 'Lay out the selected historical incident from source signal to suggestion emission as a process tree, then keep the few fields that drive judgment visible.'}
            </p>
          </div>

          {processTrace.length > 0 ? (
            <div className="process-trace">
              {processTrace.map((segment, index) => (
                <div key={segment.id} className="process-trace-segment">
                  <article
                    className={`process-trace-card tone-${segment.tone} state-${segment.state}`}
                  >
                    <span>{segment.detail}</span>
                    <strong>{segment.title}</strong>
                    <p>{segment.value}</p>
                  </article>
                  {index < processTrace.length - 1 ? (
                    <div className="process-trace-connector" aria-hidden="true">
                      <span />
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="chart-empty chart-empty-inline">
              <strong>
                {locale === 'zh'
                  ? '当前事件还没有阶段轨迹'
                  : 'No stage trace is attached to this incident yet'}
              </strong>
              <p>
                {locale === 'zh'
                  ? '当历史事件缺少阶段遥测时，这里会明确显示空态，而不是整块留白。'
                  : 'When stage telemetry is missing, this panel stays explicit instead of collapsing into a blank field.'}
              </p>
            </div>
          )}

          <div className="reading-grid">
            <article className="reading-card">
              <span>{locale === 'zh' ? '服务' : 'service'}</span>
              <strong>{selectedSuggestion.context.service}</strong>
            </article>
            <article className="reading-card">
              <span>{locale === 'zh' ? '设备' : 'device'}</span>
              <strong>{deviceLabel}</strong>
            </article>
            <article className="reading-card">
              <span>{locale === 'zh' ? '作用域' : 'scope'}</span>
              <strong>{selectedSuggestion.scope}</strong>
            </article>
            <article className="reading-card">
              <span>{locale === 'zh' ? '置信度' : 'confidence'}</span>
              <strong>{selectedSuggestion.confidenceLabel}</strong>
            </article>
            <article className="reading-card">
              <span>{locale === 'zh' ? '近一小时相似告警' : 'recent similar / 1h'}</span>
              <strong>{numericFromValue(selectedSuggestion.context.recentSimilar1h)}</strong>
            </article>
            <article className="reading-card">
              <span>{locale === 'zh' ? '聚合门槛' : 'cluster gate'}</span>
              <strong>
                {selectedSuggestion.stageTelemetry?.find(
                  (item) => item.stageId === 'cluster-window',
                )?.value ??
                  (selectedSuggestion.context.clusterWindowSec > 0
                    ? `${selectedSuggestion.context.clusterSize}/${selectedSuggestion.context.clusterWindowSec}s`
                    : locale === 'zh'
                      ? '尚未达到聚合门槛'
                      : 'not yet cluster-legible')}
              </strong>
            </article>
          </div>
        </article>
      </div>
    </section>
  )
}
