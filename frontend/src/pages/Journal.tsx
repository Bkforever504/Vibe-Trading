import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { EvidenceReport } from "@/components/trading/EvidenceReport";
import { api, type TradingDashboard } from "@/lib/api";

export function Journal() {
  const [data, setData] = useState<TradingDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void api.getTradingDashboard().then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Journal unavailable")); }, []);
  if (!data) return <div className="p-8 text-sm text-muted-foreground">{error ?? <><RefreshCw className="mr-2 inline h-4 w-4 animate-spin" />Loading journal</>}</div>;
  const journal = data.evidence.journal;
  return (
    <div className="min-h-full p-3 sm:p-5">
      <header className="border-b border-border pb-4"><h1 className="text-xl font-bold">Decision Journal</h1><p className="mt-1 text-xs text-muted-foreground">Rejected ideas, durable lessons, and items requiring human review.</p></header>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <EvidenceReport title="Rejected trade intelligence" source={journal.rejected_intel} />
        <EvidenceReport title="Lesson ledger" source={journal.lesson_ledger} />
        <EvidenceReport title="Needs review" source={journal.needs_review} />
      </div>
    </div>
  );
}

