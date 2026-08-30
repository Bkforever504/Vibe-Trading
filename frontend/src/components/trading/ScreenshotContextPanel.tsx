import { Activity, Layers3, TrendingUp } from "lucide-react";

import type { TradingHtfNarrative, TradingOptionsSignalMatrix, TradingSwingContinuation } from "@/lib/api";
import { cn } from "@/lib/utils";

function words(value: unknown): string { return String(value ?? "unavailable").replace(/_/g, " "); }
function price(value: unknown): string { const n = Number(value); return Number.isFinite(n) ? n.toFixed(2) : "--"; }

export function ScreenshotContextPanel({ symbol, htf, options, swing }: { symbol?: string | null; htf?: TradingHtfNarrative; options?: TradingOptionsSignalMatrix; swing?: TradingSwingContinuation }) {
  if (!htf && !options && !swing) return null;
  const htfItem = htf?.items?.find((row) => row.symbol === symbol) ?? (symbol ? undefined : htf?.items?.[0]);
  const swingRows = swing?.candidates?.slice(0, 5) ?? [];
  return (
    <section className="grid gap-px border border-border bg-border lg:grid-cols-3" aria-label="Expanded decision context">
      <div className="bg-card p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-info"><Layers3 className="h-4 w-4" />HTF narrative</div>
        <p className="mt-2 text-sm font-bold">{htfItem ? `${htfItem.symbol} · ${words(htfItem.primary_bias)}` : "Unavailable"}</p>
        <p className="mt-1 text-xs text-muted-foreground">Weekly {words(htfItem?.weekly_bias)} · daily {words(htfItem?.daily_bias)} · intraday {words(htfItem?.intraday_bias)}</p>
        <p className="mt-2 text-xs text-muted-foreground">Reassess above {price(htfItem?.nearest_upside?.price)} or below {price(htfItem?.nearest_downside?.price)}. Context only; no duplicate score credit.</p>
      </div>
      <div className="bg-card p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-warning"><Activity className="h-4 w-4" />Options signal matrix</div>
        <p className={cn("mt-2 text-sm font-bold", options?.decision?.startsWith("NO_TRADE") ? "text-danger" : "text-foreground")}>{words(options?.decision)}</p>
        <p className="mt-1 text-xs text-muted-foreground">GEX {words(options?.gex.state)} · DEX unavailable · net drift unavailable</p>
        <p className="mt-2 text-xs text-muted-foreground">Route {words(options?.volatility_route.selected_playbook)} · HTF {words(options?.htf_bias)}. Inferred GEX is not actual dealer inventory.</p>
        {options?.blockers?.length ? <p className="mt-2 text-xs text-danger">Blocked: {options.blockers.map(words).join(" · ")}</p> : null}
      </div>
      <div className="bg-card p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-success"><TrendingUp className="h-4 w-4" />EOD continuation challenger</div>
        <p className="mt-2 text-xs text-muted-foreground">Ignition → contraction → 8/21/50 alignment → volume breakout. Next-session shadow review only · freshness {words(swing?.source?.freshness)}.</p>
        <div className="mt-2 space-y-1.5">
          {swingRows.map((row) => <div key={row.symbol} className="flex justify-between gap-2 border-t border-border pt-1.5 text-xs"><strong>{row.symbol} · {words(row.state)}</strong><span className="tabular-nums text-muted-foreground">{row.grade ?? "--"} · {price(row.entry)} / {price(row.stop)} / {price(row.target_2r)}</span></div>)}
          {!swingRows.length && <p className="text-xs text-muted-foreground">No current shadow candidates.</p>}
        </div>
      </div>
    </section>
  );
}
