import agentEnhancedFixtureJson from '../../fixtures/compare/agent-enhanced.json'
import ruleOnlyFixtureJson from '../../fixtures/compare/rule-only.json'
import type { CompareFixtureBranch, CompareHighlight } from '../types'

const ruleOnlyFixture = ruleOnlyFixtureJson as CompareFixtureBranch
const agentEnhancedFixture = agentEnhancedFixtureJson as CompareFixtureBranch

export const compareBranches = [
  ruleOnlyFixture,
  agentEnhancedFixture,
] satisfies CompareFixtureBranch[]

const [ruleOnlyBranch, agentEnhancedBranch] = compareBranches

function formatDelta(nextValue: number, previousValue: number, suffix = '') {
  const delta = nextValue - previousValue
  const sign = delta > 0 ? '+' : ''
  return `${sign}${delta}${suffix}`
}

export const compareCurrentSlice = agentEnhancedBranch.currentSlice
export const compareWindow = agentEnhancedBranch.timeWindow

export const compareHighlights: CompareHighlight[] = [
  {
    label: 'suggestion coverage',
    ruleOnly: `${ruleOnlyBranch.metrics.suggestionEmissionCount}`,
    agentEnhanced: `${agentEnhancedBranch.metrics.suggestionEmissionCount}`,
    delta: formatDelta(
      agentEnhancedBranch.metrics.suggestionEmissionCount,
      ruleOnlyBranch.metrics.suggestionEmissionCount,
    ),
  },
  {
    label: 'closure count',
    ruleOnly: `${ruleOnlyBranch.metrics.remediationClosureCount}`,
    agentEnhanced: `${agentEnhancedBranch.metrics.remediationClosureCount}`,
    delta: formatDelta(
      agentEnhancedBranch.metrics.remediationClosureCount,
      ruleOnlyBranch.metrics.remediationClosureCount,
    ),
  },
  {
    label: 'median transition',
    ruleOnly: `${ruleOnlyBranch.metrics.medianTransitionMs} ms`,
    agentEnhanced: `${agentEnhancedBranch.metrics.medianTransitionMs} ms`,
    delta: formatDelta(
      agentEnhancedBranch.metrics.medianTransitionMs,
      ruleOnlyBranch.metrics.medianTransitionMs,
      ' ms',
    ),
  },
  {
    label: 'token cost',
    ruleOnly: `${ruleOnlyBranch.metrics.tokenCost}`,
    agentEnhanced: `${agentEnhancedBranch.metrics.tokenCost}`,
    delta: formatDelta(
      agentEnhancedBranch.metrics.tokenCost,
      ruleOnlyBranch.metrics.tokenCost,
    ),
  },
]
