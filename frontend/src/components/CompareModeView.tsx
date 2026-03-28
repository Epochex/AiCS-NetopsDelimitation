import { compareBranches, compareCurrentSlice, compareHighlights, compareWindow } from '../data/compareFixtures'
import { runtimeUiStoryCatalog } from '../data/runtimeUiStories'
import type { CompareFixtureBranch } from '../types'
import { formatMaybeTimestamp, timestampTooltip } from '../utils/time'

function metricRows(branch: CompareFixtureBranch) {
  return [
    ['alert count', `${branch.metrics.alertCount}`],
    ['cluster trigger', `${branch.metrics.clusterTriggerCount}`],
    ['suggestion emission', `${branch.metrics.suggestionEmissionCount}`],
    ['operator action', `${branch.metrics.operatorActionCount}`],
    ['remediation closure', `${branch.metrics.remediationClosureCount}`],
    ['median transition', `${branch.metrics.medianTransitionMs} ms`],
    ['token cost', `${branch.metrics.tokenCost.toLocaleString()}`],
    ['cpu proxy', `${branch.metrics.cpuProxyPct}%`],
  ]
}

export function CompareModeView() {
  return (
    <section className="page compare-page">
      <section className="section compare-hero">
        <div className="section-header">
          <div>
            <h2 className="section-title">Compare Mode</h2>
            <span className="section-subtitle">
              Same-window branch review for rule-only and agent-enhanced runtime paths.
            </span>
          </div>
          <span className="section-kicker">{compareWindow.label}</span>
        </div>

        <div className="compare-hero-grid">
          <article className="compare-current-slice">
            <p className="story-marker">current slice</p>
            <h3>{compareCurrentSlice.title}</h3>
            <p>{compareCurrentSlice.focus}</p>
            <div className="story-badges">
              <span className="signal-chip tone-alert">{compareCurrentSlice.ruleId}</span>
              <span className="signal-chip tone-suggestion">{compareCurrentSlice.service}</span>
              <span className="signal-chip tone-neutral">{compareCurrentSlice.device}</span>
            </div>
          </article>

          <article className="compare-highlights">
            <strong>Branch deltas</strong>
            <ul className="compare-highlight-list">
              {compareHighlights.map((item) => (
                <li key={item.label}>
                  <span>{item.label}</span>
                  <div>
                    <strong>{item.delta}</strong>
                    <small>
                      {item.ruleOnly} {'->'} {item.agentEnhanced}
                    </small>
                  </div>
                </li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <div>
            <h2 className="section-title">Compare Branches</h2>
            <span className="section-subtitle">
              Hold the current slice constant and let only the runtime path diverge.
            </span>
          </div>
          <span className="section-kicker">rule-only vs agent-enhanced</span>
        </div>

        <div className="compare-branch-grid">
          {compareBranches.map((branch) => (
            <article
              key={branch.id}
              className={`compare-branch-card branch-${branch.mode}`}
            >
              <div className="compare-branch-head">
                <div>
                  <span className="section-kicker">{branch.mode}</span>
                  <h3>{branch.label}</h3>
                </div>
                <span className="signal-chip tone-neutral">
                  {branch.controlBoundary.exportReadiness}
                </span>
              </div>

              <p className="compare-branch-summary">{branch.summary}</p>

              <dl className="compare-metric-grid">
                {metricRows(branch).map(([label, value]) => (
                  <div key={`${branch.id}-${label}`} className="compare-metric-card">
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>

              <ol className="timeline-list compare-timeline">
                {branch.timeline.map((step, index) => (
                  <li
                    key={`${branch.id}-${step.title}`}
                    className={`timeline-item ${index === branch.timeline.length - 1 ? 'is-active' : ''}`}
                  >
                    <span
                      className="timeline-stamp"
                      title={timestampTooltip(step.stamp)}
                    >
                      {formatMaybeTimestamp(step.stamp)}
                    </span>
                    <div className="timeline-body">
                      <h3>{step.title}</h3>
                      <p>{step.detail}</p>
                    </div>
                  </li>
                ))}
              </ol>

              <div className="compare-boundary-card">
                <strong>Control boundary</strong>
                <p>{branch.controlBoundary.detail}</p>
                <span>
                  {branch.controlBoundary.status} · {branch.controlBoundary.exportReadiness}
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>

      <div className="compare-bottom-grid">
        <section className="section">
          <div className="section-header">
            <div>
              <h2 className="section-title">Export Metrics</h2>
              <span className="section-subtitle">
                Replay and figure generation stay visible as first-class outputs.
              </span>
            </div>
            <span className="section-kicker">review / replay / paper</span>
          </div>
          <div className="compare-export-grid">
            {compareBranches.map((branch) => (
              <article key={`export-${branch.id}`} className="compare-export-card">
                <strong>{branch.label}</strong>
                <p>{branch.exportArtifacts.detail}</p>
                <span className="signal-chip tone-neutral">{branch.exportArtifacts.status}</span>
                <ul className="focus-list">
                  {branch.exportArtifacts.items.map((item) => (
                    <li key={`${branch.id}-${item}`}>{item}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section className="section">
          <div className="section-header">
            <div>
              <h2 className="section-title">State Stories</h2>
              <span className="section-subtitle">
                Component states are fixed before larger homepage iteration continues.
              </span>
            </div>
            <span className="section-kicker">state-constrained development</span>
          </div>
          <div className="compare-story-grid">
            {runtimeUiStoryCatalog.components.map((component) => (
              <article key={component.componentId} className="compare-story-card">
                <strong>{component.componentId}</strong>
                <p>{component.intent}</p>
                <ul className="focus-list">
                  {component.scenarios.map((scenario) => (
                    <li key={scenario.id}>
                      {scenario.label}: {scenario.why}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>
      </div>
    </section>
  )
}
