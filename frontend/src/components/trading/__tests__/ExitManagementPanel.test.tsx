import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TradingExitManagement } from "@/lib/api";
import { ExitManagementPanel } from "../ExitManagementPanel";

function fixture(overrides: Partial<TradingExitManagement> = {}): TradingExitManagement {
  return {
    status: "flat", trail_state: "FLAT", open_positions: 0,
    trigger_price: null, distance_to_trigger: null, trigger_eta_minutes: null,
    locked_r: null, next_ratchet: null, invalidation: null, eta_status: "not_applicable_flat",
    economics: { status: "flat_reconciled", realized_pnl: 0, unrealized_pnl: 0, economic_pnl: 0, message: "No position is open." },
    telemetry: { complete_observed_trades: 4, closed_trades: 15, coverage_pct: 26.67, insufficient_data_count: 11, qualified: false },
    basket_risk: { oldest_underwater_minutes: 0, largest_open_loss: 0, aggregate_open_risk: 0, add_on_count: 0, status: "not_applicable_flat" },
    outcome_rates: { observed_closed_ticket_win_rate: 0, observed_closed_ticket_sample: 4, economic_basket_win_rate: null, economic_basket_sample: 0, status: "insufficient_reconciled_basket_outcomes" },
    daily_locks: { loss: { status: "not_exposed_by_status_report", threshold: null }, profit: { status: "not_configured_or_not_exposed", threshold: null } },
    policy: {
      best_challenger: "ratchet_runner_no_target",
      best_challenger_metrics: { avg_return_pct: -6.41, profit_factor: 0.691 },
      relative_improvement_pct_points: 0.34, raw_promotion_ready: true,
      absolute_economics_positive: false, chronological_holdout_qualified: false,
      evidence_qualified_for_human_review: false,
      production_eligible: false, blockers: ["challenger_average_return_not_positive"],
      structural_best_path: "structural_vwap_trail", structural_best_metrics: {}, structural_review_qualified: false,
      message: "Research only.",
    },
    sources: { quality: {} as TradingExitManagement["sources"]["quality"], policy: {} as TradingExitManagement["sources"]["policy"] },
    guardrails: { add_to_losers_allowed: false, hard_stop_required: true, hard_stop_status: "not_applicable_flat", confirmation_required: true, copy_demo_to_live_allowed: false },
    execution_enabled: false, can_submit_orders: false,
    ...overrides,
  };
}

describe("ExitManagementPanel", () => {
  it("shows a reconciled flat state and observed coverage", () => {
    render(<ExitManagementPanel management={fixture()} />);
    expect(screen.getByText(/FLAT/i)).toBeInTheDocument();
    expect(screen.getByText(/26.67%/i)).toBeInTheDocument();
    expect(screen.getByText(/4\/15/i)).toBeInTheDocument();
    expect(screen.getByText(/no order submission/i)).toBeInTheDocument();
  });

  it("rejects a relative improvement with negative absolute economics", () => {
    render(<ExitManagementPanel management={fixture()} />);
    expect(screen.getByText(/Research improvement only/i)).toBeInTheDocument();
    expect(screen.getByText(/average -6.41%, PF 0.69/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot override negative expectancy/i)).toBeInTheDocument();
  });

  it("fails closed when open-position trail telemetry is unavailable", () => {
    render(<ExitManagementPanel management={fixture({
      status: "active_unqualified", trail_state: "TELEMETRY_UNAVAILABLE", open_positions: 1,
      economics: { status: "partial_realized_only", realized_pnl: 10, unrealized_pnl: null, economic_pnl: null, message: "Open risk exists, but telemetry is unavailable." },
    })} />);
    expect(screen.getByText(/TELEMETRY UNAVAILABLE/i)).toBeInTheDocument();
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
  });
});
