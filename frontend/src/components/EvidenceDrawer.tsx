import type { StrategyControl, SuggestionRecord } from '../types'
import {
  formatEvidenceValue,
  formatMaybeTimestamp,
  timestampTooltip,
} from '../utils/time'

interface EvidenceDrawerProps {
  suggestion: SuggestionRecord
  controls: StrategyControl[]
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

function whyItMatters(suggestion: SuggestionRecord) {
  const attached = attachedEvidenceKinds(suggestion).join(' + ')
  const recentSimilar = suggestion.context.recentSimilar1h

  return `${suggestion.context.service} on ${suggestion.context.srcDeviceKey} is currently being treated as a ${suggestion.scope}-scope slice with ${attached} context attached${recentSimilar > 0 ? ` and ${recentSimilar} similar alert(s) in the last hour` : ''}.`
}

export function EvidenceDrawer({
  suggestion,
  controls,
}: EvidenceDrawerProps) {
  return (
    <aside className="drawer">
      <div className="drawer-scroll">
        <div className="drawer-header">
          <div className="section-kicker">Selected suggestion / evidence trace</div>
          <h2>{suggestion.summary}</h2>
          <p className="drawer-copy">
            Read service and src device from <strong>context</strong> or{' '}
            <strong>evidence_bundle.topology</strong>, not from a top-level
            suggestion field.
          </p>
          <div className="drawer-badges">
            <span className="badge">{suggestion.scope}-scope</span>
            <span className="badge">{suggestion.priority}</span>
            <span className="badge">{suggestion.confidenceLabel}</span>
            <span className="badge">{suggestion.context.provider}</span>
          </div>
        </div>

        <div className="drawer-summary-grid">
          <section className="drawer-card drawer-priority-card">
            <h3>Why this matters</h3>
            <p className="drawer-copy">{whyItMatters(suggestion)}</p>
          </section>

          <section className="drawer-card drawer-priority-card">
            <h3>Recommended action</h3>
            <ul className="prose-list">
              {suggestion.recommendedActions.slice(0, 3).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <section className="drawer-card drawer-priority-card">
            <h3>Attached evidence</h3>
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
          <summary>Open runtime context and raw fields</summary>
          <section className="drawer-card">
            <h3>Runtime Context</h3>
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
          <summary>Open topology, device, and change evidence</summary>
          <section className="drawer-card">
            <h3>Topology Evidence</h3>
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
            <h3>Device Evidence</h3>
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
            <h3>Change / Historical Evidence</h3>
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
          <summary>Open hypotheses, confidence, and control points</summary>
          <section className="drawer-card">
            <h3>Hypotheses</h3>
            <ul className="prose-list">
              {suggestion.hypotheses.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <section className="drawer-card">
            <h3>All Recommended Actions</h3>
            <ul className="prose-list">
              {suggestion.recommendedActions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <section className="drawer-card">
            <h3>Confidence</h3>
            <p className="drawer-copy">
              <strong>{suggestion.confidenceLabel}</strong> · {suggestion.confidence}
            </p>
            <p className="drawer-copy">{suggestion.confidenceReason}</p>
          </section>

          <section className="drawer-card">
            <h3>Control Points</h3>
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
