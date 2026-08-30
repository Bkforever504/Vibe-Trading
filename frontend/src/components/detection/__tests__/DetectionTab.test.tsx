import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DetectionTab } from "../DetectionTab";

const scorecard = {
  schema_version: 1,
  generated_at: "2026-08-22T12:00:00Z",
  sessions: 1,
  metrics: { recall_at_10: 0.75, precision_at_10_mean: 0.5, actionable_recall_at_10: 0.75, actionable_precision_at_10_mean: 0.5, discovery_recall_at_10: 1, discovery_precision_at_10_mean: 0.8, ground_truth_count: 4, root_cause_coverage: 1 },
  top_missed_moves: [],
  daily: [],
  pattern_coverage: {
    status: "placeholder_pending_kenny_signoff",
    metrics_qualified: false,
    pattern_metrics_qualified: false,
    source_labels: ["data/pattern_grader_log.jsonl", "move_universe_ground_truth"],
    totals: { ground_truth_labeled: 2, grader_detected: 3, true_positives: 1, coverage_delta: null },
    opportunity_coverage: { metrics_qualified: false, ground_truth_moves: 2, detected_events: 3, true_positives: 1, false_positives: 2, false_negatives: 1, precision: null, recall: null, coverage_delta: null },
    per_pattern: [],
    per_family: [{ family: "liquidity_delivery", ground_truth_labeled: 2, grader_detected: 3, true_positives: 1, false_positives: 2, false_negatives: 1, precision: null, recall: null, coverage_delta: null, outcome_quality: { resolved_outcomes: 9, wins: 5, observed_win_rate: 0.5556, average_r: 0.72 } }],
    cisd_hypothesis: { pattern_id: "ict_cisd_universal_model" as const, n_outcomes: 9, n_dates: 4, brier: 0.18, scored_outcomes: 9, status: "measured" },
    execution_enabled: false as const,
    can_submit_orders: false as const,
  },
  execution_enabled: false as const,
  can_submit_orders: false as const,
};

const promotion = {
  schema_version: 1,
  pattern_id: "ict_cisd_universal_model" as const,
  hypothesis_status: "unvalidated_pattern_hypothesis" as const,
  n_outcomes: 47,
  n_unique_dates: 18,
  wins: 29,
  win_rate_raw: 0.617,
  wilson_lower_bound_95: 0.478,
  n_scored_probabilities: 47,
  brier_score: 0.198,
  brier_baseline: 0.25,
  brier_skill: 0.208,
  gate_status: "pending" as const,
  gate_reasons_pending: ["n_outcomes < 100", "n_unique_dates < 30"],
  eligible_for_validated_promotion: false,
  last_updated_utc: "2026-08-22T21:30:00Z",
  source_labels: ["data/pattern_grader_outcomes.jsonl"],
  execution_enabled: false as const,
  can_submit_orders: false as const,
};

const governance = {
  tested_this_week: 3,
  rejected_this_week: 1,
  bonferroni_denominator: 5,
  effective_alpha: 0.01,
  status: "active_family",
  promotion_rule_version: "2026-08-23-v2",
  governance_status: "held_missing_evidence" as const,
  latest_candidate_decisions: 2,
  decision_counts: { promote: 0, hold: 1, reject: 1 },
  failed_rule_ids: [],
  unavailable_rule_ids: ["PROMO_LATENCY_WINDOW_V2"],
  controls: {
    multiple_testing_method: "benjamini_hochberg",
    fdr_alpha: 0.05,
    required_regimes: ["trend", "chop", "high_vol", "low_vol"],
    minimum_dates_per_regime: 8,
    latency_p90_maximum_fraction: 0.2,
    revalidation_maximum_age_days: 30,
    source_repair_requires_backfill_regrade: true,
    universe_version_required: true,
  },
  provenance: [],
  execution_enabled: false as const,
  can_submit_orders: false as const,
};

