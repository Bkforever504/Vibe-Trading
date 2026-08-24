import { useEffect, useState } from "react";
import { RefreshCw, ScanSearch } from "lucide-react";
import { api, type TradingDashboard } from "@/lib/api";
import { DetectionTab } from "@/components/detection/DetectionTab";

export function Detection() {
  const [data, setData] = useState<TradingDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void api.getTradingDashboard().then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Detection unavailable")); }, []);
  if (!data) return <div className="p-8 text-sm text-muted-foreground">{error ?? <><RefreshCw className="mr-2 inline h-4 w-4 animate-spin" />Loading detection scorecard</>}</div>;
  const scorecard = data.discovery?.scorecard_rolling;
  return (
    <div className="min-h-full p-3 sm:p-5">
      <header className="border-b border-border pb-4">
        <h1 className="flex items-center gap-2 text-xl font-bold"><ScanSearch className="h-5 w-5" />Detection</h1>
        <p className="mt-1 text-xs text-muted-foreground">Did the radar find and rank the session’s causal liquid moves? Detection is measured separately from profitability.</p>
      </header>
      <DetectionTab scorecard={scorecard} promotion={data.discovery?.cisd_promotion_status} governance={data.research_governance} />
      <p className="mt-3 text-xs text-muted-foreground">Read-only accountability surface. execution_enabled=false · can_submit_orders=false</p>
    </div>
  );
}
