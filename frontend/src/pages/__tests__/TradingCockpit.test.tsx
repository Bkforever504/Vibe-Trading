import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TradingCockpit } from '../TradingCockpit'

const mocks = vi.hoisted(() => ({
  getTradingDashboard: vi.fn(),
  getTradingDashboardSource: vi.fn(),
  getTradingQuotes: vi.fn(),
  getTradingBars: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  api: mocks,
}))

const dashboard = {
  schema_version: 11,
  generated_at: '2026-08-19T14:00:00Z',
  refresh_seconds: 15,
  mode: 'read_only_decision_support',
  authority: {
    execution_enabled: false,
    can_submit_orders: false,
    live_capital_enabled: false,
    paper_signal_count: 1,
    message: 'Paper consumers revalidate all gates.',
  },
  headline: {
    state: 'paper_setup_available',
    message: 'Best eligible paper setup',
    best_setup: {
      symbol: 'SPY',
      asset_class: 'equity_option',
      direction: 'long',
      setup: 'opening_range_retest',
      source: 'trade_signal_generator',
      status: 'ready',
      lifecycle: 'ready',
      lane: 'paper_ready',
      source_score: 92,
      routing_priority: 88,
      paper_consumable: true,
      entry: 772.1,
      stop: 770.5,
      target: 775,
      reward_risk: 1.8,
      instrument: 'defined_risk_option',
      order_style: 'limit',
      blockers: [],
      reasons: ['trend_confirmed'],
      evidence: { entry: 772.1 },
    },
  },
  ranking_policy: {
    mode: 'conditional_probability_first',
    qualified_candidate_count: 1,
    minimum_samples: 100,
    minimum_independent_dates: 30,
    requires_positive_brier_skill_vs_expanding_base_rate: true,
    uses_conservative_lower_bound: true,
    fallback: 'Decision quality fallback.',
    execution_enabled: false,
    can_submit_orders: false,
  },
  market: {
    classification: 'bullish_lean',
    force_score: 2.25,
    confidence: 72,
    risk_veto: { active: false },
    breadth_status: 'positive',
    pct_above_50dma: 68,
    sector_leadership: 'broad',
    leading_sectors: ['XLK', 'XLF'],
    high_impact_days_ahead: [],
    warnings: [],
  },
  account: { equity: 90000, buying_power: 180000 },
  portfolio: {
    open_trades: {},
    position_integrity: { status: 'ok' },
    risk_level: 'normal',
  },
  operations: {
    health: { ok: 12, stale: 0, missing: 0 },
    status: 'ok',
    signal_stack_summary: {},
    task_count: 12,
    tasks: [],
    audit_issue_count: 0,
    risk_blockers: [],
    stale_source_count: 0,
    stale_sources: [],
    failure_taxonomy_week: {},
    reconciliation_status: { last_run_at: null, diff_count_24h: 0, last_diff_at: null, status: 'unavailable' },
  },
  evidence: {
    shadow_consensus: {},
    shadow_audit: {},
    bottom_reversal: {},
    scanner_leadership: [],
    exit_accountability: [],
    retro: {},
    journal: {},
    social: {
      execution_enabled: false,
      can_submit_orders: false,
      verified_trader: { source: 'verified_trader', provider: null, mode: null, generated_at: null, age_seconds: null, freshness: 'missing', available: false, provenance_qualified: false, data: {}, execution_enabled: false, can_submit_orders: false },
      public_intake: { source: 'public_intake', provider: null, mode: null, generated_at: null, age_seconds: null, freshness: 'missing', available: false, provenance_qualified: false, data: {}, execution_enabled: false, can_submit_orders: false },
      trending_symbols: { source: 'trending_symbols', provider: null, mode: null, generated_at: null, age_seconds: null, freshness: 'missing', available: false, provenance_qualified: false, data: {}, execution_enabled: false, can_submit_orders: false },
    },
    catalysts_today: { source: 'catalysts', provider: null, mode: null, generated_at: null, age_seconds: null, freshness: 'missing', days: [], execution_enabled: false, can_submit_orders: false },
  },
  options_context: {
    status: 'unavailable',
    completeness: 'unavailable',
    surface: { source: 'options_surface', provider: null, mode: null, generated_at: null, age_seconds: null, freshness: 'missing', available: false, provenance_qualified: false, data: {}, execution_enabled: false, can_submit_orders: false },
    heatmap: { source: 'options_heatmap', provider: null, mode: null, generated_at: null, age_seconds: null, freshness: 'missing', available: false, provenance_qualified: false, data: {}, execution_enabled: false, can_submit_orders: false },
    vol_premium: { source: 'vol_premium', provider: null, mode: null, generated_at: null, age_seconds: null, freshness: 'missing', available: false, provenance_qualified: false, data: {}, execution_enabled: false, can_submit_orders: false },
    reason: 'No qualified context.',
    execution_enabled: false,
    can_submit_orders: false,
  },
  simple_signals: {
    definitions: {},
    counts: { CONFIRMED: 1, WAIT: 0, INVALID: 0 },
    generated_at: '2026-08-20T17:00:00Z',
    execution_enabled: false,
    can_submit_orders: false,
    signals: [{
      symbol: 'WMT',
      state: 'CONFIRMED',
      color: 'GREEN',
      direction: 'SHORT',
      grade: 'A-',
      score: 84,
      setup: 'opening_range_breakdown',
      trigger: 104.22,
      stop: 104.1773,
      target: 103.8,
      decisive_reason: 'breakdown_retest_reject',
      action: 'Revalidate the quote before any paper entry.',
      failed_quality_gates: [],
      score_definition: 'setup_quality_not_probability',
      execution_enabled: false,
      can_submit_orders: false,
    }],
  },
  command_card: {
    state: 'STAND_ASIDE',
    color: 'YELLOW',
    symbol: 'SPY',
    direction: 'bullish',
    setup: 'orb_break_retest_volume',
    grade: 'A-',
    decision_score: 88,
    trigger: 772,
    confirmation_required: 'Completed 5-minute close, hold/retest, fresh quote, and liquidity revalidation.',
    invalidation: 770.9,
    target: 774.2,
    instrument: 'defined_risk_option',
    no_trade_zone: {
      status: 'not_supplied',
      low: null,
      high: null,
      instruction: 'No source-defined two-sided no-trade zone is available; none was inferred.',
    },
    next_action: 'Wait for closed-bar confirmation.',
    evidence_fresh: true,
    evidence_age_seconds: 300,
    plan_id: 'spy-orb',
    execution_enabled: false,
    can_submit_orders: false,
  },
  dealer_regime: {
    status: 'unavailable',
    source_status: 'unavailable',
    net_gex_state: 'negative',
    spot_vs_flip: 'unavailable',
    quadrant: null,
    strategy_route: 'No gamma route. Use price action and the ordinary risk gates only.',
    reason: 'no provenance-qualified 0dte scans',
    execution_authority: false,
  },
  candidates: [],
  sources: [],
  warnings: [],
}

