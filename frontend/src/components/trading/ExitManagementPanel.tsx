import { AlertTriangle, CheckCircle2, Route, ShieldCheck } from "lucide-react";

import type { TradingExitManagement } from "@/lib/api";

function value(value: number | null | undefined, suffix = ""): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}${suffix}` : "--";
}

function dollars(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US", { style: "currency", currency: "USD" })
    : "--";
}

function label(value: string | null | undefined): string {
  return String(value ?? "unavailable").replace(/_/g, " ");
}

export function ExitManagementPanel({ management }: { management?: TradingExitManagement }) {
  const flat = management?.trail_state === "FLAT";
  const reviewReady = management?.policy.evidence_qualified_for_human_review === true;
  const bestMetrics = management?.policy.best_challenger_metrics ?? {};
  const avgReturn = typeof bestMetrics.avg_return_pct === "number" ? bestMetrics.avg_return_pct : null;
  const profitFactor = typeof bestMetrics.profit_factor === "number" ? bestMetrics.profit_factor : null;

  return (
    <section className="border-y border-border py-4" aria-label="Exit management">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <Route className="mt-0.5 h-4 w-4 text-primary" />
          <div>
            <h2 className="text-sm font-semibold">Exit management</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {management?.economics.message ?? "Exit telemetry has not been published."}
            </p>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-xs ${flat ? "text-emerald-400" : "text-amber-400"}`}>
          {flat ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {label(management?.trail_state)}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
        <div><span className="font-medium">{management?.open_positions ?? 0}</span><div className="text-muted-foreground">open positions</div></div>
        <div><span className="font-medium">{dollars(management?.economics.economic_pnl)}</span><div className="text-muted-foreground">economic P&amp;L</div></div>
        <div><span className="font-medium">{management ? `${value(management.telemetry.coverage_pct, "%")}` : "--"}</span><div className="text-muted-foreground">observed path coverage</div></div>
        <div><span className="font-medium">{management?.telemetry.complete_observed_trades ?? 0}/{management?.telemetry.closed_trades ?? 0}</span><div className="text-muted-foreground">qualified observations</div></div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3 text-xs md:grid-cols-4">
        <div><span className="font-medium">{management?.outcome_rates.observed_closed_ticket_win_rate == null ? "--" : value(100 * management.outcome_rates.observed_closed_ticket_win_rate, "%")}</span><div className="text-muted-foreground">observed ticket wins (n={management?.outcome_rates.observed_closed_ticket_sample ?? 0})</div></div>
        <div><span className="font-medium">{management?.outcome_rates.economic_basket_win_rate == null ? "--" : value(100 * management.outcome_rates.economic_basket_win_rate, "%")}</span><div className="text-muted-foreground">economic basket wins</div></div>
        <div><span className="font-medium">{dollars(management?.basket_risk.aggregate_open_risk)}</span><div className="text-muted-foreground">aggregate open risk</div></div>
        <div><span className="font-medium">{management?.basket_risk.add_on_count ?? "--"}</span><div className="text-muted-foreground">open-position add-ons</div></div>
      </div>

      {!flat && (
        <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3 text-xs md:grid-cols-4">
          <div><span className="font-medium">{value(management?.trigger_price)}</span><div className="text-muted-foreground">trail trigger</div></div>
          <div><span className="font-medium">{value(management?.distance_to_trigger)}</span><div className="text-muted-foreground">distance to trigger</div></div>
          <div><span className="font-medium">{value(management?.trigger_eta_minutes, " min")}</span><div className="text-muted-foreground">estimated trigger time</div></div>
          <div><span className="font-medium">{value(management?.locked_r, "R")}</span><div className="text-muted-foreground">locked reward</div></div>
        </div>
      )}

      <div className={`mt-3 rounded-sm border px-3 py-2 text-xs ${reviewReady ? "border-emerald-500/40 bg-emerald-500/5" : "border-amber-500/40 bg-amber-500/5"}`}>
        <div className="flex items-center gap-2 font-medium">
          {reviewReady ? <ShieldCheck className="h-4 w-4 text-emerald-400" /> : <AlertTriangle className="h-4 w-4 text-amber-400" />}
          {reviewReady ? "Exit challenger qualifies for human promotion review — production still locked" : "Research improvement only — not production eligible"}
        </div>
        <p className="mt-1 text-muted-foreground">
          {management?.policy.best_challenger ? `${label(management.policy.best_challenger)}: average ${value(avgReturn, "%")}, PF ${value(profitFactor)}, relative delta ${value(management.policy.relative_improvement_pct_points, " pts")}. ` : "No qualified challenger report. "}
          Positive relative delta cannot override negative expectancy, PF ≤ 1, or an unqualified chronological holdout.
        </p>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span>✓ Hard stop required</span>
        <span>✓ Confirmation required</span>
        <span>✓ No adding to losers</span>
        <span>✓ No demo-to-live copying</span>
        <span>Daily loss lock: {label(management?.daily_locks.loss.status)}</span>
        <span>Daily profit lock: {label(management?.daily_locks.profit.status)}</span>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">Observation only · no order submission or execution authority.</p>
    </section>
  );
}
