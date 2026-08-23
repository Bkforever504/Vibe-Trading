import { AlertTriangle, CheckCircle2, ScanSearch } from "lucide-react";
import type { TradingExecutionQuality } from "@/lib/api";

export function ExecutionQualityPanel({ quality }: { quality?: TradingExecutionQuality }) {
  const needsReview = quality?.status === "followup_required" || quality?.status === "missing" || !quality;
  return (
    <section className="border-y border-border py-4" aria-label="Execution quality">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <ScanSearch className="mt-0.5 h-4 w-4 text-primary" />
          <div>
            <h2 className="text-sm font-semibold">Execution quality</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {quality?.message ?? "Manual and broker execution evidence has not been observed."}
            </p>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-xs ${needsReview ? "text-amber-400" : "text-emerald-400"}`}>
          {needsReview ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
          {quality?.status?.replace(/_/g, " ") ?? "missing"}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
        <div><span className="font-medium">{quality?.manual_observations ?? 0}</span><div className="text-muted-foreground">manual observations</div></div>
        <div><span className="font-medium">{quality?.manual_followups ?? 0} manual follow-up{quality?.manual_followups === 1 ? "" : "s"}</span><div className="text-muted-foreground">open lifecycle reviews</div></div>
        <div><span className="font-medium">{quality?.broker_fills ?? 0}</span><div className="text-muted-foreground">broker fills observed</div></div>
        <div><span className="font-medium">{quality?.broker_linkage_issues ?? 0} linkage issue{quality?.broker_linkage_issues === 1 ? "" : "s"}</span><div className="text-muted-foreground">ambiguous or unmatched</div></div>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">Observation only · no order submission or execution authority.</p>
    </section>
  );
}