describe('TradingCockpit', () => {
  beforeEach(() => {
    mocks.getTradingDashboard.mockReset()
    mocks.getTradingDashboardSource.mockReset()
    mocks.getTradingQuotes.mockReset()
    mocks.getTradingBars.mockReset()
    mocks.getTradingDashboard.mockResolvedValue(dashboard)
  })

  it('renders the best eligible setup and preserves read-only authority', async () => {
    render(<TradingCockpit />)

    await waitFor(() => expect(mocks.getTradingDashboard).toHaveBeenCalled())
    expect(await screen.findByText(/SPY.*opening range retest/i)).toBeInTheDocument()
    expect(screen.getByText(/WMT.*SHORT/i)).toBeInTheDocument()
    expect(screen.getByText('CONFIRMED')).toBeInTheDocument()
    expect(screen.getByText(/Green is confirmation, not guaranteed profit/i)).toBeInTheDocument()
    expect(screen.getByText(/Primary instruction/i)).toBeInTheDocument()
    expect(screen.getByText(/No source-defined two-sided no-trade zone/i)).toBeInTheDocument()
    expect(screen.getByText(/Dealer gamma route/i)).toBeInTheDocument()
    expect(screen.getByText(/No gamma route/i)).toBeInTheDocument()
    expect(screen.getByText(/stand-aside blockers/i)).toBeInTheDocument()
    expect(screen.getByText(/Risk budget/i)).toBeInTheDocument()
    expect(screen.getByText(/Social evidence/i)).toBeInTheDocument()
    expect(screen.getAllByText(/read only/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/conditional probability first/i)).toBeInTheDocument()
    expect(screen.getByText(/1 probability-qualified now/i)).toBeInTheDocument()
  })
})
