import { Activity, Clock3, Crosshair } from "lucide-react";

import type { LiquidityLevelContext, MacroTimingContext, ParticipationContext } from "@/lib/api";
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
}: {
  liquidity?: LiquidityLevelContext;
  participation?: ParticipationContext;
  macro?: MacroTimingContext;
}) {
  if (!liquidity && !participation && !macro) return null;
  const levels = liquidity?.levels.slice(0, 6) ?? [];

  return (
    <div className="grid gap-px border-b border-border bg-border lg:grid-cols-3" aria-label="Structure context">
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
      </div>
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
    </div>
  );
}
