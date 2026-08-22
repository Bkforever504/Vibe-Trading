import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getTradingQuotes: vi.fn(),
  getTradingBars: vi.fn(),
  setData: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { getTradingQuotes: mocks.getTradingQuotes, getTradingBars: mocks.getTradingBars } }));
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "Solid" },
  CandlestickSeries: {},
  LineSeries: {},
  createChart: () => ({
    addSeries: () => ({ setData: mocks.setData }),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: mocks.remove,
  }),
}));

import { BlockerChips } from "../BlockerChips";
import { CatalystStrip } from "../CatalystStrip";
import { ChartDrawer } from "../ChartDrawer";
import { EvidenceReport } from "../EvidenceReport";
import { OptionsContextPanel } from "../OptionsContextPanel";
import { PositionSizer } from "../PositionSizer";
import { SocialEvidencePanel } from "../SocialEvidencePanel";
import { TickerStrip } from "../TickerStrip";
import { LiveOpportunityPanel } from "../LiveOpportunityPanel";
import { useDashboardPrefs } from "@/stores/dashboardPrefs";

const source = (name: string, available = true) => ({
  source: name, provider: available ? "report" : null, mode: available ? "shadow" : null,
  generated_at: "2026-08-20T20:00:00Z", age_seconds: 10, freshness: available ? "live" as const : "missing" as const,
  available, provenance_qualified: available, data: available ? { summary: `${name} evidence` } : {},
  execution_enabled: false as const, can_submit_orders: false as const,
});

