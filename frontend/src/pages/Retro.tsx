import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { APlusReviewPanel } from "@/components/trading/APlusReviewPanel";
import { EvidenceReport } from "@/components/trading/EvidenceReport";
import { api, type TradingDashboard } from "@/lib/api";

export function Retro() {
  const [data, setData] = useState<TradingDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void api.getTradingDashboard().then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Retro unavailable")); }, []);
  if (!data) return <div className="p-8 text-sm text-muted-foreground">{error ?? <><RefreshCw className="mr-2 inline h-4 w-4 animate-spin" />Loading retro</>}</div>;
  const retro = data.evidence.retro;
  return (
    <div className="min-h-full p-3 sm:p-5">
      <header className="border-b border-border pb-4"><h1 className="text-xl font-bold">Daily Retro</h1><p className="mt-1 text-xs text-muted-foreground">Outcomes, closure, and missed-opportunity evidence—not hindsight permission to chase.</p></header>
      <section className="mt-4 border border-border bg-card p-4">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Research family-size control</div>
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          <div><div className="text-2xl font-bold">{data.research_governance?.tested_this_week ?? 0}</div><div className="text-xs text-muted-foreground">candidates frozen this week</div></div>
          <div><div className="text-2xl font-bold">{data.research_governance?.bonferroni_denominator ?? 0}</div><div className="text-xs text-muted-foreground">experiment-wide denominator</div></div>
          <div><div className="text-2xl font-bold">{data.research_governance?.effective_alpha == null ? "Unavailable" : data.research_governance.effective_alpha.toFixed(6)}</div><div className="text-xs text-muted-foreground">effective alpha = 0.05 / K</div></div>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">The denominator never decreases. No frozen candidates means no statistical promotion claim.</p>
      </section>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <EvidenceReport title="End-of-day summary" source={retro.daily_eod} />
        <EvidenceReport title="Outcome review" source={retro.daily_outcome} />
        <APlusReviewPanel source={retro.aplus_review} />
        <EvidenceReport title="Closed-trade postmortems · top 5" source={retro.closed_postmortem} limit={5} />
        <EvidenceReport title="Missed bangers" source={retro.missed_banger} limit={5} />
      </div>
    </div>
  );
}
