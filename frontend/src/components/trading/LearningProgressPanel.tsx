import { AlertTriangle, CheckCircle2, GraduationCap } from "lucide-react";

import type { TradingLearningProgress } from "@/lib/api";

function pct(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * (value <= 1 ? 100 : 1)).toFixed(1)}%` : "--";
}

function number(value: number | null | undefined, digits = 2): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function words(value: string): string {
  return value.replace(/_/g, " ");
}

export function LearningProgressPanel({ progress }: { progress?: TradingLearningProgress }) {
  const ready = progress?.live_readiness.ready === true;
  const move = progress?.broad_move_audit;
  const rank = progress?.frozen_rank_validation;
  const graded = progress?.graded_trade_outcomes;
  const calibration = progress?.calibration;

  return (
    <section className="border-y border-border py-4" aria-label="Grade to outcome learning progress">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <GraduationCap className="mt-0.5 h-4 w-4 text-primary" />
          <div>
            <h2 className="text-sm font-semibold">Grade → outcome → live-readiness progress</h2>
            <p className="mt-1 max-w-4xl text-xs text-muted-foreground">
              Compares what was ranked before the move with frozen outcomes. Broad mover discovery is shown separately from executable ranking quality.
            </p>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-xs ${ready ? "text-emerald-400" : "text-amber-400"}`}>
          {ready ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {ready ? "human live review qualified" : "live locked · evidence building"}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-4 xl:grid-cols-8">
        <div><span className="font-medium">{move?.movers_audited ?? 0}</span><div className="text-muted-foreground">moves audited</div></div>
        <div><span className="font-medium">{pct(move?.source_discovery_recall_pct)}</span><div className="text-muted-foreground">broad discovery</div></div>
        <div><span className="font-medium">{pct(move?.early_detection_pct)}</span><div className="text-muted-foreground">detected early</div></div>
        <div><span className="font-medium">{pct(move?.actionable_early_pct)}</span><div className="text-muted-foreground">actionable early</div></div>
        <div><span className="font-medium">{pct(rank?.precision_at_10)}</span><div className="text-muted-foreground">frozen precision@10</div></div>
        <div><span className="font-medium">{pct(rank?.recall_at_10)}</span><div className="text-muted-foreground">frozen recall@10</div></div>
        <div><span className="font-medium">{graded?.resolved ?? 0}/{graded?.unique_top_tier_setups ?? 0}</span><div className="text-muted-foreground">top-grade outcomes · {graded?.blocked_or_incomplete ?? 0} blocked</div></div>
        <div><span className="font-medium">{number(graded?.average_r)}R</span><div className="text-muted-foreground">observed average</div></div>
      </div>

      <div className="mt-3 grid gap-3 border-t border-border pt-3 text-xs md:grid-cols-3">
        <div>
          <div className="font-medium">Frozen rank evidence</div>
          <p className="mt-1 text-muted-foreground">{rank?.sessions ?? 0}/30 sessions · {rank?.ground_truth_count ?? 0} labeled moves</p>
        </div>
        <div>
          <div className="font-medium">Probability calibration</div>
          <p className="mt-1 text-muted-foreground">{calibration?.eligible_outcomes ?? 0}/{calibration?.minimum_outcomes ?? 100} eligible · {calibration?.qualified_probability_buckets ?? 0} qualified buckets · {calibration?.embargoed_or_skipped_outcomes ?? 0} embargoed/skipped</p>
        </div>
        <div>
          <div className="font-medium">Session alignment</div>
          <p className="mt-1 text-muted-foreground">Moves {progress?.as_of_date ?? "--"} · grades {progress?.grade_review_date ?? "--"} · {progress?.current_session_complete ? "session complete" : "session still open"}</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 text-xs">
        <span className="font-medium">Evidence readiness {number(progress?.evidence_readiness.overall_score, 1)}/10</span>
        <span className="text-muted-foreground">{progress?.evidence_readiness.status.replace(/_/g, " ") ?? "unavailable"}</span>
        <span className="text-muted-foreground">This is evidence maturity, not a probability of profit.</span>
      </div>

      {!ready && progress && (
        <div className="mt-3 rounded-sm border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs">
          <div className="font-medium text-amber-300">Current evidence blockers</div>
          <p className="mt-1 text-muted-foreground">{progress.live_readiness.blockers.slice(0, 6).map(words).join(" · ")}</p>
        </div>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground">{progress?.live_readiness.message ?? "Outcome evidence unavailable."} No order authority.</p>
    </section>
  );
}
