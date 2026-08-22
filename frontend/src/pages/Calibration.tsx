import { useEffect, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { api, type GradeCalibrationBucket, type TradingDashboard } from "@/lib/api";
import { ReliabilityDiagram } from "@/components/trading/ReliabilityDiagram";

function pct(value: number | null | undefined): string {
  return value == null ? "Not measured" : `${(value * 100).toFixed(1)}%`;
}

export function Calibration() {
  const [data, setData] = useState<TradingDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { void api.getTradingDashboard().then(setData).catch((caught) => setError(caught instanceof Error ? caught.message : "Calibration unavailable")); }, []);
  const buckets = data?.calibration?.buckets ?? [];
  const bucket: GradeCalibrationBucket | undefined = buckets.find((item) => item.bucket_id === selected) ?? buckets[0];
  if (!data) return <div className="p-8 text-sm text-muted-foreground">{error ?? <><RefreshCw className="mr-2 inline h-4 w-4 animate-spin" />Loading calibration evidence</>}</div>;
  return (
    <div className="min-h-full p-3 sm:p-5">
      <header className="border-b border-border pb-4">
        <h1 className="flex items-center gap-2 text-xl font-bold"><Activity className="h-5 w-5" />Calibration</h1>
        <p className="mt-1 text-xs text-muted-foreground">Does each grade’s stated conditional win rate match chronological out-of-sample outcomes? Percentages do not unlock order authority.</p>
      </header>
      <div className="mt-4 grid gap-px bg-border sm:grid-cols-3">
        <div className="bg-card p-4"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Eligible outcomes</div><div className="mt-1 text-2xl font-bold">{data.calibration?.eligible_outcomes ?? 0}</div></div>
        <div className="bg-card p-4"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Qualified ranking buckets</div><div className="mt-1 text-2xl font-bold">{buckets.filter((item) => item.probability.status === "local_forward_validated").length}</div></div>
        <div className="bg-card p-4"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Method</div><div className="mt-2 text-sm font-semibold">Expanding-window isotonic</div></div>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(260px,0.8fr)_minmax(420px,1.2fr)]">
        <section className="border border-border bg-card">
          <div className="border-b border-border px-3 py-2 text-sm font-semibold">Grade buckets</div>
          {buckets.length ? <div className="divide-y divide-border">{buckets.map((item) => <button type="button" key={item.bucket_id} onClick={() => setSelected(item.bucket_id)} className={`grid w-full grid-cols-[1fr_44px_75px] gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50 ${bucket?.bucket_id === item.bucket_id ? "bg-primary/10" : ""}`}><span><span className="font-semibold">{item.setup_family}</span><span className="ml-2 text-xs text-muted-foreground">{item.regime}</span></span><span className="font-bold">{item.grade}</span><span className="text-right">{item.probability.status === "not_calibrated" ? "N/A" : pct(item.probability.value)}</span></button>)}</div> : <p className="px-3 py-5 text-sm text-muted-foreground">No eligible calibration buckets yet. The dashboard will not infer a probability from a grade alone.</p>}
        </section>
        <section className="border border-border bg-card p-4">
          {bucket ? <><div className="mb-3 flex flex-wrap items-start justify-between gap-3"><div><div className="font-semibold">{bucket.setup_family} · {bucket.regime} · Grade {bucket.grade}</div><div className="mt-1 text-xs text-muted-foreground">{bucket.probability.label}</div></div><div className="text-right"><div className="text-2xl font-bold">{bucket.probability.status === "not_calibrated" ? "Not calibrated" : pct(bucket.probability.value)}</div><div className="text-xs text-muted-foreground">95% block-bootstrap lower {pct(bucket.probability.lower_bound)} · n={bucket.probability.sample_size}</div></div></div><ReliabilityDiagram bins={bucket.reliability_bins} /><div className="mt-3 grid grid-cols-3 gap-2 text-xs"><div>ECE <strong>{pct(bucket.probability.ece)}</strong></div><div>MCE <strong>{pct(bucket.probability.mce)}</strong></div><div>Brier skill <strong>{pct(bucket.probability.brier_skill_vs_expanding_base_rate)}</strong></div></div></> : <ReliabilityDiagram bins={[]} />}
        </section>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">Read-only calibration surface. execution_enabled=false · can_submit_orders=false</p>
    </div>
  );
}
