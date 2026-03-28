import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import type { RuntimeSnapshot, StageTelemetry, SuggestionRecord } from '../types'
import { formatPreciseDurationMs } from '../utils/time'

interface RuntimeVisualPanelsProps {
  snapshot: RuntimeSnapshot
  selectedSuggestion: SuggestionRecord
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
        smooth: 0.3,
        symbol: 'circle',
        symbolSize: 7,
        data: snapshot.cadence.alerts,
        lineStyle: { width: 2, color: '#ff8a45' },
        itemStyle: { color: '#ff8a45' },
        areaStyle: { color: 'rgba(255, 138, 69, 0.12)' },
      },
      {
        name: 'suggestions',
        type: 'line',
        smooth: 0.24,
        symbol: 'circle',
        symbolSize: 7,
        data: snapshot.cadence.suggestions,
        lineStyle: { width: 2, color: '#6fffa8' },
        itemStyle: { color: '#6fffa8' },
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
          borderRadius: [0, 2, 2, 0],
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
          borderRadius: [0, 2, 2, 0],
        },
      },
    ],
  }
}

function summaryLine(telemetry: StageTelemetry[] | undefined) {
  const measured = (telemetry ?? []).filter(
    (item) =>
      item.mode === 'duration' &&
      item.durationMs !== null &&
      item.durationMs !== undefined,
  )
  const totalMs = measured.reduce((sum, item) => sum + (item.durationMs ?? 0), 0)

  return measured.length > 0
    ? `Measured transition budget: ${formatPreciseDurationMs(totalMs)}`
    : 'Measured transition budget appears when live stage telemetry is present.'
}

export function RuntimeVisualPanels({
  snapshot,
  selectedSuggestion,
}: RuntimeVisualPanelsProps) {
  const latency = latencyRows(selectedSuggestion)

  return (
    <section className="section visual-strip">
      <div className="section-header">
        <div>
          <h2 className="section-title">Meaningful Runtime Visuals</h2>
          <span className="section-subtitle">
            Curves and bars are only kept when they answer throughput, evidence quality,
            or transition cost for the active incident slice.
          </span>
        </div>
        <span className="section-kicker">signal density with purpose</span>
      </div>

      <div className="signal-visual-grid">
        <article className="chart-card">
          <div className="chart-meta">
            <strong>Cadence parity</strong>
            <p>Whether suggestion emission stays close to alert arrival across the same window.</p>
          </div>
          <ReactECharts
            option={lineOption(snapshot)}
            notMerge
            lazyUpdate
            style={{ height: 212 }}
          />
        </article>

        <article className="chart-card">
          <div className="chart-meta">
            <strong>Evidence attachment</strong>
            <p>Topology, device, and change context rates on the current runtime path.</p>
          </div>
          <ReactECharts
            option={evidenceOption(snapshot)}
            notMerge
            lazyUpdate
            style={{ height: 212 }}
          />
        </article>

        <article className="chart-card">
          <div className="chart-meta">
            <strong>Transition latency</strong>
            <p>{summaryLine(selectedSuggestion.stageTelemetry)}</p>
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
              <strong>Latency telemetry unavailable</strong>
              <p>
                This panel stays blank rather than inventing timings when the selected
                suggestion does not carry measured stage telemetry.
              </p>
            </div>
          )}
        </article>
      </div>
    </section>
  )
}
