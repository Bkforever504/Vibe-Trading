import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getTradingDashboard: vi.fn(), getTradingQuotes: vi.fn(), getTradingBars: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: mocks }));
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "Solid" }, LineSeries: {},
  createChart: () => ({ addSeries: () => ({ setData: vi.fn() }), timeScale: () => ({ fitContent: vi.fn() }), remove: vi.fn() }),
}));

import { Journal } from "../Journal";
import { Retro } from "../Retro";
import { Watchlist } from "../Watchlist";
import { Detection } from "../Detection";
import { Calibration } from "../Calibration";
import { useDashboardPrefs } from "@/stores/dashboardPrefs";

const source = (name: string) => ({ source: name, provider: "report", mode: "shadow", generated_at: null, age_seconds: 1, freshness: "live", available: true, provenance_qualified: true, data: { result: name }, execution_enabled: false, can_submit_orders: false });
const aplusReview = { ...source("aplus_review"), data: { review_status: "attention_required", summary: { system_reviewed_setup_count: 1, current_distinct_setup_count: 1, carried_followup_count: 0, outcome_followup_count: 1, source_coverage_pct: 93.8, system_review_coverage_pct: 100 }, source_inventory: [{ source: "pattern_grader", status: "missing" }], items: [{ source: "intraday_radar", review_id: "nvda-1", symbol: "NVDA", grade: "A+", setup: "opening_range_breakout", outcome_review_status: "pending", verdict: "reviewed_outcome_pending", is_carry_forward: false }] } };
const dashboard = { evidence: { retro: { daily_eod: source("daily_eod"), daily_outcome: source("daily_outcome"), aplus_review: aplusReview, closed_postmortem: source("closed_postmortem"), missed_banger: source("missed_banger") }, journal: { rejected_intel: source("rejected_intel"), lesson_ledger: source("lesson_ledger"), needs_review: source("needs_review") } }, discovery: { scorecard_rolling: { metrics: { recall_at_10: 0.6, precision_at_10_mean: 0.4, ground_truth_count: 20, root_cause_coverage: 1 }, top_missed_moves: [{ move_id: "x", symbol: "NVDA", move_pct: 8, partition: "ranking_miss" }] } }, calibration: { eligible_outcomes: 120, buckets: [{ bucket_id: "break_retest|trend|A", setup_family: "break_retest", regime: "trend", grade: "A", probability: { value: 0.68, lower_bound: 0.57, sample_size: 110, independent_dates: 40, status: "local_forward_validated", label: "Locally forward-calibrated conditional probability", brier_skill_vs_expanding_base_rate: 0.08, ece: 0.04, mce: 0.08 }, calibration_status: "local_forward_validated", reliability_bins: [{ count: 20, mean_probability: 0.65, observed_rate: 0.7, gap: -0.05 }], execution_enabled: false, can_submit_orders: false }], execution_enabled: false, can_submit_orders: false } };

describe("dashboard pages", () => {
  beforeEach(() => {
    mocks.getTradingDashboard.mockResolvedValue(dashboard);
    mocks.getTradingQuotes.mockResolvedValue({ quotes: { SPY: { price: 500, bid: 499.9, ask: 500.1, freshness: "live" } } });
    mocks.getTradingBars.mockResolvedValue({ bars: [] });
    useDashboardPrefs.setState({ watchlist_symbols: ["SPY"] });
  });

  it("renders the watchlist quote grid", async () => {
    render(<Watchlist />);
    expect(await screen.findByText("500.00")).toBeInTheDocument();
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
  });

  it("renders retro evidence", async () => {
    render(<Retro />);
    expect(await screen.findByText("End-of-day summary")).toBeInTheDocument();
    expect(screen.getByText("Every A+ setup review")).toBeInTheDocument();
    expect(screen.getByText("93.8%")).toBeInTheDocument();
    expect(screen.getByText(/pattern_grader/)).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
  });

  it("renders journal evidence", async () => {
    render(<Journal />);
    expect(await screen.findByText("Rejected trade intelligence")).toBeInTheDocument();
  });

  it("renders the detection scorecard without implying profitability", async () => {
    render(<Detection />);
    expect(await screen.findByText("60.0%")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText(/separately from profitability/i)).toBeInTheDocument();
  });

  it("renders chronological calibration evidence", async () => {
    render(<Calibration />);
    expect(await screen.findByText("120")).toBeInTheDocument();
    expect(screen.getAllByText("68.0%")).toHaveLength(2);
    expect(screen.getByText(/do not unlock order authority/i)).toBeInTheDocument();
  });
});
