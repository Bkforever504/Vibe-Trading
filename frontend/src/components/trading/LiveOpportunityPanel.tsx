import { Activity, AlertTriangle, Clock3, Layers3, Radio, ShieldCheck } from "lucide-react";

import type { LiveOpportunityReport } from "@/lib/api";
import { cn } from "@/lib/utils";
import { StructureContextRail } from "./StructureContextRail";

type Connection = "connecting" | "live" | "degraded" | "snapshot";

function value(number: number | null | undefined): string {
  return number == null ? "--" : number.toFixed(2);
}

function label(text: string): string {
  return text.split("_").join(" ");
}

export function LiveOpportunityPanel({
  report,
  connection,
  onOpenChart,
}: {
  report: LiveOpportunityReport | null;
  connection: Connection;
  onOpenChart: (symbol: string) => void;
}) {
  const candidates = (report?.candidates ?? []).slice(0, 5);
  const feed = report?.feed;
  const structureRows = (report?.market_structure_watchlist ?? []).slice(0, 3);
  const bestStructure = structureRows[0];
  const canonicalGrade = bestStructure?.pattern_grade;
  const modelSequence = bestStructure?.best_setup?.model_sequence;
  const consequentEncroachment = modelSequence?.bonus_confluences.consequent_encroachment;
  const completedModelStages = modelSequence?.stages.filter((stage) => stage.status === "complete").length ?? 0;
  const gradeComponents = canonicalGrade
    ? [
        ["Base evidence", canonicalGrade.components.base_rate],
        ["Volume", canonicalGrade.components.volume_rvol],
        ["MTF", canonicalGrade.components.mtf_alignment],
        ["Regime", canonicalGrade.components.regime_fit],
        ["Confluence", canonicalGrade.components.confluence],
        ["R:R", canonicalGrade.components.reward_risk],
      ] as const
    : [];
  const scheduledFallback = report?.mode === "read_only_scheduled_fallback";
  const effectiveConnection: Connection = scheduledFallback ? "snapshot" : connection;
  const feedLabel = feed
    ? `Alpaca ${feed.feed.toUpperCase()} · ${scheduledFallback ? "scheduled completed-bar snapshot" : label(feed.transport)}`
    : "Feed unavailable";

  return (
    <section className="border border-border bg-card" aria-label="Streaming opportunity engine">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-3 py-2.5">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Radio className={cn("h-4 w-4", effectiveConnection === "live" ? "text-success" : "text-warning")} />
            Streaming opportunity engine
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {feedLabel}. Causal completed-bar patterns, bad-setup vetoes, exact timing, liquidity, and post-friction geometry.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={cn("border px-2 py-1 font-medium", effectiveConnection === "live" ? "border-success/30 text-success" : "border-warning/30 text-warning")}>{effectiveConnection}</span>
          <span className={cn("border px-2 py-1 font-medium", report?.decision_state === "READY_TO_REVIEW" ? "border-success/30 text-success" : "border-warning/30 text-warning")}>{label(report?.decision_state ?? "STAND_ASIDE")}</span>
        </div>
      </div>
      {bestStructure ? (
        <>
        <div className="grid gap-px bg-border lg:grid-cols-3">
          <button type="button" onClick={() => onOpenChart(bestStructure.symbol)} className="bg-card px-3 py-3 text-left hover:bg-muted/30">
            <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-success"><Layers3 className="h-3.5 w-3.5" />Best structure</span>
            <span className="mt-1 block text-sm font-bold">{bestStructure.symbol} · {label(bestStructure.best_setup?.pattern_id ?? "no confirmed setup")}</span>
            <span className="mt-1 block text-xs text-muted-foreground">{bestStructure.best_setup?.reason ?? "No objective entry geometry yet."}</span>
          </button>
          <div className="bg-card px-3 py-3">
            <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-danger"><AlertTriangle className="h-3.5 w-3.5" />Worst look-alike</span>
            <span className="mt-1 block text-sm font-bold">{label(bestStructure.worst_setup?.pattern_id ?? "none detected")}</span>
            <span className="mt-1 block text-xs text-muted-foreground">{bestStructure.worst_setup?.reason ?? "No active anti-pattern veto on the leading structure."}</span>
          </div>
          <div className="bg-card px-3 py-3">
            <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-info"><Clock3 className="h-3.5 w-3.5" />Timing & exit</span>
            <span className="mt-1 block text-sm font-bold">Trigger {value(bestStructure.entry_plan.trigger)} · Invalid {value(bestStructure.entry_plan.invalidation)}</span>
            <span className="mt-1 block text-xs text-muted-foreground">
              {bestStructure.exit_plan.targets.map((target) => `${target.name.replace("target_", "").toUpperCase()} ${value(target.price)}`).join(" · ") || "Targets unavailable"}
              {bestStructure.exit_plan.time_stop_bars ? ` · Time stop ${bestStructure.exit_plan.time_stop_bars} bars` : ""}
            </span>
          </div>
        </div>
        {modelSequence ? (
          <div className="border-b border-border bg-muted/10 px-3 py-3" aria-label="CISD sequence">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide">CISD sequence</span>
              <span className={cn("text-xs font-medium", modelSequence.core_complete ? "text-success" : "text-warning")}>
                {completedModelStages} of {modelSequence.stages.length} stages complete
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {modelSequence.stages.map((stage) => (
                <span key={stage.name} className={cn("border px-2 py-1 text-[10px] uppercase tracking-wide", stage.status === "complete" ? "border-success/30 text-success" : "border-warning/30 text-warning")}>
                  {label(stage.name)} · {label(stage.status)}
                </span>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {label(modelSequence.probability_status)} · mapped execution {modelSequence.mapped_execution_timeframe}
              {consequentEncroachment?.level == null ? "" : ` · CE ${value(consequentEncroachment.level)}`}
              {" · independent completed-bar rules"}
            </p>
          </div>
        ) : null}
        <StructureContextRail
          liquidity={bestStructure.liquidity_level_context}
          participation={bestStructure.participation_context}
          macro={bestStructure.macro_context}
          strat={bestStructure.strat_context}
          balanceRange={bestStructure.ny_0800_0900_range_context}
        />
        {canonicalGrade ? (
          <div className="border-b border-border bg-card px-3 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className={cn("text-sm font-bold", canonicalGrade.grade === "A" ? "text-success" : canonicalGrade.grade === "D" ? "text-danger" : "text-warning")}>Grade {canonicalGrade.grade} · {canonicalGrade.final_score.toFixed(1)}</span>
                <span className="ml-2 text-xs text-muted-foreground">{label(canonicalGrade.label)} · {label(canonicalGrade.validation_status)}</span>
              </div>
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">One canonical score · {canonicalGrade.rubric_version}</span>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
              {gradeComponents.map(([name, score]) => (
                <div key={name}>
                  <div className="flex justify-between text-[10px] uppercase text-muted-foreground"><span>{name}</span><span>{score.toFixed(0)}</span></div>
                  <div className="mt-1 h-1.5 bg-muted"><div className="h-full bg-info" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} /></div>
                </div>
              ))}
            </div>
            {canonicalGrade.penalty_multiplier < 1 ? (
              <p className="mt-2 text-xs text-danger">Penalty active: {Object.entries(canonicalGrade.penalty_factors).filter(([, factor]) => factor < 1).map(([name, factor]) => `${label(name)} ×${factor}`).join(" · ")}</p>
            ) : null}
          </div>
        ) : null}
        </>
      ) : null}
      {candidates.length > 0 ? (
        <div className="divide-y divide-border">
          {candidates.map((candidate) => (
            <button
              key={candidate.candidate_id}
              type="button"
              onClick={() => onOpenChart(candidate.symbol)}
              className="grid w-full grid-cols-[70px_minmax(160px,1.4fr)_90px_90px_90px_80px] items-center gap-3 px-3 py-3 text-left text-sm hover:bg-muted/30 max-lg:grid-cols-[64px_minmax(150px,1fr)_80px_80px] max-lg:[&>*:nth-child(5)]:hidden max-lg:[&>*:nth-child(6)]:hidden"
            >
              <span className="font-bold">{candidate.symbol}</span>
              <span className="min-w-0"><span className="block truncate font-medium capitalize">{label(candidate.setup_family)}</span><span className="block truncate text-xs text-muted-foreground">{candidate.reason}</span></span>
              <span><span className="block text-[10px] uppercase text-muted-foreground">Entry</span>{value(candidate.entry)}</span>
              <span><span className="block text-[10px] uppercase text-muted-foreground">Invalid</span>{value(candidate.invalidation)}</span>
              <span><span className="block text-[10px] uppercase text-muted-foreground">Post-cost</span>{candidate.reward_risk_after_friction == null ? "--" : `${candidate.reward_risk_after_friction.toFixed(2)}R`}</span>
              <span className={cn("font-semibold", candidate.state === "READY_TO_REVIEW" ? "text-success" : candidate.state === "REJECT" ? "text-danger" : "text-warning")}><span className="block">{candidate.grade}</span><span className="block text-[10px] font-normal uppercase">{label(candidate.market_structure?.decision ?? candidate.state)}</span></span>
            </button>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-2 px-3 py-5 text-sm text-muted-foreground"><Activity className="h-4 w-4" />No streaming candidate clears the display gate. Stand aside.</div>
      )}
      <div className="flex items-center gap-2 border-t border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5 text-success" />Manual review only. This feed has no order authority.
      </div>
    </section>
  );
}
