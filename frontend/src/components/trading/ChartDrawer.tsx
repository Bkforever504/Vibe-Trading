import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";
import { X } from "lucide-react";
import { api, type TradingBar } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ChartDrawer({ symbol, open, onClose }: { symbol: string | null; open: boolean; onClose: () => void }) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [timeframe, setTimeframe] = useState("5m");
  const [bars, setBars] = useState<TradingBar[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !symbol) return;
    setError(null);
    void api.getTradingBars(symbol, timeframe, timeframe === "1d" ? 120 : 200)
      .then((response) => setBars(response.bars))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Chart unavailable"));
  }, [open, symbol, timeframe]);

  useEffect(() => {
    if (!open || !hostRef.current) return;
    const chart = createChart(hostRef.current, {
      autoSize: true,
      height: 430,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#94a3b8" },
      grid: { vertLines: { color: "rgba(100,116,139,.12)" }, horzLines: { color: "rgba(100,116,139,.12)" } },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e", downColor: "#ef4444", borderVisible: false,
      wickUpColor: "#22c55e", wickDownColor: "#ef4444",
    });
    series.setData(bars.map((bar) => ({ ...bar, time: bar.time as UTCTimestamp })));
    chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [bars, open]);

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose, open]);

  return (
    <div className={cn("fixed inset-0 z-50", open ? "pointer-events-auto" : "pointer-events-none")} aria-hidden={!open}>
      <button type="button" aria-label="Close chart overlay" onClick={onClose} className={cn("absolute inset-0 bg-black/60 transition-opacity", open ? "opacity-100" : "opacity-0")} />
      <aside className={cn("absolute inset-y-0 right-0 w-[min(92vw,52rem)] border-l border-border bg-background shadow-2xl transition-transform", open ? "translate-x-0" : "translate-x-full")} aria-label={`${symbol ?? "Symbol"} chart`}>
        <div className="flex items-center justify-between border-b border-border p-4">
          <div><div className="text-lg font-bold">{symbol ?? "Chart"}</div><div className="text-xs text-muted-foreground">Alpaca IEX · read-only market context</div></div>
          <button type="button" onClick={onClose} className="border border-border p-2" aria-label="Close chart"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex gap-1 border-b border-border p-3">
          {["5m", "1d"].map((tf) => <button key={tf} type="button" onClick={() => setTimeframe(tf)} className={cn("px-3 py-1.5 text-xs font-semibold", timeframe === tf ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>{tf}</button>)}
        </div>
        {error && <div className="border-b border-danger/30 bg-danger/10 p-3 text-sm text-danger">{error}</div>}
        <div ref={hostRef} className="h-[430px] w-full" data-testid="chart-host" />
        <p className="border-t border-border p-4 text-xs text-muted-foreground">Charts support visual review only. Confirm freshness, liquidity, trigger, and invalidation before any paper decision.</p>
      </aside>
    </div>
  );
}

