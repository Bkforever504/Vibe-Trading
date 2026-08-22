import type { TradingEvidenceSource } from "@/lib/api";

function summaryRows(data: Record<string, unknown>, limit?: number): Array<[string, unknown]> {
  return Object.entries(data)
    .filter(([key]) => !["execution_enabled", "can_submit_orders"].includes(key))
    .slice(0, limit ?? 12);
}

function display(value: unknown): string {
  if (value == null) return "--";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

export function EvidenceReport({ title, source, limit }: { title: string; source: TradingEvidenceSource; limit?: number }) {
  return (
    <section className="min-w-0 border border-border bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-border p-3">
        <div><h2 className="font-semibold">{title}</h2><p className="mt-1 text-xs text-muted-foreground">{source.source} · {source.provider ?? "provider unavailable"}</p><p className="mt-1 text-[10px] text-muted-foreground">{source.filename ?? "file unavailable"}:{source.line_reference ?? "--"} · spec {source.spec_hash?.slice(0, 18) ?? "unavailable"}</p></div>
        <span className="border border-border px-2 py-1 text-xs">{source.freshness}</span>
      </div>
      {!source.available ? <div className="p-5 text-sm text-muted-foreground">Sourced report unavailable.</div> : (
        <dl className="divide-y divide-border">
          {summaryRows(source.data, limit).map(([key, value]) => (
            <div key={key} className="grid gap-1 px-3 py-2.5 text-xs sm:grid-cols-[160px_1fr]">
              <dt className="font-semibold text-muted-foreground">{key.replace(/_/g, " ")}</dt>
              <dd className="min-w-0 whitespace-pre-wrap break-words font-mono text-[11px]">{display(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="border-t border-border px-3 py-2 text-[10px] uppercase text-muted-foreground">Read only · no execution authority</div>
    </section>
  );
}
