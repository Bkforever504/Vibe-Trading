import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TradingLearningProgress } from "@/lib/api";
import { LearningProgressPanel } from "../LearningProgressPanel";

const progress: TradingLearningProgress = {
  status: "learning_loop_measured_live_locked", as_of_date: "2026-08-26", grade_review_date: "2026-08-25", current_session_complete: false,
  opportunity_funnel: { stage_status: "measured_scorecard", market_moves: 5, discovered: 3, setup_confirmed: 1, execution_qualified: 0, discovery_recall_pct: 60, confirmation_recall_pct: 20, execution_recall_pct: 0, stage_definitions: {}, denominator_note: "Same denominator." },
  market_data_coverage: { futures_coverage: "unavailable", details: {}, interpretation: "Futures misses are unknown, not no-move outcomes." },
  broad_move_audit: { movers_audited: 100, source_discovery_recall_pct: 100, early_detection_count: 43, early_detection_pct: 43, actionable_early_count: 0, actionable_early_pct: 0, risk_gate_qualified_count: 0, late_detection_count: 57, top_blockers: [], denominator_note: "Broad." },
  frozen_rank_validation: { sessions: 3, ground_truth_count: 196, precision_at_10: 0, recall_at_10: 0, discovery_precision_at_10: 0.2, discovery_recall_at_10: 0.4, actionable_precision_at_10: 0, actionable_recall_at_10: 0, root_cause_coverage: 1, denominator_note: "Frozen." },
  graded_trade_outcomes: { unique_top_tier_setups: 2, resolved: 2, pending: 0, observed_wins: 2, observed_win_rate: 1, average_r: 1.3741, outcome_sample_with_r: 2, blocked_or_incomplete: 2 },
  calibration: { eligible_outcomes: 0, embargoed_or_skipped_outcomes: 605, qualified_probability_buckets: 0, minimum_outcomes: 100, minimum_independent_dates: 30, method: "chronological" },
  evidence_readiness: { overall_score: 6.8, status: "evidence_building", all_categories_verified_10: false, priority_gaps: [] },
  live_readiness: { ready: false, blockers: ["rolling_precision_at_10_not_positive", "fewer_than_30_independent_ranking_sessions"], message: "Inputs are not outcomes." },
  sources: {}, execution_enabled: false, can_submit_orders: false,
};

describe("LearningProgressPanel", () => {
  it("separates broad discovery from frozen ranking and live readiness", () => {
    render(<LearningProgressPanel progress={progress} />);
    expect(screen.getByText(/Market move → discovery → execution progress/i)).toBeInTheDocument();
    expect(screen.getByText(/moves actually happened/i)).toBeInTheDocument();
    expect(screen.getByText(/discovered · 60.0%/i)).toBeInTheDocument();
    expect(screen.getByText(/setup confirmed · 20.0%/i)).toBeInTheDocument();
    expect(screen.getByText(/Futures coverage: unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/unknown, not no-move/i)).toBeInTheDocument();
    expect(screen.getAllByText("0.0%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/2\/2/)).toBeInTheDocument();
    expect(screen.getByText(/live locked/i)).toBeInTheDocument();
    expect(screen.getByText(/3\/30 sessions/i)).toBeInTheDocument();
    expect(screen.getByText(/0\/100 eligible/i)).toBeInTheDocument();
    expect(screen.getByText(/Evidence readiness 6.8\/10/i)).toBeInTheDocument();
  });
});
