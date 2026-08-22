import type { DetectionPatternCoverage, TradingDashboard } from "@/lib/api";

type Scorecard = NonNullable<NonNullable<TradingDashboard["discovery"]>["scorecard_rolling"]>;

interface DetectionTabProps {
  scorecard?: Scorecard;
}

function pct(value: number | null | undefined): string {
  return value == null ? "Not measured" : `${(value * 100).toFixed(1)}%`;
}

function deltaTone(delta: number): string {
  if (delta < 0) return "bg-red-500/15 text-red-500";
  if (delta > 0) return "bg-amber-500/15 text-amber-500";
  return "bg-emerald-500/15 text-emerald-500";
}

function CoverageHeatmap({ coverage }: { coverage: DetectionPatternCoverage }) {
  const families = coverage.per_family ?? [];
  return (
    <section className="mt-4 overflow-hidden border border-border bg-card" aria-labelledby="coverage-heading">
      <div className="border-b border-border px-3 py-2">
        <h2 id="coverage-heading" className="text-sm font-semibold">Pattern-family coverage heatmap</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">Delta = grader detections − independently labeled ground truth.</p>
      </div>
      {families.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-xs">
            <caption className="sr-only">Precision, recall, and coverage delta by pattern family</caption>
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
              <tr><th className="px-3 py-2">Family</th><th className="px-3 py-2">Labeled</th><th className="px-3 py-2">Detected</th><th className="px-3 py-2">Delta</th><th className="px-3 py-2">Precision</th><th className="px-3 py-2">Recall</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {families.map((row) => (
                <tr key={row.family}>
                  <th scope="row" className="px-3 py-2 font-semibold">{row.family.replace(/_/g, " ")}</th>
                  <td className="px-3 py-2 tabular-nums">{row.ground_truth_labeled}</td>
                  <td className="px-3 py-2 tabular-nums">{row.grader_detected}</td>
                  <td className="px-3 py-2"><span className={`inline-flex min-w-12 justify-center rounded px-2 py-1 font-bold tabular-nums ${deltaTone(row.coverage_delta)}`}>{row.coverage_delta > 0 ? "+" : ""}{row.coverage_delta}</span></td>
                  <td className="px-3 py-2 tabular-nums">{pct(row.precision)}</td>
                  <td className="px-3 py-2 tabular-nums">{pct(row.recall)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="px-3 py-5 text-sm text-muted-foreground">No pattern-family denominator is available yet.</p>}
    </section>
  );
}

export function DetectionTab({ scorecard }: DetectionTabProps) {
  const metrics = scorecard?.metrics;
  const coverage = scorecard?.pattern_coverage;
  const misses = scorecard?.top_missed_moves ?? [];
  const totals = coverage?.totals;
  const cisd = coverage?.cisd_hypothesis;
  return (
    <>
      <div className="mt-4 grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Rolling recall@10", pct(metrics?.recall_at_10)],
          ["Mean precision@10", pct(metrics?.precision_at_10_mean)],
          ["Ground-truth moves", String(metrics?.ground_truth_count ?? 0)],
          ["Miss RCA coverage", pct(metrics?.root_cause_coverage)],
        ].map(([name, value]) => <div key={name} className="bg-card p-4"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">{name}</div><div className="mt-1 text-2xl font-bold">{value}</div></div>)}
      </div>

      {coverage && !coverage.metrics_qualified ? <div role="status" className="mt-4 border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">Placeholder denominator active — precision and recall remain unqualified until Kenny approves the frozen MOVE ground-truth spec.</div> : null}

      {coverage ? (
        <div className="mt-4 grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-4">
          <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Pattern labels</div><div className="mt-1 text-xl font-bold tabular-nums">{totals?.ground_truth_labeled ?? 0}</div></div>
          <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Grader detections</div><div className="mt-1 text-xl font-bold tabular-nums">{totals?.grader_detected ?? 0}</div></div>
          <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Coverage delta</div><div className="mt-1 text-xl font-bold tabular-nums">{(totals?.coverage_delta ?? 0) > 0 ? "+" : ""}{totals?.coverage_delta ?? 0}</div></div>
          <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">CISD evidence</div><div className="mt-1 text-sm font-bold tabular-nums">n={cisd?.n_outcomes ?? 0} · dates={cisd?.n_dates ?? 0}</div><div className="mt-1 text-xs text-muted-foreground">Brier {cisd?.brier == null ? "Not measured" : cisd.brier.toFixed(3)}</div></div>
        </div>
      ) : null}

      {coverage ? <CoverageHeatmap coverage={coverage} /> : null}

      <section className="mt-4 border border-border bg-card">
        <div className="border-b border-border px-3 py-2 text-sm font-semibold">Top missed moves</div>
        {misses.length ? <div className="divide-y divide-border">{misses.slice(0, 10).map((row, index) => <div key={`${String(row.move_id ?? row.symbol)}-${index}`} className="grid grid-cols-[70px_90px_1fr] gap-3 px-3 py-2 text-sm"><span className="font-bold">{String(row.symbol ?? "--")}</span><span>{String(row.move_pct ?? "--")}%</span><span className="text-muted-foreground">{String(row.partition ?? "unclassified")}</span></div>)}</div> : <p className="px-3 py-5 text-sm text-muted-foreground">No measured missed moves yet. This is not evidence of perfect coverage when the denominator is empty.</p>}
      </section>
    </>
  );
}
