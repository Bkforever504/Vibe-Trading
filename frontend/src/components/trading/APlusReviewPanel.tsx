import { AlertTriangle, CheckCircle2, Clock3 } from "lucide-react";
import type { TradingEvidenceSource } from "@/lib/api";

function record(value: unknown): Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function APlusReviewPanel({ source }: { source: TradingEvidenceSource }) {
  const report = source.data;
  const summary = record(report.summary);
  const items = Array.isArray(report.items) ? report.items.map(record) : [];
  const inventory = Array.isArray(report.source_inventory) ? report.source_inventory.map(record) : [];
  const failedSources = inventory.filter((item) => item.status !== "reviewed");
  const complete = report.review_status === "complete";

  return (
    <section className="min-w-0 border border-border bg-card xl:col-span-2">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border p-3">
        <div>
          <h2 className="font-semibold">Every A+ setup review</h2>
          <p className="mt-1 text-xs text-muted-foreground">Every top-tier observation is audited; unresolved outcomes carry forward daily.</p>
          <p className="mt-1 text-[10px] text-muted-foreground">{source.source} · {source.provider ?? "provider unavailable"} · {source.freshness}</p>
        </div>
        <span className={`flex items-center gap-1 border px-2 py-1 text-xs ${complete ? "border-emerald-500/40 text-emerald-400" : "border-amber-500/40 text-amber-400"}`}>
          {complete ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
          {complete ? "Review complete" : "Attention required"}
        </span>
      </div>

      {!source.available ? <div className="p-5 text-sm text-muted-foreground">Daily A+ review report unavailable.</div> : <>
        <div className="grid gap-px bg-border sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Reviewed", number(summary.system_reviewed_setup_count)],
            ["Today", number(summary.current_distinct_setup_count)],
            ["Carried", number(summary.carried_followup_count)],
            ["Pending outcomes", number(summary.outcome_followup_count)],
            ["Source coverage", `${number(summary.source_coverage_pct).toFixed(1)}%`],
            ["System coverage", `${number(summary.system_review_coverage_pct).toFixed(1)}%`],
          ].map(([label, value]) => (
            <div key={String(label)} className="bg-card p-3">
              <div className="text-lg font-bold tabular-nums">{value}</div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
            </div>
          ))}
        </div>

        {failedSources.length > 0 ? (
          <div className="border-t border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {failedSources.length} source{failedSources.length === 1 ? "" : "s"} need{failedSources.length === 1 ? "s" : ""} attention: {failedSources.map((item) => String(item.source ?? "unknown")).join(", ")}. Zero setups is not trusted until coverage is complete.
          </div>
        ) : null}

        <div className="divide-y divide-border">
          {items.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">No top-tier setup was enumerated for this review window.</div>
          ) : items.slice(0, 20).map((item, index) => (
            <div key={`${String(item.source)}-${String(item.review_id)}-${index}`} className="grid gap-2 px-3 py-2.5 text-xs sm:grid-cols-[80px_1fr_100px_160px] sm:items-center">
              <div className="font-bold">{String(item.symbol ?? "--")} <span className="text-emerald-400">{String(item.grade ?? "A+")}</span></div>
              <div><div className="font-medium">{String(item.setup ?? "Unspecified setup")}</div><div className="text-[10px] text-muted-foreground">{String(item.source ?? "unknown source")}</div></div>
              <div>{item.is_carry_forward ? <span className="flex items-center gap-1 text-amber-300"><Clock3 className="h-3 w-3" />Carried</span> : "Today"}</div>
              <div className="text-muted-foreground">{String(item.verdict ?? item.outcome_review_status ?? "reviewed")}</div>
            </div>
          ))}
        </div>
      </>}
      <div className="border-t border-border px-3 py-2 text-[10px] uppercase text-muted-foreground">Read only · A+ is setup quality, not guaranteed profitability</div>
    </section>
  );
}
