import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DetectionTab } from "../DetectionTab";

const scorecard = {
  schema_version: 1,
  generated_at: "2026-08-22T12:00:00Z",
  sessions: 1,
  metrics: { recall_at_10: 0.75, precision_at_10_mean: 0.5, ground_truth_count: 4, root_cause_coverage: 1 },
  top_missed_moves: [],
  daily: [],
  pattern_coverage: {
    status: "placeholder_pending_kenny_signoff",
    metrics_qualified: false,
    source_labels: ["data/pattern_grader_log.jsonl", "move_universe_ground_truth"],
    totals: { ground_truth_labeled: 2, grader_detected: 3, true_positives: 1, coverage_delta: 1 },
    per_pattern: [],
    per_family: [{ family: "liquidity_delivery", ground_truth_labeled: 2, grader_detected: 3, true_positives: 1, false_positives: 2, false_negatives: 1, precision: 0.3333, recall: 0.5, coverage_delta: 1 }],
    cisd_hypothesis: { pattern_id: "ict_cisd_universal_model" as const, n_outcomes: 9, n_dates: 4, brier: 0.18, scored_outcomes: 9, status: "measured" },
    execution_enabled: false as const,
    can_submit_orders: false as const,
  },
  execution_enabled: false as const,
  can_submit_orders: false as const,
};

describe("DetectionTab", () => {
  it("renders family precision, recall, delta, and CISD evidence", () => {
    render(<DetectionTab scorecard={scorecard} />);

    expect(screen.getByText("liquidity delivery")).toBeInTheDocument();
    expect(screen.getByText("33.3%")).toBeInTheDocument();
    expect(screen.getAllByText("50.0%")).toHaveLength(2);
    expect(screen.getAllByText("+1")).toHaveLength(2);
    expect(screen.getByText(/n=9 · dates=4/)).toBeInTheDocument();
    expect(screen.getByText("Brier 0.180")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/placeholder denominator active/i);
  });
});
