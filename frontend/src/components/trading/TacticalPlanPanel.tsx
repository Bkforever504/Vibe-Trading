import { AlertTriangle, ArrowDown, ArrowUp, Clock3, ShieldCheck } from "lucide-react";

import type { TradingTacticalBranch, TradingTacticalPlan } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BlockerChips } from "./BlockerChips";

function words(value: unknown): string {
  return String(value ?? "unavailable").replace(/_/g, " ");
}

function value(input: number | null | undefined): string {
  return input == null ? "--" : Number(input).toFixed(2);
}

function timeStop(value: Record<string, unknown> | null | undefined): string {
  if (!value) return "not defined";
  const minutes = Number(value.minutes);
  if (Number.isFinite(minutes)) return `${minutes} minutes`;
  const bars = Number(value.bars);
  const timeframe = String(value.timeframe ?? "bars");
  return Number.isFinite(bars) ? `${bars} ${timeframe}` : "not defined";
}

function Branch({ title, branch, bullish }: { title: string; branch: TradingTacticalBranch; bullish: boolean }) {
  const ready = branch.state === "READY_TO_REVIEW";
  return (
    <div className={cn("border-l-4 bg-card p-3", bullish ? "border-success" : "border-danger")}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className={cn("flex items-center gap-1.5 text-xs font-bold uppercase", bullish ? "text-success" : "text-danger")}>
            {bullish ? <ArrowUp className="h-4 w-4" /> : <ArrowDown className="h-4 w-4" />}{title}
          </div>
          <div className="mt-1 text-sm font-semibold">{branch.setup ? words(branch.setup) : "No qualified branch"}</div>
        </div>
        <span className={cn("border px-2 py-1 text-[10px] font-semibold uppercase", ready ? "border-success/30 text-success" : branch.state === "INVALID" ? "border-danger/30 text-danger" : "border-warning/30 text-warning")}>{words(branch.state)}</span>
      </div>
      <div className="mt-3 grid grid-cols-4 gap-px bg-border text-xs">
        <div className="bg-background p-2"><span className="block text-[9px] uppercase text-muted-foreground">Trigger</span><strong>{value(branch.trigger)}</strong></div>
        <div className="bg-background p-2"><span className="block text-[9px] uppercase text-muted-foreground">Stop</span><strong>{value(branch.stop)}</strong></div>
        <div className="bg-background p-2"><span className="block text-[9px] uppercase text-muted-foreground">T1</span><strong>{value(branch.t1)}</strong></div>
        <div className="bg-background p-2"><span className="block text-[9px] uppercase text-muted-foreground">T2</span><strong>{value(branch.t2)}</strong></div>
      </div>
      <p className="mt-3 text-xs"><strong>Confirm:</strong> <span className="text-muted-foreground">{branch.confirmation_required}</span></p>
      <p className="mt-2 flex items-center gap-1.5 text-xs"><Clock3 className="h-3.5 w-3.5 text-warning" /><strong>ETA:</strong> <span className="text-muted-foreground">{branch.entry_timing?.eta_minutes == null ? "not available" : `${branch.entry_timing.eta_minutes.toFixed(1)} minutes to earliest recheck`}</span></p>
      <p className="mt-2 text-xs"><strong>Why:</strong> <span className="text-muted-foreground">{branch.entry_timing?.why?.join(" · ") || `${words(branch.setup)} with source-defined risk and confirmation`}</span></p>
      <p className="mt-2 text-xs"><strong>Exit clock:</strong> <span className="text-muted-foreground">time stop {timeStop(branch.time_stop)}{branch.entry_timing?.cancel_if?.length ? ` · cancel if ${branch.entry_timing.cancel_if.join(" · ")}` : ""}</span></p>
      <p className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">Entry zone {value(branch.entry_zone.low)}–{value(branch.entry_zone.high)} · retest required · {branch.source_labels.join(" · ") || "source unavailable"}</p>
      {branch.blockers.length > 0 && <BlockerChips blockers={branch.blockers} />}
    </div>
  );
}

export function TacticalPlanPanel({ plan }: { plan?: TradingTacticalPlan }) {
  if (!plan) return null;
  const conflict = plan.cross_checks.level_consistency === "fail";
  return (
    <section className="border border-border bg-muted/20" aria-label="Two-sided tactical plan">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-3 py-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-primary" />Two-sided tactical plan · {plan.symbol ?? "no symbol"}</div>
          <p className="mt-1 text-xs text-muted-foreground">Let price reach a source level, confirm on a completed candle, then review the retest. No anticipation.</p>
        </div>
        <span className={cn("border px-2 py-1 text-xs font-semibold uppercase", conflict ? "border-danger/30 text-danger" : "border-warning/30 text-warning")}>{words(plan.decision)}</span>
      </div>
      {conflict && (
        <div className="flex items-start gap-2 border-b border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />Contradictory or inverted source levels detected. The entire plan is invalid and the dashboard must stand aside.
        </div>
      )}
      <div className="grid gap-3 p-3 lg:grid-cols-2">
        <Branch title="If price confirms up" branch={plan.bull_case} bullish />
        <Branch title="If price confirms down" branch={plan.bear_case} bullish={false} />
      </div>
      <div className="grid gap-3 border-t border-border px-3 py-3 text-xs md:grid-cols-[1.2fr_1fr]">
        <div><strong>No-trade zone:</strong> <span className="text-muted-foreground">{plan.no_trade_zone.status === "available" ? `${value(plan.no_trade_zone.low)}–${value(plan.no_trade_zone.high)}. ` : "Unavailable. "}{plan.no_trade_zone.instruction}</span></div>
        <div className="text-muted-foreground">
          Regime {words(plan.market_state.classification)} · expected move {value(plan.market_state.expected_move_points)} · ATM IV {plan.market_state.atm_iv == null ? "--" : `${(plan.market_state.atm_iv * 100).toFixed(1)}%`} · freshness {words(plan.market_state.freshness)}
          {plan.market_state.decision_eligible === false ? <span className="mt-1 block text-warning">Expected-move context blocked: {words(plan.market_state.blocked_reason)}</span> : null}
        </div>
      </div>
      <div className="border-t border-border px-3 py-2 text-[10px] uppercase tracking-wide text-muted-foreground">Read only · manual review · no order authority · expected move is context, not a target</div>
    </section>
  );
}
