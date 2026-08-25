import { Activity, Clock3, Crosshair, Layers3, Target } from "lucide-react";

import type { ClcEntryContext, LiquidityLevelContext, MacroTimingContext, NyBalanceRangeContext, ParticipationContext, SmtDivergenceContext, StratContext } from "@/lib/api";
import { cn } from "@/lib/utils";

function words(value: string): string {
  return value.split("_").join(" ");
}

function price(value: number): string {
  return value.toFixed(2);
}

export function StructureContextRail({
  liquidity,
  participation,
  macro,
  strat,
  balanceRange,
  clc,
  smt,
}: {
  liquidity?: LiquidityLevelContext;
  participation?: ParticipationContext;
  macro?: MacroTimingContext;
  strat?: StratContext;
  balanceRange?: NyBalanceRangeContext;
  clc?: ClcEntryContext;
  smt?: SmtDivergenceContext;
}) {
  if (!liquidity && !participation && !macro && !strat && !balanceRange && !clc && !smt) return null;
  const levels = liquidity?.levels.slice(0, 6) ?? [];
  const clcFrames = clc?.context.frames ?? {};

  return (
    <div className="grid gap-px border-b border-border bg-border md:grid-cols-2 xl:grid-cols-4" aria-label="Structure context">
      {clc ? (
        <div className="bg-card px-3 py-3 xl:col-span-2">
          <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-success">
            <Target className="h-3.5 w-3.5" />Context · Location · Confirmation
          </span>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <strong className={cn("mr-1 text-sm uppercase", clc.status === "manual_review_ready" ? "text-success" : clc.status === "blocked" ? "text-danger" : "text-warning")}>{words(clc.status)}</strong>
            {[clc.context, clc.location, clc.confirmation].map((step, index) => (
              <span key={index} className={cn("border px-2 py-1 text-[10px] uppercase", step.status === "complete" ? "border-success/30 text-success" : "border-warning/30 text-warning")}>
                {index === 0 ? "Context" : index === 1 ? "Location" : "Confirmation"} · {words(step.status)}
              </span>
            ))}
          </div>
          <p className="mt-2 text-xs font-medium uppercase">
            {(["60m", "4h", "1d"] as const).map((frame) => `${frame.toUpperCase()} ${clcFrames[frame] ?? "unavailable"}`).join(" · ")}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">Next: {clc.next_required}</p>
          <p className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">True absorption/delta unavailable without tick or MBO · no automatic execution</p>
        </div>
      ) : null}
      <div className="bg-card px-3 py-3">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-info">
          <Crosshair className="h-3.5 w-3.5" />Liquidity map
        </span>
        {levels.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {levels.map((level) => (
              <span key={level.id} className="border border-border px-2 py-1 text-xs">
                <strong>{level.label}</strong> {price(level.price)}
              </span>
            ))}
          </div>
        ) : <p className="mt-2 text-xs text-muted-foreground">Prior-period levels unavailable.</p>}
        <p className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">
          {liquidity?.active_sweeps.length ? `${liquidity.active_sweeps.length} confirmed reclaim` : "No active reclaim"} · probability unmeasured
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {liquidity?.nearest_upside ? `Upside ${liquidity.nearest_upside.label} ${price(liquidity.nearest_upside.price)}` : "Upside target unavailable"}
          {liquidity?.nearest_downside ? ` · Downside ${liquidity.nearest_downside.label} ${price(liquidity.nearest_downside.price)}` : ""}
          {liquidity?.dealing_range ? ` · ${words(liquidity.dealing_range.location)}` : ""}
        </p>
      </div>
      {smt ? (
        <div className="bg-card px-3 py-3">
          <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-info">
            <Layers3 className="h-3.5 w-3.5" />Paired-index SMT proxy
          </span>
          <p className={cn("mt-2 text-sm font-bold", smt.direction === "bullish" ? "text-success" : smt.direction === "bearish" ? "text-danger" : "text-foreground")}>
            {smt.peer_symbol ? `${smt.peer_symbol} · ` : ""}{smt.direction} {words(smt.status)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">Completed 5m price divergence · not order flow · no score effect</p>
        </div>
      ) : null}
      <div className="bg-card px-3 py-3">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-warning">
          <Activity className="h-3.5 w-3.5" />Participation curvature
        </span>
        <p className={cn("mt-2 text-sm font-bold capitalize", participation?.direction === "bullish" ? "text-success" : participation?.direction === "bearish" ? "text-danger" : "text-foreground")}>{words(participation?.status ?? "unavailable")}</p>
        <p className="mt-1 text-xs text-muted-foreground">OHLCV proxy · not true order flow{participation?.score == null ? "" : ` · strength ${participation.score.toFixed(0)}`}</p>
      </div>
      <div className="bg-card px-3 py-3">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" />Timing context
        </span>
        <p className={cn("mt-2 text-sm font-bold", macro?.active ? "text-warning" : "text-foreground")}>{macro?.label ?? "Timing unavailable"}</p>
        <p className="mt-1 text-xs text-muted-foreground">Context only · no score effect until locally validated</p>
      </div>
      <div className="bg-card px-3 py-3">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-info">
          <Layers3 className="h-3.5 w-3.5" />STRAT context
        </span>
        <p className="mt-2 text-sm font-bold uppercase">
          {strat?.current_scenario ? `${strat.current_scenario} · ${strat.ftfc.state} FTFC` : "Unavailable"}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {strat?.ftfc.strict ? `${strat.ftfc.frame_count} completed frames aligned` : `Need 4 aligned completed frames · have ${strat?.ftfc.frame_count ?? 0}`}
          {strat?.magnitude.target == null ? "" : ` · ${strat.magnitude.target_label ?? "target"} ${price(strat.magnitude.target)}`}
        </p>
      </div>
      <div className="bg-card px-3 py-3">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-warning">
          <Target className="h-3.5 w-3.5" />8–9 AM range
        </span>
        <p className={cn("mt-2 text-sm font-bold", balanceRange?.cisd?.confirmed ? "text-success" : "text-foreground")}>{words(balanceRange?.status ?? "unavailable")}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {balanceRange?.range ? `${price(balanceRange.range.low)}–${price(balanceRange.range.high)}` : "Completed premarket bars unavailable"}
          {balanceRange?.target == null ? "" : ` · target ${price(balanceRange.target)}`}
          {" · claimed rate excluded"}
        </p>
      </div>
    </div>
  );
}
