import ReactEChartsCore from 'echarts-for-react/lib/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  LineChart,
  CanvasRenderer,
])

interface TrendChartProps {
  title: string
  labels: string[]
  series: Array<{
    name: string
    data: number[]
    color: string
  }>
  unit?: string
}

export function TrendChart({
  title,
  labels,
  series,
  unit = '',
}: TrendChartProps) {
  return (
    <ReactEChartsCore
      echarts={echarts}
      style={{ height: 180 }}
      option={{
        backgroundColor: 'transparent',
        title: {
          text: title,
          left: 12,
          top: 8,
          textStyle: {
            color: '#f2f7fb',
            fontFamily: 'IBM Plex Sans Condensed',
            fontSize: 12,
            fontWeight: 500,
            letterSpacing: 1.2,
          },
        },
        grid: { left: 38, right: 18, top: 46, bottom: 28 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: '#0b1118',
          borderColor: 'rgba(152, 181, 211, 0.24)',
          textStyle: { color: '#f2f7fb', fontFamily: 'IBM Plex Mono' },
          valueFormatter: (value: number) => `${value}${unit}`,
        },
        legend: {
          top: 10,
          right: 12,
          textStyle: { color: '#738699', fontFamily: 'IBM Plex Sans Condensed' },
        },
        xAxis: {
          type: 'category',
          data: labels,
          boundaryGap: false,
          axisLabel: { color: '#738699', fontFamily: 'IBM Plex Mono', fontSize: 11 },
          axisLine: { lineStyle: { color: 'rgba(152, 181, 211, 0.14)' } },
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: '#738699', fontFamily: 'IBM Plex Mono', fontSize: 11 },
          splitLine: { lineStyle: { color: 'rgba(152, 181, 211, 0.08)' } },
        },
        series: series.map((item) => ({
          name: item.name,
          type: 'line',
          smooth: 0.28,
          symbol: 'rect',
          symbolSize: 6,
          lineStyle: { width: 2, color: item.color },
          itemStyle: { color: item.color },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${item.color}55` },
                { offset: 1, color: `${item.color}02` },
              ],
            },
          },
          data: item.data,
        })),
      }}
    />
  )
}
