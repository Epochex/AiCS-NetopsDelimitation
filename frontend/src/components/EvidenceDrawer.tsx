import type { StrategyControl, SuggestionRecord } from '../types'

interface EvidenceDrawerProps {
  suggestion: SuggestionRecord
  controls: StrategyControl[]
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

        <section className="drawer-card">
          <h3>Runtime Context</h3>
          <ul className="evidence-list">
            <li>
              <span>suggestion_ts</span>
              <strong>{suggestion.suggestionTs}</strong>
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

        <section className="drawer-card">
          <h3>Topology Evidence</h3>
          <ul className="evidence-list">
            {Object.entries(suggestion.evidenceBundle.topology).map(([key, value]) => (
              <li key={key}>
                <span>{key}</span>
                <strong>
                  {Array.isArray(value) ? value.join(', ') || '-' : value || '-'}
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
                  {Array.isArray(value) ? value.join(', ') || '-' : value || '-'}
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
                    ? value.join(', ') || '-'
                    : value === null
                      ? '-'
                      : String(value)}
                </strong>
              </li>
            ))}
            {Object.entries(suggestion.evidenceBundle.historical).map(
              ([key, value]) => (
                <li key={`hist-${key}`}>
                  <span>{key}</span>
                  <strong>
                    {Array.isArray(value) ? value.join(', ') || '-' : value}
                  </strong>
                </li>
              ),
            )}
          </ul>
        </section>

        <section className="drawer-card">
          <h3>Hypotheses</h3>
          <ul className="prose-list">
            {suggestion.hypotheses.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>

        <section className="drawer-card">
          <h3>Recommended Actions</h3>
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
      </div>
    </aside>
  )
}
