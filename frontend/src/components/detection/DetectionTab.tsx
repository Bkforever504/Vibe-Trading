import type { CisdPromotionStatus, DetectionPatternCoverage, MesV2EvidenceStatus, MnqSmtFamilyEvidenceStatus, TradingDashboard } from "@/lib/api";

type Scorecard = NonNullable<NonNullable<TradingDashboard["discovery"]>["scorecard_rolling"]>;

interface DetectionTabProps {
  scorecard?: Scorecard;
  promotion?: CisdPromotionStatus;
  governance?: TradingDashboard["research_governance"];
  mesEvidence?: MesV2EvidenceStatus;
  mnqEvidence?: MnqSmtFamilyEvidenceStatus;
}

function MnqEvidenceProgress({ evidence }: { evidence?: MnqSmtFamilyEvidenceStatus }) {
  const candidates = evidence?.candidates ?? [];
  return (
    <section className="mt-4 border border-border bg-card" aria-labelledby="mnq-evidence-heading">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div><h2 id="mnq-evidence-heading" className="text-sm font-semibold">MNQ SMT / CISD Databento evidence</h2><p className="mt-0.5 text-xs text-muted-foreground">Four frozen ablations are reproduced from raw-contract OHLCV and resolved from reconstructed MBO. Proxy outcomes never count.</p></div>
        <span className={`rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${evidence?.live_feed.status === "available" ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500"}`}>Live CME {evidence?.live_feed.status ?? "not probed"}</span>
      </div>
      {candidates.length ? <div className="divide-y divide-border">{candidates.map((candidate) => <article key={candidate.candidate_id} className="p-3">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="font-semibold">{candidate.candidate_id}</div><div className="text-xs text-muted-foreground">{candidate.family_id}</div></div><span className="rounded bg-amber-500/15 px-2 py-1 text-[10px] font-bold uppercase text-amber-500">{candidate.status.replace(/_/g, " ")}</span></div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <ProgressStat label="Qualified MBO outcomes" value={candidate.qualified_outcomes} target={candidate.targets.resolved_outcomes} />
          <ProgressStat label="Independent dates" value={candidate.distinct_dates} target={candidate.targets.distinct_dates} />
          <div className="border border-border bg-background p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Regime dates</div><div className="mt-1 text-xs tabular-nums">Trend {candidate.regime_dates.trend} · Chop {candidate.regime_dates.chop}</div><div className="mt-1 text-xs tabular-nums">High vol {candidate.regime_dates.high_vol} · Low vol {candidate.regime_dates.low_vol}</div><div className="mt-2 text-xs text-muted-foreground">Need {candidate.targets.dates_per_regime} each</div></div>
          <div className="border border-border bg-background p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Excluded proxy / invalid</div><div className="mt-1 text-lg font-bold tabular-nums">{candidate.excluded_outcomes}</div><div className="mt-2 text-xs text-muted-foreground">Approval {evidence?.approval_present ? "recorded" : "missing"}</div></div>
        </div>
        {candidate.blockers.length ? <p className="mt-2 text-xs text-amber-600">HOLD: {candidate.blockers.join(" · ").replace(/_/g, " ")}</p> : null}
      </article>)}</div> : <p className="px-3 py-5 text-sm text-muted-foreground">No delayed MNQ MBO evidence yet. The first eligible market session is 2026-08-25.</p>}
      <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">Live CME license absence blocks real-time Databento—not delayed regrading · execution_enabled=false · can_submit_orders=false</p>
    </section>
  );
}

