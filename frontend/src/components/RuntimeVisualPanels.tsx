import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
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

function numericFromValue(value: unknown) {
  return typeof value === 'number' ? value : 0
}

function chartBaseGrid() {
  return {
    top: 18,
    right: 18,
    bottom: 28,
    left: 42,
    containLabel: true,
  }
}

function lineOption(snapshot: RuntimeSnapshot): EChartsOption {
  return {
    animationDuration: 700,
    grid: chartBaseGrid(),
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(6, 10, 14, 0.96)',
      borderColor: 'rgba(105, 249, 255, 0.28)',
      textStyle: { color: '#d7e4ef' },
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: '#91a5b7', fontSize: 10 },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: snapshot.cadence.labels,
      axisLabel: { color: '#91a5b7', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(157, 176, 196, 0.18)' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#91a5b7', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(157, 176, 196, 0.08)' } },
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

function evidenceOption(snapshot: RuntimeSnapshot): EChartsOption {
  return {
    animationDuration: 700,
    grid: {
      top: 12,
      right: 18,
      bottom: 18,
      left: 70,
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(6, 10, 14, 0.96)',
      borderColor: 'rgba(111, 255, 168, 0.24)',
      textStyle: { color: '#d7e4ef' },
    },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: {
        color: '#91a5b7',
        fontSize: 10,
        formatter: '{value}%',
      },
      splitLine: { lineStyle: { color: 'rgba(157, 176, 196, 0.08)' } },
    },
    yAxis: {
      type: 'category',
      data: snapshot.evidenceCoverage.labels,
      axisLabel: { color: '#91a5b7', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(157, 176, 196, 0.18)' } },
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

function latencyRows(selectedSuggestion: SuggestionRecord): LatencyRow[] {
  const stageLookup = new Map(
    (selectedSuggestion.stageTelemetry ?? []).map((item) => [item.stageId, item]),
  )
  const orderedStages: Array<[string, string]> = [
    ['correlator', 'edge -> alert'],
    ['cluster-window', 'cluster gate'],
    ['aiops-agent', 'alert -> suggestion'],
  ]

  return orderedStages
    .map(([stageId, label]) => {
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
        label,
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
    <section className="section visual-strip">
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
          <ReactECharts
            option={lineOption(snapshot)}
            notMerge
            lazyUpdate
            style={{ height: 212 }}
          />
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
          <ReactECharts
            option={evidenceOption(snapshot)}
            notMerge
            lazyUpdate
            style={{ height: 212 }}
          />
        </article>

        <article className="chart-card chart-card-latency">
          <div className="chart-meta">
            <strong>{t('Transition latency', '转场时延')}</strong>
            <p>{summaryLine(selectedSuggestion.stageTelemetry, locale)}</p>
          </div>
          {latency.length > 0 ? (
            <ReactECharts
              option={latencyOption(latency)}
              notMerge
              lazyUpdate
              style={{ height: 212 }}
            />
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
      </div>
    </section>
  )
}
