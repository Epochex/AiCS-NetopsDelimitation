import type { StrategyControl, SuggestionRecord } from '../types'
import { pick, type UiLocale } from '../i18n'
import {
  formatEvidenceValue,
  formatMaybeTimestamp,
  timestampTooltip,
} from '../utils/time'

interface EvidenceDrawerProps {
  suggestion: SuggestionRecord
  controls: StrategyControl[]
  locale: UiLocale
}

function firstPresentValue(
  mapping: Record<string, string | string[]>,
  keys: string[],
) {
  for (const key of keys) {
    const value = mapping[key]
    if (Array.isArray(value) && value.length > 0) {
      return value.join(', ')
    }
    if (typeof value === 'string' && value) {
      return value
    }
  }

  return '-'
}

function attachedEvidenceKinds(suggestion: SuggestionRecord) {
  return (
    [
      Object.keys(suggestion.evidenceBundle.topology).length > 0 ? 'topology' : null,
      Object.keys(suggestion.evidenceBundle.device).length > 0 ? 'device' : null,
      Object.keys(suggestion.evidenceBundle.change).length > 0 ? 'change' : null,
      Object.keys(suggestion.evidenceBundle.historical).length > 0 ? 'historical' : null,
    ].filter((item): item is string => item !== null) || ['minimal']
  )
}

function whyItMatters(suggestion: SuggestionRecord, locale: UiLocale) {
  const attached = attachedEvidenceKinds(suggestion).join(' + ')
  const recentSimilar = suggestion.context.recentSimilar1h

  if (locale === 'zh') {
    return `${suggestion.context.srcDeviceKey} 上的 ${suggestion.context.service} 当前被视为 ${suggestion.scope}-scope 事件切片，并已附带 ${attached} 上下文${recentSimilar > 0 ? `，最近 1 小时内还有 ${recentSimilar} 条相似告警` : ''}。`
  }

  return `${suggestion.context.service} on ${suggestion.context.srcDeviceKey} is currently being treated as a ${suggestion.scope}-scope slice with ${attached} context attached${recentSimilar > 0 ? ` and ${recentSimilar} similar alert(s) in the last hour` : ''}.`
}

function primaryHypothesis(suggestion: SuggestionRecord, locale: 'en' | 'zh') {
  return (
    suggestion.hypotheses[0] ??
    (locale === 'zh'
      ? '当前没有单独的假设文本，先沿着已挂载证据继续检查。'
      : 'No standalone hypothesis is attached yet, so continue from the evidence already attached.')
  )
}

function leadingAction(suggestion: SuggestionRecord, locale: 'en' | 'zh') {
  return (
    suggestion.recommendedActions[0] ??
    (locale === 'zh'
      ? '先展开证据字段，再决定是否需要进一步人工处置。'
      : 'Open the evidence fields first, then decide whether manual action is needed.')
  )
}

function evidenceOverview(suggestion: SuggestionRecord, locale: 'en' | 'zh') {
  const attached = attachedEvidenceKinds(suggestion).join(' + ')
  return locale === 'zh'
    ? `${attached} 已挂载，cluster gate=${suggestion.context.clusterSize}/${suggestion.context.clusterWindowSec}s`
    : `${attached} attached, cluster gate=${suggestion.context.clusterSize}/${suggestion.context.clusterWindowSec}s`
}

function humanReadableTitle(suggestion: SuggestionRecord, locale: 'en' | 'zh') {
  const deviceName = suggestion.evidenceBundle.device.device_name
  const deviceLabel =
    typeof deviceName === 'string' && deviceName.trim().length > 0
      ? deviceName
      : suggestion.context.srcDeviceKey

  if (locale === 'zh') {
    return `${suggestion.context.service} 在 ${deviceLabel} 上出现重复 deny`
  }

  return `Repeated denies on ${suggestion.context.service} from ${deviceLabel}`
}

