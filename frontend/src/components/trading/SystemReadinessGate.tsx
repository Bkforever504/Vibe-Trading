import { AlertTriangle, CheckCircle2, Gauge } from "lucide-react";
import type { TradingSystemReadiness } from "@/lib/api";

function words(value: string): string {
  return value.replace(/_/g, " ");
}

export function SystemReadinessGate({ readiness }: { readiness?: TradingSystemReadiness }) {
  const ready = readiness?.ready_for_equity_manual_review ?? readiness?.ready_for_manual_review === true;
  const failed = readiness?.runtime.gates.filter((gate) => !gate.ready) ?? [];
  const build = readiness?.build.percent ?? 0;
  const runtime = readiness?.runtime.percent ?? 0;
  const lanes = readiness?.lanes ? Object.values(readiness.lanes) : [];

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
              Equity scanning, options data, research evidence, and execution observation are independently fail-closed.
            </p>
            {failed.length > 0 ? (
              <p className="mt-1 text-xs text-amber-300">
                Blocked non-ready gates: {failed.map((gate) => words(gate.id)).join(", ")}
              </p>
            ) : null}
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-xs font-medium ${ready ? "text-emerald-400" : "text-amber-400"}`}>
          {ready ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {ready ? "Equity scanner ready" : "Equity scanner fail closed"}
        </div>
      </div>
      {lanes.length > 0 ? (
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
          {lanes.map((lane) => (
            <div key={lane.id} className={`border p-2 ${lane.ready ? "border-emerald-500/25" : "border-amber-500/25"}`}>
              <div className="font-semibold">{words(lane.id)}</div>
              <div className={lane.ready ? "text-emerald-400" : "text-amber-400"}>{lane.ready ? "Operational" : "Fail closed"}</div>
              <div className="mt-1 text-[10px] text-muted-foreground">{lane.message}</div>
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
        <div><span className="font-medium">{build.toFixed(1)}% installed</span><div className="text-muted-foreground">components and runners</div></div>
        <div><span className="font-medium">{runtime.toFixed(1)}% all producers</span><div className="text-muted-foreground">lane status above controls usability</div></div>
        <div><span className="font-medium">{readiness?.evidence.status === "qualified" ? "Probability-qualified" : "Collecting evidence"}</span><div className="text-muted-foreground">{readiness?.evidence.eligible_outcomes ?? 0} outcomes · {readiness?.evidence.independent_dates ?? 0} dates</div></div>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        {readiness?.evidence.message ?? "Readiness report missing."} Read only · never order authority.
      </p>
    </section>
  );
}
