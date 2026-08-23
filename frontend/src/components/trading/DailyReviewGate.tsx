import { AlertTriangle, CheckCircle2, ClipboardCheck } from "lucide-react";
import type { TradingDailyReviewGate } from "@/lib/api";

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function coverage(value: number | null): string {
  return value == null || !Number.isFinite(value) ? "unknown" : `${value.toFixed(1)}% complete`;
}

export function DailyReviewGate({ gate }: { gate?: TradingDailyReviewGate }) {
  const complete = gate?.status === "complete" && gate.overall_review_coverage_pct === 100;
  const missing = !gate || gate.status === "missing";
  const failed = gate?.failed_sources ?? [];

  return (
    <section className={`border px-3 py-3 ${complete ? "border-emerald-500/35 bg-emerald-500/5" : "border-amber-500/40 bg-amber-500/5"}`} aria-label="Daily A+ review gate">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <ClipboardCheck className={`mt-0.5 h-4 w-4 shrink-0 ${complete ? "text-emerald-400" : "text-amber-400"}`} />
          <div>
            <h2 className="text-sm font-semibold">Daily A+ review gate</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {missing ? "The daily review report is missing; setup coverage is unknown." : gate.message}
            </p>
            {failed.length > 0 ? (
              <p className="mt-1 text-xs text-amber-300">Missing or failed: {failed.map(label).join(", ")}</p>
            ) : null}
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-xs font-medium ${complete ? "text-emerald-400" : "text-amber-400"}`}>
          {complete ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {coverage(gate?.overall_review_coverage_pct ?? null)}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-muted-foreground">
        <span>{gate?.reviewed_setup_count ?? 0} setups reviewed</span>
        <span>{gate?.outcome_followup_count ?? 0} outcome follow-ups</span>
        <span>Read only · review quality, not entry authority</span>
      </div>
    </section>
  );
}
