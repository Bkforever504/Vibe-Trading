import { useEffect, useMemo, useState } from "react";
import { Clock3 } from "lucide-react";
import { api, type TradingQuotesResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface TickerSlot {
  symbol: string;
  state?: string;
  score?: number | null;
}

function evidenceAge(seconds: number | null): string {
  if (seconds == null) return "age unavailable";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

export function TickerStrip({
  slots,
  ageSeconds,
  onSelect,
}: {
  slots: TickerSlot[];
  ageSeconds: number | null;
  onSelect?: (symbol: string) => void;
}) {
  const visible = useMemo(() => slots.filter((slot) => slot.symbol).slice(0, 5), [slots]);
  const [market, setMarket] = useState<TradingQuotesResponse | null>(null);

  useEffect(() => {
    if (!visible.length) return;
    let active = true;
    const refresh = () => {
      void api.getTradingQuotes(visible.map((slot) => slot.symbol))
        .then((response) => { if (active) setMarket(response); })
        .catch(() => undefined);
    };
    refresh();
    const timer = window.setInterval(refresh, 5_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [visible]);

  return (
    <section
      className="sticky top-0 z-20 flex min-h-11 items-stretch overflow-x-auto border-y border-border bg-background/95 backdrop-blur"
      aria-label="Priority ticker strip"
      tabIndex={0}
      onKeyDown={(event) => {
        const index = Number(event.key) - 1;
        if (index >= 0 && index < visible.length) {
          event.preventDefault();
          event.stopPropagation();
          onSelect?.(visible[index].symbol);
        }
      }}
    >
      <div className="flex shrink-0 items-center gap-1.5 border-r border-border px-3 text-[11px] text-muted-foreground">
        <Clock3 className="h-3.5 w-3.5" /> Evidence {evidenceAge(ageSeconds)}
      </div>
      {visible.map((slot, index) => {
        const quote = market?.quotes[slot.symbol];
        return (
          <button
            key={slot.symbol}
            type="button"
            onClick={() => onSelect?.(slot.symbol)}
            className="flex min-w-36 items-center justify-between gap-3 border-r border-border px-3 py-2 text-left hover:bg-muted/40"
            title={`Slot ${index + 1}: ${slot.symbol}`}
          >
            <span><span className="font-bold">{index + 1} · {slot.symbol}</span><span className="block text-[10px] text-muted-foreground">{slot.state?.replace(/_/g, " ") ?? "watch"}</span></span>
            <span className={cn("text-right text-xs tabular-nums", quote?.stale && "text-warning")}>
              <span className="block font-semibold">{quote?.price == null ? "--" : quote.price.toFixed(2)}</span>
              <span className="text-[10px] text-muted-foreground">{slot.score == null ? "--" : `${Math.round(slot.score)}/100`}</span>
            </span>
          </button>
        );
      })}
      {!visible.length && <div className="px-3 py-3 text-xs text-muted-foreground">No ranked symbols available.</div>}
    </section>
  );
}