function MesEvidenceProgress({ evidence }: { evidence?: MesV2EvidenceStatus }) {
  const candidates = evidence?.candidates ?? [];
  return (
    <section className="mt-4 border border-border bg-card" aria-labelledby="mes-evidence-heading">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div><h2 id="mes-evidence-heading" className="text-sm font-semibold">MES v2 forward evidence</h2><p className="mt-0.5 text-xs text-muted-foreground">Proxy alerts support timely review; only delayed Databento MBO regrades enter promotion statistics.</p></div>
        <span className={`rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${evidence?.live_feed.status === "available" ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500"}`}>Databento live {evidence?.live_feed.status ?? "not probed"}</span>
      </div>
      {candidates.length ? <div className="divide-y divide-border">{candidates.map((candidate) => <article key={candidate.candidate_id} className="p-3">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="font-semibold">{candidate.candidate_id}</div><div className="text-xs text-muted-foreground">{candidate.family_id}</div></div><span className="rounded bg-amber-500/15 px-2 py-1 text-[10px] font-bold uppercase text-amber-500">{candidate.status.replace(/_/g, " ")}</span></div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <ProgressStat label="Qualified outcomes" value={candidate.qualified_outcomes} target={candidate.targets.resolved_outcomes} />
          <ProgressStat label="Independent dates" value={candidate.distinct_dates} target={candidate.targets.distinct_dates} />
          <div className="border border-border bg-background p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Regime dates</div><div className="mt-1 text-xs tabular-nums">Trend {candidate.regime_dates.trend} · Chop {candidate.regime_dates.chop}</div><div className="mt-1 text-xs tabular-nums">High vol {candidate.regime_dates.high_vol} · Low vol {candidate.regime_dates.low_vol}</div><div className="mt-2 text-xs text-muted-foreground">Need {candidate.targets.dates_per_regime} each</div></div>
          <div className="border border-border bg-background p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Evidence exclusions</div><div className="mt-1 text-lg font-bold tabular-nums">{candidate.excluded_outcomes}</div><div className="mt-2 text-xs text-muted-foreground">Never included in promotion metrics</div></div>
        </div>
        {candidate.blockers.length ? <p className="mt-2 text-xs text-amber-600">HOLD: {candidate.blockers.join(" · ").replace(/_/g, " ")}</p> : null}
      </article>)}</div> : <p className="px-3 py-5 text-sm text-muted-foreground">No MES evidence status report yet. Promotion remains HOLD.</p>}
      <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">execution_enabled=false · can_submit_orders=false</p>
    </section>
  );
}

function pct(value: number | null | undefined): string {
  return value == null ? "Not measured" : `${(value * 100).toFixed(1)}%`;
}

function deltaTone(delta: number | null): string {
  if (delta == null) return "bg-muted text-muted-foreground";
  if (delta < 0) return "bg-red-500/15 text-red-500";
  if (delta > 0) return "bg-amber-500/15 text-amber-500";
  return "bg-emerald-500/15 text-emerald-500";
}

function deltaLabel(delta: number | null): string {
  if (delta == null) return "Not measured";
  return `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(1)}%`;
}

function metricTone(value: number | null, greenAt: number): string {
  if (value == null) return "text-muted-foreground";
  if (value >= greenAt) return "text-emerald-500";
  if (value >= 0.45 && greenAt === 0.55) return "text-amber-500";
  return "text-red-500";
}

function ProgressStat({ label, value, target }: { label: string; value: number; target: number }) {
  const width = Math.min(100, value / target * 100);
  return <div className="border border-border bg-background p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div><div className="mt-1 text-lg font-bold tabular-nums">{value} / {target}</div><div className="mt-2 h-1.5 overflow-hidden rounded bg-muted"><div className="h-full bg-emerald-500" style={{ width: `${width}%` }} /></div></div>;
}

function CisdProgress({ promotion }: { promotion?: CisdPromotionStatus }) {
  const validated = promotion?.eligible_for_validated_promotion === true;
  const status = validated ? "validated_pattern" : "unvalidated_pattern_hypothesis";
  return (
    <section className="mt-4 border border-border bg-card" aria-labelledby="cisd-progress-heading">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div><h2 id="cisd-progress-heading" className="text-sm font-semibold">CISD Hypothesis Progress</h2><p className="mt-0.5 text-xs text-muted-foreground">Promotion requires every frozen evidence gate; progress is not probability of profit.</p></div>
        <span className={`rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${validated ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500"}`}>{status}</span>
      </div>
      <div className="grid gap-2 p-3 sm:grid-cols-2 xl:grid-cols-4">
        <ProgressStat label="Resolved outcomes" value={promotion?.n_outcomes ?? 0} target={100} />
        <ProgressStat label="Unique dates" value={promotion?.n_unique_dates ?? 0} target={30} />
        <div className="border border-border bg-background p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Wilson lower bound</div><div className={`mt-1 text-lg font-bold tabular-nums ${metricTone(promotion?.wilson_lower_bound_95 ?? null, 0.55)}`}>{pct(promotion?.wilson_lower_bound_95)}</div><div className="mt-2 text-xs text-muted-foreground">Gate ≥ 55.0%</div></div>
        <div className="border border-border bg-background p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Brier skill</div><div className={`mt-1 text-lg font-bold tabular-nums ${metricTone(promotion?.brier_skill ?? null, Number.MIN_VALUE)}`}>{promotion?.brier_skill == null ? "Not measured" : promotion.brier_skill.toFixed(3)}</div><div className="mt-2 text-xs text-muted-foreground">Gate &gt; 0 vs 50% baseline</div></div>
      </div>
      <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">Source: cisd-promotion-status.json · execution_enabled=false · can_submit_orders=false</p>
    </section>
  );
}