describe("trading primitives", () => {
  beforeEach(() => {
    mocks.getTradingQuotes.mockReset(); mocks.getTradingBars.mockReset(); mocks.setData.mockReset();
    useDashboardPrefs.setState({ risk_pct: 0.5, watchlist_symbols: [] });
  });

  it("renders blocker chips", () => {
    render(<BlockerChips blockers={["stale_quote", "risk_veto"]} />);
    expect(screen.getByText("stale quote")).toBeInTheDocument();
  });

  it("calculates position size from the persisted risk preference", () => {
    render(<PositionSizer equity={100_000} entry={100} stop={99} />);
    expect(screen.getByText("$500")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
  });

  it("polls and renders ticker quotes", async () => {
    mocks.getTradingQuotes.mockResolvedValue({ quotes: { SPY: { price: 101.25, stale: false } } });
    const onSelect = vi.fn();
    render(<TickerStrip slots={[{ symbol: "SPY", state: "wait", score: 80 }]} ageSeconds={12} onSelect={onSelect} />);
    expect(await screen.findByText("101.25")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText("Priority ticker strip"), { key: "1" });
    expect(onSelect).toHaveBeenCalledWith("SPY");
  });

  it("renders only sourced catalyst content", () => {
    render(<CatalystStrip catalysts={{ source: "catalysts", provider: "report", mode: "shadow", generated_at: null, age_seconds: 5, freshness: "live", days: [{ date: "2026-08-20", events: [{ title: "FOMC minutes" }], execution_enabled: false, can_submit_orders: false }], execution_enabled: false, can_submit_orders: false }} />);
    expect(screen.getByText(/FOMC minutes/)).toBeInTheDocument();
  });

  it("loads bars into the chart drawer", async () => {
    mocks.getTradingBars.mockResolvedValue({ bars: [{ time: 1, open: 1, high: 2, low: 1, close: 2, volume: 10 }] });
    render(<ChartDrawer symbol="SPY" open onClose={vi.fn()} />);
    await waitFor(() => expect(mocks.setData).toHaveBeenCalled());
    expect(screen.getByText(/Alpaca IEX/)).toBeInTheDocument();
  });

  it("shows provenance status for options and context-only social evidence", () => {
    render(<><OptionsContextPanel context={{ status: "context_available", completeness: "complete", surface: source("surface"), heatmap: source("heatmap"), vol_premium: source("vol_premium"), reason: "Qualified", execution_enabled: false, can_submit_orders: false }} /><SocialEvidencePanel social={{ verified_trader: source("verified_trader"), public_intake: source("public_intake"), trending_symbols: source("trending_symbols"), execution_enabled: false, can_submit_orders: false }} /></>);
    expect(screen.getAllByText("Qualified").length).toBeGreaterThan(0);
    expect(screen.getByText(/never an entry trigger/i)).toBeInTheDocument();
  });

  it("renders an evidence report with freshness and read-only authority", () => {
    render(<EvidenceReport title="Outcome" source={source("daily_outcome")} />);
    expect(screen.getByText("Outcome")).toBeInTheDocument();
    expect(screen.getByText(/no execution authority/i)).toBeInTheDocument();
  });

  it("changes the sizing preference from its input", () => {
    render(<PositionSizer equity={10_000} entry={10} stop={9} />);
    fireEvent.change(screen.getByLabelText("Risk percent"), { target: { value: "1" } });
    expect(useDashboardPrefs.getState().risk_pct).toBe(1);
  });

  it("renders streaming feed provenance and exact manual-review geometry", () => {
    render(<LiveOpportunityPanel connection="live" report={{
      schema_version: 1,
      generated_at: "2026-08-21T14:10:00Z",
      mode: "read_only_streaming_research",
      decision_state: "READY_TO_REVIEW",
      ready_count: 1,
      candidate_count: 1,
      setup_families: ["opening_range_break_retest"],
      market_structure_patterns: [{ id: "range_break_retest", complexity: "simple", role: "setup", confirmation: "break, retest, hold" }],
      market_structure_watchlist: [{
        symbol: "NVDA", decision: "READY_TO_REVIEW", grade: "A", score: 89,
        pattern_grade: {
          rubric_version: "pattern_grade_v1",
          components: { base_rate: 68, volume_rvol: 100, mtf_alignment: 100, regime_fit: 100, confluence: 100, reward_risk: 75 },
          weights: { base_rate: 0.25, volume_rvol: 0.15, mtf_alignment: 0.2, regime_fit: 0.15, confluence: 0.15, reward_risk: 0.1 },
          raw_score: 89.5,
          penalty_factors: { anti_pattern: 1, macro_window: 1, wide_spread: 1, stale_feed: 1 },
          penalty_multiplier: 1,
          final_score: 89.5,
          grade: "A",
          label: "ALL_OBSERVED_CONDITIONS_ALIGNED",
          all_observed_conditions_aligned: true,
          validation_status: "RESEARCH_PRIOR",
          evidence: { base_rate: "research_prior_not_local_probability" },
          warnings: ["Not a win probability."],
          execution_enabled: false,
          can_submit_orders: false,
        },
        best_setup: {
          pattern_id: "ict_cisd_universal_model", complexity: "advanced", direction: "bullish", confidence_score: 92, trigger_state: "confirmed", reason: "Ordered CISD sequence", trigger: 181.2, invalidation: 179.8, reference_level: 180.1, closed_bar_only: true,
          model_sequence: {
            model_version: "ict_cisd_sequence_v1", core_complete: true, chronology_valid: true, mapped_execution_timeframe: "5m", probability_status: "unvalidated_pattern_hypothesis", source_label: "independent_ohlc_rules_from_public_model_description", execution_enabled: false, can_submit_orders: false,
            stages: [
              { name: "htf_fvg_context", status: "complete" },
              { name: "third_candle_range", status: "complete" },
              { name: "liquidity_sweep", status: "complete" },
              { name: "ifvg", status: "complete" },
              { name: "cisd", status: "complete", body_close_required: true },
            ],
            bonus_confluences: { displacement: true, liquidity_sweep: true, smt: "unavailable_without_correlated_completed_bars", consequent_encroachment: { level: 180.75, status: "context_only_unvalidated" } },
          },
        },
        worst_setup: { pattern_id: "late_chase_exhaustion", complexity: "anti_pattern", direction: "bearish", confidence_score: 61, trigger_state: "confirmed", reason: "Path consumed", trigger: null, invalidation: null, reference_level: 180, closed_bar_only: true },
        entry_plan: { status: "actionable_manual_review", trigger: 181.2, entry_zone: { low: 181.1, high: 181.3 }, invalidation: 179.8, risk_per_share: 1.4, instruction: "Wait for completed bar." },
        exit_plan: { status: "defined", targets: [{ name: "target_1r", price: 182.6, reward_risk: 1 }, { name: "target_2r", price: 184, reward_risk: 2 }], time_stop_bars: 6, management: "Never widen invalidation." },
        hard_blockers: [], timeframe_alignment: { state: "aligned", frames: {}, closed_bar_only: true }, freshness: "live", source_labels: ["completed_5m_bars", "latest_quote"], execution_enabled: false, can_submit_orders: false,
        liquidity_level_context: {
          status: "available", levels: [
            { id: "pdh", label: "PDH", price: 182.4, side: "buy_side", source_label: "completed_prior_session_60m", freshness: "completed_period", historical_probability: { status: "unavailable_pending_local_outcomes", value: null }, execution_enabled: false, can_submit_orders: false },
            { id: "pdl", label: "PDL", price: 178.2, side: "sell_side", source_label: "completed_prior_session_60m", freshness: "completed_period", historical_probability: { status: "unavailable_pending_local_outcomes", value: null }, execution_enabled: false, can_submit_orders: false },
          ], active_sweeps: [{ level_id: "pdh", direction: "bearish", status: "confirmed_reclaim" }], probability_status: "unavailable_pending_local_outcomes", execution_enabled: false, can_submit_orders: false,
        },
        participation_context: { status: "buy_pressure_accelerating", direction: "bullish", method: "ohlcv_participation_curvature_proxy_v1", true_order_flow: false, score: 71, reason: "Completed-bar participation is accelerating.", probability: { status: "unavailable_pending_local_outcomes", value: null }, source_labels: ["completed_ohlcv_proxy", "not_true_order_flow"], execution_enabled: false, can_submit_orders: false },
        macro_context: { status: "context_only_unvalidated", active_window: "ny_am_0950_1010", active: true, label: "NY AM 09:50–10:10 ET", source_label: "public_ict_macro_schedule_context", score_effect: "none_until_validated", execution_enabled: false, can_submit_orders: false },
      }],
      feed: { provider: "alpaca", feed: "iex", transport: "websocket", entitlement: "configured_not_verified", label: "alpaca_iex_stock_stream", execution_enabled: false, can_submit_orders: false },
      candidates: [{ candidate_id: "one", symbol: "NVDA", asset_class: "equity", setup_family: "opening_range_break_retest", direction: "bullish", reason: "completed retest", decision_score: 88, grade: "A", state: "READY_TO_REVIEW", freshness: "live", entry: 181.2, invalidation: 179.8, targets: [{ name: "target_2r", price: 184 }], reward_risk_after_friction: 1.91, rvol_time_of_day: 2.1, source_labels: ["alpaca_iex_stream"], blockers: [], execution_enabled: false, can_submit_orders: false }],
      top_candidates: [],
      execution_enabled: false,
      can_submit_orders: false,
    }} onOpenChart={vi.fn()} />);

    expect(screen.getByText("Streaming opportunity engine")).toBeInTheDocument();
    expect(screen.getByText(/Alpaca IEX/)).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getAllByText(/181.20/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/179.80/).length).toBeGreaterThan(0);
    expect(screen.getByText(/1.91R/)).toBeInTheDocument();
    expect(screen.getByText(/Best structure/i)).toBeInTheDocument();
    expect(screen.getByText(/ict cisd universal model/i)).toBeInTheDocument();
    expect(screen.getAllByText(/CISD sequence/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/5 of 5 stages complete/i)).toBeInTheDocument();
    expect(screen.getByText(/unvalidated pattern hypothesis/i)).toBeInTheDocument();
    expect(screen.getByText(/CE 180.75/i)).toBeInTheDocument();
    expect(screen.getByText(/Worst look-alike/i)).toBeInTheDocument();
    expect(screen.getByText(/late chase exhaustion/i)).toBeInTheDocument();
    expect(screen.getByText(/6 bars/i)).toBeInTheDocument();
    expect(screen.getByText(/Grade A · 89.5/)).toBeInTheDocument();
    expect(screen.getByText(/all observed conditions aligned/i)).toBeInTheDocument();
    expect(screen.getByText(/One canonical score/i)).toBeInTheDocument();
    expect(screen.getByText(/Liquidity map/i)).toBeInTheDocument();
    expect(screen.getByText("PDH")).toBeInTheDocument();
    expect(screen.getByText("182.40")).toBeInTheDocument();
    expect(screen.getByText(/OHLCV proxy · not true order flow/i)).toBeInTheDocument();
    expect(screen.getByText(/NY AM 09:50/)).toBeInTheDocument();
    expect(screen.getByText(/probability unmeasured/i)).toBeInTheDocument();
    expect(screen.getByText(/manual review only/i)).toBeInTheDocument();
  });
});
