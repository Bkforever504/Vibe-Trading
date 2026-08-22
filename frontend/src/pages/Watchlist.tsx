import { useEffect, useMemo, useRef, useState } from "react";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { ColorType, createChart, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { PinOff, Plus, RefreshCw } from "lucide-react";
import { api, type TradingQuote } from "@/lib/api";
import { useDashboardPrefs } from "@/stores/dashboardPrefs";

interface WatchRow { symbol: string; quote?: TradingQuote; }

function Sparkline({ symbol }: { symbol: string }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    let chart: ReturnType<typeof createChart> | null = null;
    void api.getTradingBars(symbol, "5m", 40).then((response) => {
      if (!ref.current) return;
      chart = createChart(ref.current, { autoSize: true, height: 36, layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "transparent" }, grid: { vertLines: { visible: false }, horzLines: { visible: false } }, rightPriceScale: { visible: false }, timeScale: { visible: false } });
      const line = chart.addSeries(LineSeries, { color: "#f97316", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
      line.setData(response.bars.map((bar) => ({ time: bar.time as UTCTimestamp, value: bar.close })));
      chart.timeScale().fitContent();
    }).catch(() => undefined);
    return () => chart?.remove();
  }, [symbol]);
  return <div ref={ref} className="h-9 w-28" aria-label={`${symbol} sparkline`} />;
}

const column = createColumnHelper<WatchRow>();

export function Watchlist() {
  const symbols = useDashboardPrefs((state) => state.watchlist_symbols);
  const pinSymbol = useDashboardPrefs((state) => state.pinSymbol);
  const unpinSymbol = useDashboardPrefs((state) => state.unpinSymbol);
  const [quotes, setQuotes] = useState<Record<string, TradingQuote>>({});
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbols.length) return;
    let active = true;
    const refresh = () => {
      setLoading(true);
      void api.getTradingQuotes(symbols).then((response) => { if (active) setQuotes(response.quotes); }).catch(() => undefined).finally(() => { if (active) setLoading(false); });
    };
    refresh();
    const timer = window.setInterval(refresh, 5_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [symbols]);

  const rows = useMemo(() => symbols.map((symbol) => ({ symbol, quote: quotes[symbol] })), [quotes, symbols]);
  const columns = useMemo(() => [
    column.accessor("symbol", { header: "Symbol", cell: (info) => <span className="font-bold">{info.getValue()}</span> }),
    column.display({ id: "spark", header: "Trend", cell: ({ row }) => <Sparkline symbol={row.original.symbol} /> }),
    column.display({ id: "price", header: "Price", cell: ({ row }) => row.original.quote?.price?.toFixed(2) ?? "--" }),
    column.display({ id: "spread", header: "Bid / Ask", cell: ({ row }) => `${row.original.quote?.bid?.toFixed(2) ?? "--"} / ${row.original.quote?.ask?.toFixed(2) ?? "--"}` }),
    column.display({ id: "freshness", header: "Freshness", cell: ({ row }) => row.original.quote?.freshness ?? "missing" }),
    column.display({ id: "remove", header: "", cell: ({ row }) => <button type="button" aria-label={`Unpin ${row.original.symbol}`} onClick={() => unpinSymbol(row.original.symbol)} className="p-2 text-muted-foreground hover:text-danger"><PinOff className="h-4 w-4" /></button> }),
  ], [unpinSymbol]);
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="min-h-full p-3 sm:p-5">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
        <div><h1 className="text-xl font-bold">Watchlist</h1><p className="mt-1 text-xs text-muted-foreground">Alpaca IEX quotes every 5 seconds · read only</p></div>
        <form onSubmit={(event) => { event.preventDefault(); if (draft.trim()) pinSymbol(draft); setDraft(""); }} className="flex gap-2">
          <input value={draft} onChange={(event) => setDraft(event.target.value.toUpperCase())} placeholder="Add symbol" className="w-36 border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary" />
          <button type="submit" className="border border-primary px-3 py-2 text-sm text-primary"><Plus className="h-4 w-4" /></button>
        </form>
      </header>
      {loading && <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><RefreshCw className="h-3.5 w-3.5 animate-spin" />Refreshing quotes</div>}
      <div className="mt-4 overflow-x-auto border border-border bg-card">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id} className="px-3 py-2">{flexRender(header.column.columnDef.header, header.getContext())}</th>)}</tr>)}</thead>
          <tbody className="divide-y divide-border">{table.getRowModel().rows.map((row) => <tr key={row.id}>{row.getVisibleCells().map((cell) => <td key={cell.id} className="px-3 py-3 tabular-nums">{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody>
        </table>
        {!rows.length && <div className="p-8 text-center text-sm text-muted-foreground">Pin candidates from the cockpit or add a symbol above.</div>}
      </div>
    </div>
  );
}