function GovernanceControls({ governance }: { governance?: TradingDashboard["research_governance"] }) {
  const status = governance?.governance_status ?? "awaiting_evidence";
  const blocked = status !== "all_latest_candidates_pass";
  const blockers = [...(governance?.unavailable_rule_ids ?? []), ...(governance?.failed_rule_ids ?? [])];
  const controls = governance?.controls;
  return (
    <section className="mt-4 border border-border bg-card" aria-labelledby="governance-heading">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div><h2 id="governance-heading" className="text-sm font-semibold">Promotion governance</h2><p className="mt-0.5 text-xs text-muted-foreground">Every challenger must clear evidence quality, timing, regime, repair, decay, and universe controls.</p></div>
        <span className={`rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${blocked ? "bg-amber-500/15 text-amber-500" : "bg-emerald-500/15 text-emerald-500"}`}>{status.replace(/_/g, " ")}</span>
      </div>
      <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-4">
        <div className="bg-card p-3"><div className="text-[10px] uppercase text-muted-foreground">Multiple testing</div><div className="mt-1 text-sm font-bold">{controls?.multiple_testing_method ?? "Not configured"}</div><div className="text-xs text-muted-foreground">FDR α {controls?.fdr_alpha ?? "--"}</div></div>
        <div className="bg-card p-3"><div className="text-[10px] uppercase text-muted-foreground">Regime minimum</div><div className="mt-1 text-sm font-bold">{controls?.minimum_dates_per_regime ?? "--"} dates each</div><div className="text-xs text-muted-foreground">{controls?.required_regimes?.join(" · ") || "Not configured"}</div></div>
        <div className="bg-card p-3"><div className="text-[10px] uppercase text-muted-foreground">Latency budget</div><div className="mt-1 text-sm font-bold">p90 ≤ {controls?.latency_p90_maximum_fraction == null ? "--" : pct(controls.latency_p90_maximum_fraction)}</div><div className="text-xs text-muted-foreground">of expected move window</div></div>
        <div className="bg-card p-3"><div className="text-[10px] uppercase text-muted-foreground">Revalidate</div><div className="mt-1 text-sm font-bold">≤ {controls?.revalidation_maximum_age_days ?? "--"} days</div><div className="text-xs text-muted-foreground">universe version + repair re-grade required</div></div>
      </div>
      <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">{blockers.length ? `Current holds/rejections: ${blockers.join(", ")}` : `Rule ${governance?.promotion_rule_version ?? "not loaded"} · no current governance blockers`} · execution_enabled=false · can_submit_orders=false</p>
    </section>
  );
}

