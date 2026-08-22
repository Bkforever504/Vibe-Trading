import type { TradingOptionsContext } from "@/lib/api";

const LABELS = { surface: "Surface", heatmap: "Liquidation heatmap", vol_premium: "Vol premium" } as const;

export function OptionsContextPanel({ context }: { context: TradingOptionsContext }) {
  return (
    <section className="border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border p-3">
        <div><div className="font-semibold">Options context</div><div className="text-xs text-muted-foreground">Provenance-gated · context only</div></div>
        <span className="border border-border px-2 py-1 text-xs">{context.completeness}</span>
      </div>
      <div className="grid gap-px bg-border md:grid-cols-3">
        {(Object.keys(LABELS) as Array<keyof typeof LABELS>).map((key) => {
          const source = context[key];
          return (
            <div key={key} className="bg-card p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">{LABELS[key]}</div>
              <div className="mt-2 font-semibold">{source.provenance_qualified ? "Qualified" : "Unavailable"}</div>
              <div className="mt-1 text-xs text-muted-foreground">{source.source} · {source.freshness}</div>
              {source.provenance_qualified && <pre className="mt-3 max-h-40 overflow-auto bg-muted/30 p-2 text-[10px]">{JSON.stringify(source.data, null, 2)}</pre>}
            </div>
          );
        })}
      </div>
      <p className="border-t border-border p-3 text-xs text-muted-foreground">{context.reason}</p>
    </section>
  );
}

