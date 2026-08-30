import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TradingTacticalPlan } from "@/lib/api";
import { TacticalPlanPanel } from "../TacticalPlanPanel";

const branch = (direction: string, trigger: number, stop: number): TradingTacticalPlan["bull_case"] => ({
  state: "WAIT", direction, setup: "range_break_retest", grade: "A-", decision_score: 86,
  trigger, entry_zone: { status: "source_defined", low: trigger, high: trigger },
  confirmation_required: "Wait for a completed 5m close, then a hold or retest.", retest_required: true,
  stop, t1: direction === "bullish" ? trigger + 1 : trigger - 1, t2: direction === "bullish" ? trigger + 2 : trigger - 2,
  entry_timing: {
    status: "awaiting_completed_bar", confirmation_timeframe: "5m", earliest_review_at: "2026-08-25T14:00:00Z", eta_minutes: 2,
    eta_definition: "Earliest legitimate recheck.", entry_trigger: trigger,
    entry_zone: { status: "exact_source_trigger", low: trigger, high: trigger, instruction: "Exact." }, invalidation: stop,
    target: direction === "bullish" ? trigger + 2 : trigger - 2, confirmation_required: "Completed 5m close and retest.", why: ["structure"], cancel_if: [],
    execution_enabled: false, can_submit_orders: false,
  },
  blockers: [], source: "live_opportunities", source_labels: ["completed_5m_bars"], execution_enabled: false, can_submit_orders: false,
});

describe("TacticalPlanPanel", () => {
  it("renders both branches, exact levels, ETA, and read-only authority", () => {
    const plan: TradingTacticalPlan = {
      schema_version: 1, generated_at: "2026-08-25T13:58:00Z", status: "WAIT_FOR_CONFIRMATION", symbol: "SPY",
      market_state: { classification: "gap_up", atm_iv: 0.139, expected_move_points: 6.72, freshness: "live", source_labels: ["opra_manual_reference"] },
      bull_case: branch("bullish", 769, 768), bear_case: branch("bearish", 768, 769),
      no_trade_zone: { status: "available", low: 768, high: 769, instruction: "Stand aside inside the triggers." },
      cross_checks: { level_consistency: "pass", conflicts: [], rule: "Conflicts fail closed." }, decision: "WAIT_FOR_CONFIRMATION",
      execution_enabled: false, can_submit_orders: false,
    };
    render(<TacticalPlanPanel plan={plan} />);

    expect(screen.getByText(/If price confirms up/i)).toBeInTheDocument();
    expect(screen.getByText(/If price confirms down/i)).toBeInTheDocument();
    expect(screen.getByText(/768.00–769.00/i)).toBeInTheDocument();
    expect(screen.getAllByText(/2.0 minutes to earliest recheck/i)).toHaveLength(2);
    expect(screen.getByText(/no order authority/i)).toBeInTheDocument();
  });

  it("shows a stand-aside contradiction warning", () => {
    const plan = {
      schema_version: 1, generated_at: "2026-08-25T13:58:00Z", status: "INVALID_SOURCE_CONFLICT", symbol: "SPY", market_state: { source_labels: [] },
      bull_case: branch("bullish", 779, 768), bear_case: branch("bearish", 768, 769),
      no_trade_zone: { status: "unavailable", low: null, high: null, instruction: "Invalid." },
      cross_checks: { level_consistency: "fail", conflicts: [{ reason: "same_source_trigger_claims_disagree" }], rule: "Conflicts fail closed." },
      decision: "STAND_ASIDE", execution_enabled: false, can_submit_orders: false,
    } satisfies TradingTacticalPlan;
    render(<TacticalPlanPanel plan={plan} />);

    expect(screen.getByText(/Contradictory or inverted source levels/i)).toBeInTheDocument();
    expect(screen.getAllByText(/stand aside/i).length).toBeGreaterThan(0);
  });

  it("labels stale expected-move context as blocked", () => {
    const plan = {
      schema_version: 1, generated_at: "2026-08-25T13:58:00Z", status: "WAIT_FOR_CONFIRMATION", symbol: "SPY",
      market_state: { classification: "bullish_lean", expected_move_points: null, atm_iv: null, freshness: "stale", decision_eligible: false, blocked_reason: "stale_or_unqualified_expected_move_source", source_labels: [] },
      bull_case: branch("bullish", 769, 768), bear_case: branch("bearish", 768, 769),
      no_trade_zone: { status: "available", low: 768, high: 769, instruction: "Stand aside inside the triggers." },
      cross_checks: { level_consistency: "pass", conflicts: [], rule: "Conflicts fail closed." }, decision: "WAIT_FOR_CONFIRMATION",
      execution_enabled: false, can_submit_orders: false,
    } satisfies TradingTacticalPlan;

    render(<TacticalPlanPanel plan={plan} />);

    expect(screen.getByText(/Expected-move context blocked: stale or unqualified expected move source/i)).toBeInTheDocument();
    expect(screen.getByText(/expected move --/i)).toBeInTheDocument();
  });
});