function CoverageHeatmap({ coverage }: { coverage: DetectionPatternCoverage }) {
  const families = coverage.per_family ?? [];
  return (
    <section className="mt-4 overflow-hidden border border-border bg-card" aria-labelledby="coverage-heading">
      <div className="border-b border-border px-3 py-2">
        <h2 id="coverage-heading" className="text-sm font-semibold">Pattern-family coverage heatmap</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">Delta = (grader detections − independently labeled ground truth) / labeled ground truth.</p>
      </div>
      {families.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-xs">
            <caption className="sr-only">Independent annotation metrics and resolved outcome quality by pattern family</caption>
            <thead className="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
              <tr><th className="px-3 py-2">Family</th><th className="px-3 py-2">Labeled</th><th className="px-3 py-2">Detected</th><th className="px-3 py-2">Delta</th><th className="px-3 py-2">Precision</th><th className="px-3 py-2">Recall</th><th className="px-3 py-2">Resolved</th><th className="px-3 py-2">Win rate</th><th className="px-3 py-2">Avg R</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {families.map((row) => (
                <tr key={row.family}>
                  <th scope="row" className="px-3 py-2 font-semibold">{row.family.replace(/_/g, " ")}</th>
                  <td className="px-3 py-2 tabular-nums">{row.ground_truth_labeled}</td>
                  <td className="px-3 py-2 tabular-nums">{row.grader_detected}</td>
                  <td className="px-3 py-2"><span className={`inline-flex min-w-12 justify-center rounded px-2 py-1 font-bold tabular-nums ${deltaTone(row.coverage_delta)}`}>{deltaLabel(row.coverage_delta)}</span></td>
                  <td className="px-3 py-2 tabular-nums">{pct(row.precision)}</td>
                  <td className="px-3 py-2 tabular-nums">{pct(row.recall)}</td>
                  <td className="px-3 py-2 tabular-nums">{row.outcome_quality?.resolved_outcomes ?? 0}</td>
                  <td className="px-3 py-2 tabular-nums">{pct(row.outcome_quality?.observed_win_rate)}</td>
                  <td className="px-3 py-2 tabular-nums">{row.outcome_quality?.average_r == null ? "Not measured" : `${row.outcome_quality.average_r.toFixed(2)}R`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="px-3 py-5 text-sm text-muted-foreground">No pattern-family denominator is available yet.</p>}
    </section>
  );
}

export function DetectionTab({ scorecard, promotion, governance, mesEvidence, mnqEvidence }: DetectionTabProps) {
  const metrics = scorecard?.metrics;
  const coverage = scorecard?.pattern_coverage;
  const misses = scorecard?.top_missed_moves ?? [];
  const totals = coverage?.totals;
  const opportunity = coverage?.opportunity_coverage;
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

      {coverage && !coverage.metrics_qualified ? <div role="status" className="mt-4 border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">Move denominator unavailable — opportunity precision and recall remain unqualified until the independent frozen-spec builder completes.</div> : coverage && coverage.pattern_metrics_qualified === false ? <div role="status" className="mt-4 border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">Opportunity coverage is measured, but per-family precision and recall remain unavailable until an independent pattern annotation contract is populated. Resolved outcome quality is shown separately.</div> : null}

      <CisdProgress promotion={promotion} />
      <GovernanceControls governance={governance} />
      <MesEvidenceProgress evidence={mesEvidence} />
      <MnqEvidenceProgress evidence={mnqEvidence} />

      {coverage ? (
        <section className="mt-4 border border-border bg-card" aria-labelledby="opportunity-coverage-heading">
          <div className="border-b border-border px-3 py-2"><h2 id="opportunity-coverage-heading" className="text-sm font-semibold">Opportunity coverage</h2><p className="mt-0.5 text-xs text-muted-foreground">Any-family detection matched to independently labeled price displacement at the same completed bar.</p></div>
          <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-4">
            <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Labeled moves</div><div className="mt-1 text-xl font-bold tabular-nums">{opportunity?.ground_truth_moves ?? 0}</div></div>
            <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Moves caught</div><div className="mt-1 text-xl font-bold tabular-nums">{opportunity?.true_positives ?? 0}</div></div>
            <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Opportunity precision</div><div className="mt-1 text-xl font-bold tabular-nums">{pct(opportunity?.precision)}</div></div>
            <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Opportunity recall</div><div className="mt-1 text-xl font-bold tabular-nums">{pct(opportunity?.recall)}</div></div>
          </div>
        </section>
      ) : null}

      {coverage ? (
        <div className="mt-4 grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-4">
          <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Pattern labels</div><div className="mt-1 text-xl font-bold tabular-nums">{totals?.ground_truth_labeled ?? 0}</div></div>
          <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Grader detections</div><div className="mt-1 text-xl font-bold tabular-nums">{totals?.grader_detected ?? 0}</div></div>
          <div className="bg-card p-4"><div className="text-[10px] uppercase text-muted-foreground">Coverage delta</div><div className="mt-1 text-xl font-bold tabular-nums">{deltaLabel(totals?.coverage_delta ?? null)}</div></div>
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
