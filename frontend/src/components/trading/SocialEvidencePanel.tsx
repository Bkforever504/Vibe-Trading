import type { TradingSocialEvidence } from "@/lib/api";

export function SocialEvidencePanel({ social }: { social: TradingSocialEvidence }) {
  const rows = [social.verified_trader, social.public_intake, social.trending_symbols];
  return (
    <section className="border border-border bg-card">
      <div className="border-b border-border px-3 py-2.5"><div className="text-sm font-semibold">Social evidence</div><div className="text-xs text-muted-foreground">Context only · never an entry trigger</div></div>
      <div className="divide-y divide-border">
        {rows.map((source) => (
          <div key={source.source} className="flex items-center justify-between gap-3 px-3 py-2.5 text-xs">
            <span className="font-medium">{source.source.replace(/_/g, " ")}</span>
            <span className="text-muted-foreground">{source.available ? source.freshness : "unavailable"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

