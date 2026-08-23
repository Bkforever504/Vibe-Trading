import { AlertTriangle, CheckCircle2, Gauge } from "lucide-react";
import type { TradingSystemReadiness } from "@/lib/api";

function words(value: string): string {
  return value.replace(/_/g, " ");
}

export function SystemReadinessGate({ readiness }: { readiness?: TradingSystemReadiness }) {
  const ready = readiness?.ready_for_manual_review === true;
  const failed = readiness?.runtime.gates.filter((gate) => !gate.ready) ?? [];
  const build = readiness?.build.percent ?? 0;
  const runtime = readiness?.runtime.percent ?? 0;

  return (
    <section
      aria-label="System readiness"
      className={`border px-3 py-3 ${ready ? "border-emerald-500/35 bg-emerald-500/5" : "border-amber-500/40 bg-amber-500/5"}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <Gauge className={`mt-0.5 h-4 w-4 shrink-0 ${ready ? "text-emerald-400" : "text-amber-400"}`} />
          <div>
            <h2 className="text-sm font-semibold">System readiness</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Build completeness, live producer health, and statistical evidence are measured separately.
            </p>
            {failed.length > 0 ? (
              <p className="mt-1 text-xs text-amber-300">
                Runtime attention: {failed.map((gate) => words(gate.id)).join(", ")}
              </p>
            ) : null}
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-xs font-medium ${ready ? "text-emerald-400" : "text-amber-400"}`}>
          {ready ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {ready ? "Ready for manual review" : "Fail closed"}
        </div>
      </div>
      <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
        <div><span className="font-medium">{build.toFixed(1)}% installed</span><div className="text-muted-foreground">components and runners</div></div>
        <div><span className="font-medium">{runtime.toFixed(1)}% live</span><div className="text-muted-foreground">current evidence producers</div></div>
        <div><span className="font-medium">{readiness?.evidence.status === "qualified" ? "Probability-qualified" : "Collecting evidence"}</span><div className="text-muted-foreground">{readiness?.evidence.eligible_outcomes ?? 0} outcomes · {readiness?.evidence.independent_dates ?? 0} dates</div></div>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        {readiness?.evidence.message ?? "Readiness report missing."} Read only · never order authority.
      </p>
    </section>
  );
}