export function EvidenceDrawer({
  suggestion,
  controls,
  locale,
}: EvidenceDrawerProps) {
  const copy =
    locale === 'zh'
      ? {
          title: '当前建议 / 证据轨迹',
          overview: '打开就能看的摘要',
          problem: '当前问题',
          inference: '系统推断',
          why: '为什么值得看',
          actions: '建议动作',
          attached: '已挂载上下文',
          runtime: '运行上下文与原始字段',
          evidence: '拓扑、设备与变更证据',
          confidence: '假设、置信度与控制点',
          close: '关闭',
        }
      : {
          title: 'Selected suggestion / evidence trace',
          overview: 'At a glance',
          problem: 'Current problem',
          inference: 'System inference',
          why: 'Why this matters',
          actions: 'Recommended action',
          attached: 'Attached evidence',
          runtime: 'Runtime context and raw fields',
          evidence: 'Topology, device, and change evidence',
          confidence: 'Hypotheses, confidence, and control points',
          close: 'Close',
        }

  return (
    <aside className="drawer">
      <div className="drawer-scroll">
        <div className="drawer-header">
          <div className="section-kicker">
            {pick(locale, 'Selected suggestion / evidence trace', '当前建议 / 证据轨迹')}
          </div>
          <h2>{suggestion.summary}</h2>
          <p className="drawer-copy">
            {pick(
              locale,
              'Read service and src device from ',
              'service 与 src device 请优先从 ',
            )}
            <strong>context</strong>
            {pick(locale, ' or ', ' 或 ')}
            <strong>evidence_bundle.topology</strong>
            {pick(
              locale,
              ', not from a top-level suggestion field.',
              ' 读取，而不是依赖 suggestion 顶层字段。',
            )}
          </p>
          <div className="drawer-badges">
            <span className="badge">{suggestion.scope}-scope</span>
            <span className="badge">{suggestion.priority}</span>
            <span className="badge">{suggestion.confidenceLabel}</span>
            <span className="badge">{suggestion.context.provider}</span>
          </div>
        </div>

        <section className="drawer-card drawer-overview-card">
          <h3>{copy.overview}</h3>
          <div className="drawer-overview-grid">
            <article className="drawer-glance-card">
              <span>{copy.problem}</span>
              <strong>{humanReadableTitle(suggestion, locale)}</strong>
              <p>{whyItMatters(suggestion)}</p>
            </article>
            <article className="drawer-glance-card">
              <span>{copy.inference}</span>
              <strong>{primaryHypothesis(suggestion, locale)}</strong>
              <p>{suggestion.confidenceReason}</p>
            </article>
            <article className="drawer-glance-card">
              <span>{copy.actions}</span>
              <strong>{leadingAction(suggestion, locale)}</strong>
              <p>{evidenceOverview(suggestion, locale)}</p>
            </article>
            <article className="drawer-glance-card">
              <span>{copy.attached}</span>
              <strong>{attachedEvidenceKinds(suggestion).join(' + ')}</strong>
              <p>
                service={suggestion.context.service} · src_device_key=
                {suggestion.context.srcDeviceKey}
              </p>
            </article>
          </div>
        </section>

        <div className="drawer-summary-grid">
          <section className="drawer-card drawer-priority-card">
            <h3>{pick(locale, 'Why this matters', '为什么值得关注')}</h3>
            <p className="drawer-copy">{whyItMatters(suggestion, locale)}</p>
          </section>

          <section className="drawer-card drawer-priority-card">
            <h3>{pick(locale, 'Recommended action', '推荐动作')}</h3>
            <ul className="prose-list">
              {suggestion.recommendedActions.slice(0, 3).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <section className="drawer-card drawer-priority-card">
            <h3>{pick(locale, 'Attached evidence', '附带证据')}</h3>
            <ul className="evidence-list">
              <li>
                <span>service</span>
                <strong>{suggestion.context.service}</strong>
              </li>
              <li>
                <span>src_device_key</span>
                <strong>{suggestion.context.srcDeviceKey}</strong>
              </li>
              <li>
                <span>cluster gate</span>
                <strong>
                  {suggestion.context.clusterSize} /{' '}
                  {suggestion.context.clusterWindowSec}s
                </strong>
              </li>
              <li>
                <span>srcip</span>
                <strong>
                  {firstPresentValue(suggestion.evidenceBundle.topology, [
                    'srcip',
                    'src_ip',
                  ])}
                </strong>
              </li>
              <li>
                <span>dstip</span>
                <strong>
                  {firstPresentValue(suggestion.evidenceBundle.topology, [
                    'dstip',
                    'dst_ip',
                  ])}
                </strong>
              </li>
              <li>
                <span>device</span>
                <strong>
                  {firstPresentValue(suggestion.evidenceBundle.device, [
                    'device_name',
                    'devtype',
                    'srcmac',
                  ])}
                </strong>
              </li>
            </ul>
          </section>
        </div>

        <details className="drawer-disclosure">
          <summary>
            {pick(locale, 'Open runtime context and raw fields', '展开运行时上下文与原始字段')}
          </summary>
          <section className="drawer-card">
            <h3>{pick(locale, 'Runtime Context', '运行时上下文')}</h3>
            <ul className="evidence-list">
              <li>
                <span>suggestion_ts</span>
                <strong title={timestampTooltip(suggestion.suggestionTs)}>
                  {formatMaybeTimestamp(suggestion.suggestionTs)}
                </strong>
              </li>
              <li>
                <span>alert_id</span>
                <strong>{suggestion.alertId}</strong>
              </li>
              <li>
                <span>service</span>
                <strong>{suggestion.context.service}</strong>
              </li>
              <li>
                <span>src_device_key</span>
                <strong>{suggestion.context.srcDeviceKey}</strong>
              </li>
              <li>
                <span>cluster</span>
                <strong>
                  {suggestion.context.clusterSize} /{' '}
                  {suggestion.context.clusterWindowSec}s
                </strong>
              </li>
              <li>
                <span>recent_similar_1h</span>
                <strong>{suggestion.context.recentSimilar1h}</strong>
              </li>
            </ul>
          </section>
        </details>

        <details className="drawer-disclosure">
          <summary>
            {pick(
              locale,
              'Open topology, device, and change evidence',
              '展开拓扑、设备与变更证据',
            )}
          </summary>
          <section className="drawer-card">
            <h3>{pick(locale, 'Topology Evidence', '拓扑证据')}</h3>
            <ul className="evidence-list">
              {Object.entries(suggestion.evidenceBundle.topology).map(([key, value]) => (
                <li key={key}>
                  <span>{key}</span>
                  <strong>
                    {Array.isArray(value)
                      ? value.map((item) => formatEvidenceValue(item)).join(', ') || '-'
                      : formatEvidenceValue(value)}
                  </strong>
                </li>
              ))}
            </ul>
          </section>

          <section className="drawer-card">
            <h3>{pick(locale, 'Device Evidence', '设备证据')}</h3>
            <ul className="evidence-list">
              {Object.entries(suggestion.evidenceBundle.device).map(([key, value]) => (
                <li key={key}>
                  <span>{key}</span>
                  <strong>
                    {Array.isArray(value)
                      ? value.map((item) => formatEvidenceValue(item)).join(', ') || '-'
                      : formatEvidenceValue(value)}
                  </strong>
                </li>
              ))}
            </ul>
          </section>

          <section className="drawer-card">
            <h3>{pick(locale, 'Change / Historical Evidence', '变更 / 历史证据')}</h3>
            <ul className="evidence-list">
              {Object.entries(suggestion.evidenceBundle.change).map(([key, value]) => (
                <li key={`change-${key}`}>
                  <span>{key}</span>
                  <strong>
                    {Array.isArray(value)
                      ? value.map((item) => formatEvidenceValue(item)).join(', ') || '-'
                      : formatEvidenceValue(value)}
                  </strong>
                </li>
              ))}
              {Object.entries(suggestion.evidenceBundle.historical).map(
                ([key, value]) => (
                  <li key={`hist-${key}`}>
                    <span>{key}</span>
                    <strong>
                      {Array.isArray(value)
                        ? value.map((item) => formatEvidenceValue(item)).join(', ') || '-'
                        : formatEvidenceValue(value)}
                    </strong>
                  </li>
                ),
              )}
            </ul>
          </section>
        </details>

        <details className="drawer-disclosure">
          <summary>
            {pick(
              locale,
              'Open hypotheses, confidence, and control points',
              '展开假设、置信度与控制点',
            )}
          </summary>
          <section className="drawer-card">
            <h3>{pick(locale, 'Hypotheses', '假设')}</h3>
            <ul className="prose-list">
              {suggestion.hypotheses.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <section className="drawer-card">
            <h3>{pick(locale, 'All Recommended Actions', '全部推荐动作')}</h3>
            <ul className="prose-list">
              {suggestion.recommendedActions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <section className="drawer-card">
            <h3>{pick(locale, 'Confidence', '置信度')}</h3>
            <p className="drawer-copy">
              <strong>{suggestion.confidenceLabel}</strong> · {suggestion.confidence}
            </p>
            <p className="drawer-copy">{suggestion.confidenceReason}</p>
          </section>

          <section className="drawer-card">
            <h3>{pick(locale, 'Control Points', '控制点')}</h3>
            <div className="control-list">
              {controls.map((control) => (
                <article key={control.id} className="control-item">
                  <strong>{control.label}</strong>
                  <span>{control.detail}</span>
                  <span className="control-value">
                    {control.currentValue} · {control.source}
                  </span>
                </article>
              ))}
            </div>
          </section>
        </details>
      </div>
    </aside>
  )
}