const mesEvidence = {
  schema_version: 1,
  provider: "mes_v2_evidence_status" as const,
  generated_at: "2026-08-23T20:00:00Z",
  live_feed: { provider: "databento" as const, dataset: "GLBX.MDP3" as const, status: "unavailable", reason: "license_required" },
  evidence_planes: { timely_discovery: "proxy_non_executable_not_promotion_eligible", promotion_measurement: "delayed_databento_mbo_regrade" },
  candidates: [{
    candidate_id: "mes-orb-0932-vix-v2",
    family_id: "mes-opening-breakout",
    qualified_outcomes: 1,
    excluded_outcomes: 2,
    distinct_dates: 1,
    targets: { resolved_outcomes: 100, distinct_dates: 30, dates_per_regime: 8 },
    regime_dates: { trend: 1, chop: 0, high_vol: 0, low_vol: 1 },
    latency: { observations: 1, p90_fraction_of_expected_window: 0.1, maximum_allowed: 0.2 },
    status: "collecting_or_blocked",
    blockers: ["natural_forward_sample_incomplete"],
    execution_enabled: false as const,
    can_submit_orders: false as const,
  }],
  execution_enabled: false as const,
  can_submit_orders: false as const,
};

const mnqEvidence = {
  schema_version: 1,
  provider: "mnq_smt_family_evidence_status" as const,
  generated_at: "2026-08-24T22:00:00Z",
  source_labels: ["data/shadow_outcomes.jsonl"],
  live_feed: { provider: "databento" as const, dataset: "GLBX.MDP3" as const, status: "unavailable", reason: "live_data_license_required" },
  evidence_planes: { timely_discovery: "proxy_non_executable_not_promotion_eligible", promotion_measurement: "delayed_databento_mbo_regrade" },
  approval_present: true,
  candidates: [{
    candidate_id: "mnq-cisd-only-v1",
    family_id: "mnq-smt-cisd-family",
    qualified_outcomes: 0,
    excluded_outcomes: 1,
    distinct_dates: 0,
    targets: { resolved_outcomes: 100, distinct_dates: 30, dates_per_regime: 8 },
    regime_dates: { trend: 0, chop: 0, high_vol: 0, low_vol: 0 },
    status: "collecting_or_blocked",
    blockers: ["natural_forward_sample_incomplete"],
    execution_enabled: false as const,
    can_submit_orders: false as const,
  }],
  execution_enabled: false as const,
  can_submit_orders: false as const,
};

describe("DetectionTab", () => {
  it("renders family precision, recall, delta, and CISD evidence", () => {
    render(<DetectionTab scorecard={scorecard} promotion={promotion} governance={governance} mesEvidence={mesEvidence} mnqEvidence={mnqEvidence} />);

    expect(screen.getByText("liquidity delivery")).toBeInTheDocument();
    expect(screen.getByText("Actionable recall@10")).toBeInTheDocument();
    expect(screen.getByText("Discovery recall@10")).toBeInTheDocument();
    expect(screen.getByText("Opportunity coverage")).toBeInTheDocument();
    expect(screen.getAllByText("Not measured").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("55.6%")).toBeInTheDocument();
    expect(screen.getByText("0.72R")).toBeInTheDocument();
    expect(screen.getByText(/n=9 · dates=4/)).toBeInTheDocument();
    expect(screen.getByText("Brier 0.180")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/move denominator unavailable/i);
    expect(screen.getByText("CISD Hypothesis Progress")).toBeInTheDocument();
    expect(screen.getByText("47 / 100")).toBeInTheDocument();
    expect(screen.getByText("18 / 30")).toBeInTheDocument();
    expect(screen.getByText("47.8%")).toBeInTheDocument();
    expect(screen.getByText("0.208")).toBeInTheDocument();
    expect(screen.getByText("unvalidated_pattern_hypothesis")).toBeInTheDocument();
    expect(screen.getByText("Promotion governance")).toBeInTheDocument();
    expect(screen.getByText("held missing evidence")).toBeInTheDocument();
    expect(screen.getByText("benjamini_hochberg")).toBeInTheDocument();
    expect(screen.getByText("8 dates each")).toBeInTheDocument();
    expect(screen.getByText(/PROMO_LATENCY_WINDOW_V2/)).toBeInTheDocument();
    expect(screen.getByText("MES v2 forward evidence")).toBeInTheDocument();
    expect(screen.getByText("1 / 100")).toBeInTheDocument();
    expect(screen.getAllByText("2").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/natural forward sample incomplete/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("MNQ SMT / CISD Databento evidence")).toBeInTheDocument();
    expect(screen.getByText("mnq-cisd-only-v1")).toBeInTheDocument();
    expect(screen.getByText(/Approval recorded/i)).toBeInTheDocument();
    expect(screen.getByText(/Live CME license absence/i)).toBeInTheDocument();
  });
});
