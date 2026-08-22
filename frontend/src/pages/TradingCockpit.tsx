import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  FileJson,
  Gauge,
  RefreshCw,
  Search,
  ShieldCheck,
  Target,
  TrendingUp,
  WalletCards,
  XCircle,
  LineChart,
  Pin,
} from "lucide-react";
import { toast } from "sonner";
import { api, type LiveOpportunityReport, type SimplePriceActionSignal, type TradingCandidate, type TradingDashboard, type TradingSource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { Skeleton, SkeletonMetrics } from "@/components/common/Skeleton";
import { BlockerChips } from "@/components/trading/BlockerChips";
import { CatalystStrip } from "@/components/trading/CatalystStrip";
import { ChartDrawer } from "@/components/trading/ChartDrawer";
import { OptionsContextPanel } from "@/components/trading/OptionsContextPanel";
import { PositionSizer } from "@/components/trading/PositionSizer";
import { SocialEvidencePanel } from "@/components/trading/SocialEvidencePanel";
import { TickerStrip } from "@/components/trading/TickerStrip";
import { LiveOpportunityPanel } from "@/components/trading/LiveOpportunityPanel";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useDashboardPrefs } from "@/stores/dashboardPrefs";

type View = "overview" | "stocks" | "options" | "futures" | "setups" | "risk" | "sources";
type CandidateFilter = "all" | "ready" | "watch" | "blocked";

const VIEWS: Array<{ id: View; label: string }> = [
  { id: "overview", label: "Daily Board" },
  { id: "stocks", label: "Stocks" },
  { id: "options", label: "Options" },
  { id: "futures", label: "Futures" },
  { id: "setups", label: "All Setups" },
  { id: "risk", label: "Risk & Ops" },
  { id: "sources", label: "Sources" },
];

function money(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-US", { style: "currency", currency: "USD" }) : "--";
}

function number(value: unknown, digits = 1): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "--";
}

function label(value: unknown): string {
  return String(value ?? "unknown").replace(/_/g, " ");
}

function catalystLabels(data: TradingDashboard["evidence"]["catalysts_today"], symbol: string): string[] {
  const labels: string[] = [];
  for (const day of data.days) {
    const events = Array.isArray(day.events) ? day.events : Array.isArray(day.items) ? day.items : [];
    for (const raw of events) {
      if (!raw || typeof raw !== "object") continue;
      const event = raw as Record<string, unknown>;
      const symbols = Array.isArray(event.symbols) ? event.symbols : [event.symbol ?? event.ticker ?? event.underlying];
      if (!symbols.some((item) => String(item ?? "").toUpperCase() === symbol.toUpperCase())) continue;
      labels.push(String(event.title ?? event.event ?? event.name ?? "Sourced catalyst"));
    }
  }
  return [...new Set(labels)].slice(0, 2);
}

function age(seconds: number | null): string {
  if (seconds === null) return "unavailable";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function tone(value: string): string {
  const normalized = value.toLowerCase();
  if (["ready", "live", "ok", "normal", "qualified_long", "paper_ready", "shadow_ready", "confirmed"].some((item) => normalized.includes(item))) {
    return "border-success/30 bg-success/10 text-success";
  }
  if (["blocked", "error", "stale", "missing", "high", "invalid", "too_late", "no_chase"].some((item) => normalized.includes(item))) {
    return "border-danger/30 bg-danger/10 text-danger";
  }
  if (["watch", "armed", "recent", "prior", "cautious", "pressure"].some((item) => normalized.includes(item))) {
    return "border-warning/30 bg-warning/10 text-warning";
  }
  return "border-border bg-muted/60 text-muted-foreground";
}

function StatusPill({ children }: { children: string }) {
  return <span className={cn("inline-flex items-center border px-2 py-0.5 text-[11px] font-medium", tone(children))}>{label(children)}</span>;
}

function Metric({ labelText, value, detail }: { labelText: string; value: string; detail?: string }) {
  return (
    <div className="min-w-0 border-l border-border pl-3 first:border-l-0 first:pl-0">
      <div className="text-[11px] font-medium uppercase text-muted-foreground">{labelText}</div>
      <div className="mt-1 truncate text-lg font-semibold tabular-nums">{value}</div>
      {detail && <div className="mt-0.5 truncate text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

function GradeBadge({ grade, score }: { grade?: string; score?: number }) {
  const good = Number(score ?? 0) >= 80;
  const watch = Number(score ?? 0) >= 65;
  return (
    <div className={cn("flex h-14 w-14 shrink-0 flex-col items-center justify-center border", good ? "border-success/40 bg-success/10 text-success" : watch ? "border-warning/40 bg-warning/10 text-warning" : "border-danger/30 bg-danger/10 text-danger")}>
      <span className="text-lg font-bold leading-none">{grade ?? "--"}</span>
      <span className="mt-1 text-[10px] font-semibold tabular-nums">{score == null ? "N/A" : `${number(score, 0)}/100`}</span>
    </div>
  );
}

function SignalDot({ color }: { color: SimplePriceActionSignal["color"] }) {
  return <span className={cn("h-3 w-3 shrink-0 rounded-full", color === "GREEN" ? "bg-success" : color === "RED" ? "bg-danger" : "bg-warning")} aria-label={color} />;
}

function SimpleSignalBoard({ signals }: { signals: SimplePriceActionSignal[] }) {
  if (!signals.length) {
    return <section className="border-y border-border px-3 py-4 text-sm text-muted-foreground">Simple price-action state is waiting for the next radar refresh.</section>;
  }
  return (
    <section className="border-y border-border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2.5">
        <div>
          <div className="text-sm font-semibold">Price-action signals</div>
          <div className="mt-0.5 text-xs text-muted-foreground">Closed 5-minute bars only. Green is confirmation, not guaranteed profit.</div>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground"><span className="flex items-center gap-1.5"><SignalDot color="GREEN" />Confirmed</span><span className="flex items-center gap-1.5"><SignalDot color="YELLOW" />Wait</span><span className="flex items-center gap-1.5"><SignalDot color="RED" />Invalid</span></div>
      </div>
      <div className="divide-y divide-border">
        {signals.slice(0, 8).map((signal) => (
          <div key={signal.symbol} className="grid gap-3 px-3 py-3 md:grid-cols-[150px_90px_minmax(220px,1fr)_minmax(250px,1.2fr)] md:items-center">
            <div className="flex min-w-0 items-center gap-2"><SignalDot color={signal.color} /><div><div className="font-semibold">{signal.symbol} · {signal.direction}</div><div className="text-xs text-muted-foreground">{signal.grade} · {number(signal.score, 0)}/100</div></div></div>
            <div className={cn("text-xs font-bold", signal.color === "GREEN" ? "text-success" : signal.color === "RED" ? "text-danger" : "text-warning")}>{signal.state}</div>
            <div className="grid grid-cols-3 gap-3 text-xs tabular-nums"><div><div className="text-[10px] uppercase text-muted-foreground">Trigger</div><div className="mt-1 font-semibold">{signal.trigger ?? "--"}</div></div><div><div className="text-[10px] uppercase text-muted-foreground">Stop</div><div className="mt-1 font-semibold">{signal.stop ?? "--"}</div></div><div><div className="text-[10px] uppercase text-muted-foreground">Target</div><div className="mt-1 font-semibold">{signal.target ?? "--"}</div></div></div>
            <div className="min-w-0 text-xs"><div className="font-semibold">{label(signal.decisive_reason)}</div><div className="mt-1 text-muted-foreground">{signal.action}</div></div>
          </div>
        ))}
      </div>
    </section>
  );
}

function CommandCard({ command, dealer, blockers }: { command: TradingDashboard["command_card"]; dealer: TradingDashboard["dealer_regime"]; blockers: string[] }) {
  if (!command) return null;
  const commandTone = command.color === "GREEN" ? "border-success bg-success/5" : command.color === "YELLOW" ? "border-warning bg-warning/5" : "border-danger bg-danger/5";
  const zone = command.no_trade_zone;
  return (
    <section className={cn("border-l-4", commandTone)}>
      <div className="grid lg:grid-cols-[minmax(0,1.65fr)_minmax(280px,0.75fr)]">
        <div className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-semibold uppercase text-muted-foreground">Primary instruction · read only</div>
              <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-2xl font-bold">{label(command.state)}</span>
                <span className="text-lg font-semibold">{command.symbol ? `${command.symbol} · ${label(command.direction)}` : "No active symbol"}</span>
              </div>
              <div className="mt-1 text-sm text-muted-foreground">{command.setup ? label(command.setup) : "No complete setup"}</div>
            </div>
            <GradeBadge grade={command.grade} score={command.decision_score ?? undefined} />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
            <div className="bg-background p-3"><div className="text-[10px] font-semibold uppercase text-muted-foreground">Trigger</div><div className="mt-1 text-base font-bold tabular-nums">{command.trigger ?? "--"}</div></div>
            <div className="bg-background p-3"><div className="text-[10px] font-semibold uppercase text-muted-foreground">Invalidation</div><div className="mt-1 text-base font-bold tabular-nums">{command.invalidation ?? "--"}</div></div>
            <div className="bg-background p-3"><div className="text-[10px] font-semibold uppercase text-muted-foreground">Target</div><div className="mt-1 text-base font-bold tabular-nums">{command.target ?? "--"}</div></div>
            <div className="bg-background p-3"><div className="text-[10px] font-semibold uppercase text-muted-foreground">Instrument</div><div className="mt-1 break-all text-sm font-semibold">{command.instrument ?? "Not selected"}</div></div>
          </div>
          <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
            <div><div className="text-[10px] font-semibold uppercase text-muted-foreground">Confirmation</div><div className="mt-1">{command.confirmation_required}</div><div className="mt-1 text-xs text-muted-foreground">Evidence: {command.evidence_fresh ? "fresh" : "stale or unavailable"}</div></div>
            <div><div className="text-[10px] font-semibold uppercase text-muted-foreground">Next action</div><div className="mt-1">{command.next_action}</div></div>
          </div>
          <div className="mt-3 border-t border-border pt-3 text-xs">
            <span className="font-semibold">No-trade zone: </span>
            <span className="text-muted-foreground">{zone.status === "available" ? `${zone.low} to ${zone.high}. ${zone.instruction}` : zone.instruction}</span>
          </div>
          {command.state === "STAND_ASIDE" && <BlockerChips blockers={blockers.length ? blockers : ["no setup clears every gate"]} />}
        </div>
        <div className="border-t border-border p-4 lg:border-l lg:border-t-0">
          <div className="flex items-center justify-between gap-2"><div className="text-xs font-semibold uppercase text-muted-foreground">Dealer gamma route</div><StatusPill>{dealer?.status ?? "unavailable"}</StatusPill></div>
          <dl className="mt-4 grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Net GEX</dt><dd>{label(dealer?.net_gex_state ?? "unavailable")}</dd>
            <dt className="text-muted-foreground">Spot vs flip</dt><dd>{label(dealer?.spot_vs_flip ?? "unavailable")}</dd>
            <dt className="text-muted-foreground">Quadrant</dt><dd>{dealer?.quadrant == null ? "Not classified" : label(dealer.quadrant)}</dd>
          </dl>
          <p className="mt-4 text-sm">{dealer?.strategy_route ?? "No gamma route. Use price action and ordinary risk gates."}</p>
          <p className="mt-2 text-xs text-muted-foreground">{dealer?.reason ?? "Fresh provenance-qualified dealer positioning is unavailable."}</p>
        </div>
      </div>
    </section>
  );
}

function DecisionDesk({ data }: { data: TradingDashboard["decision_desk"] }) {
  if (!data) return null;
  const lanes = [
    { key: "shadow_ready", labelText: "Ready to shadow", rows: data.best_now, detail: "Confirmed, reward remains" },
    { key: "wait", labelText: "Wait for level", rows: data.next_up, detail: "Armed, not confirmed" },
    { key: "late_no_chase", labelText: "Too late", rows: data.no_chase, detail: "Log it, do not chase" },
    { key: "invalid", labelText: "Invalid", rows: data.invalid, detail: "Mechanical stop crossed" },
  ];
  return (
    <section className="border-y border-border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-3 py-3">
        <div><div className="text-sm font-semibold">Shadow decision desk</div><div className="mt-1 text-xs text-muted-foreground">{data.method}</div></div>
        <StatusPill>read only</StatusPill>
      </div>
      <div className="grid divide-y divide-border lg:grid-cols-4 lg:divide-x lg:divide-y-0">
        {lanes.map((lane) => (
          <div key={lane.key} className="min-w-0 p-3">
            <div className="flex items-center justify-between gap-2"><div className="text-xs font-semibold uppercase text-muted-foreground">{lane.labelText}</div><StatusPill>{String(data.counts[lane.key] ?? 0)}</StatusPill></div>
            <div className="mt-1 text-[11px] text-muted-foreground">{lane.detail}</div>
            <div className="mt-3 space-y-2">
              {lane.rows.slice(0, 3).map((row) => (
                <div key={`${lane.key}-${row.plan_id ?? row.symbol}`} className="border-l-2 border-border pl-2">
                  <div className="flex items-center justify-between gap-2 text-sm"><span className="font-semibold">{row.symbol} · {label(row.direction)}</span><span className="tabular-nums text-muted-foreground">{number(row.decision_score, 0)}</span></div>
                  <div className="mt-0.5 truncate text-xs text-muted-foreground">{label(row.setup)}</div>
                  {row.reward_remaining_r != null && <div className="mt-1 text-[11px] tabular-nums text-muted-foreground">{number(row.reward_remaining_r, 2)}R left · {number(row.move_consumed_pct, 0)}% consumed</div>}
                </div>
              ))}
              {lane.rows.length === 0 && <div className="text-xs text-muted-foreground">None</div>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function FactorGrid({ candidate }: { candidate: TradingCandidate }) {
  const factors = Object.entries(candidate.factors ?? {});
  if (!factors.length) return <div className="text-xs text-muted-foreground">Factor detail unavailable in this legacy signal.</div>;
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
      {factors.map(([name, factor]) => (
        <div key={name} className="min-w-0">
          <div className="flex items-center justify-between gap-2 text-[10px] font-medium uppercase text-muted-foreground"><span className="truncate">{label(name)}</span><span className="tabular-nums">{factor.available && factor.score != null ? number(factor.score, 0) : "--"}</span></div>
          <div className="mt-1 h-1.5 bg-muted"><div className={cn("h-full", Number(factor.score ?? 0) >= 80 ? "bg-success" : Number(factor.score ?? 0) >= 60 ? "bg-warning" : "bg-danger")} style={{ width: `${factor.score ?? 0}%` }} /></div>
        </div>
      ))}
    </div>
  );
}

function PlanCard({ candidate, title, equity, onOpenChart }: { candidate?: TradingCandidate; title: string; equity: number; onOpenChart: (symbol: string) => void }) {
  const pinSymbol = useDashboardPrefs((state) => state.pinSymbol);
  const pinned = useDashboardPrefs((state) => candidate ? state.watchlist_symbols.includes(candidate.symbol) : false);
  if (!candidate) {
    return <section className="border border-border bg-card p-4"><div className="text-xs font-semibold uppercase text-muted-foreground">{title}</div><div className="mt-5 text-sm text-muted-foreground">No ranked plan available from current sources.</div></section>;
  }
  const plan = candidate.trade_plan;
  const target = plan?.targets?.[0]?.price ?? candidate.target;
  const probability = candidate.probability;
  const optionRiskUnavailable = Boolean(plan?.contract) || /option|call|put|spread/i.test(String(plan?.instrument ?? candidate.instrument ?? ""));
  const futuresMultipliers: Record<string, number> = { MES: 5, MNQ: 2, M2K: 5, MYM: 0.5, ES: 50, NQ: 20, RTY: 50, YM: 5 };
  const sizeMultiplier = futuresMultipliers[candidate.symbol.toUpperCase()] ?? 1;
  return (
    <section className="min-w-0 border border-border bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-border p-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">{title} · plan {candidate.plan_id ?? "legacy"}</div>
          <div className="mt-1 text-lg font-bold">{`${candidate.symbol} · ${label(candidate.setup)}`}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2"><StatusPill>{candidate.lane}</StatusPill><span className="text-xs text-muted-foreground">{label(candidate.direction)} · {label(candidate.source)}</span></div>
        </div>
        <div className="flex items-start gap-2">
          <button type="button" onClick={() => pinSymbol(candidate.symbol)} className="border border-border p-2 text-muted-foreground hover:text-primary" aria-label={`Pin ${candidate.symbol}`} title={pinned ? "Pinned" : "Pin to watchlist"}><Pin className="h-4 w-4" /></button>
          <button type="button" onClick={() => onOpenChart(candidate.symbol)} className="border border-border p-2 text-muted-foreground hover:text-primary" aria-label={`Open ${candidate.symbol} chart`}><LineChart className="h-4 w-4" /></button>
          <GradeBadge grade={candidate.grade} score={candidate.decision_score ?? candidate.setup_score} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-px border-b border-border bg-border sm:grid-cols-4">
        <div className="bg-card p-3"><div className="text-[10px] font-medium uppercase text-muted-foreground">Instrument / strike</div><div className="mt-1 break-all text-sm font-semibold">{plan?.contract ? `${plan.contract.underlying} ${plan.contract.expiry} ${plan.contract.strike} ${plan.contract.right}` : plan?.instrument || candidate.instrument || "Pending chain"}</div></div>
        <div className="bg-card p-3"><div className="text-[10px] font-medium uppercase text-muted-foreground">Entry trigger</div><div className="mt-1 text-sm font-semibold tabular-nums">{plan?.entry_trigger ?? candidate.entry ?? "Wait for trigger"}</div></div>
        <div className="bg-card p-3"><div className="text-[10px] font-medium uppercase text-muted-foreground">Invalidation / stop</div><div className="mt-1 text-sm font-semibold tabular-nums">{plan?.invalidation ?? candidate.stop ?? "Not confirmed"}</div></div>
        <div className="bg-card p-3"><div className="text-[10px] font-medium uppercase text-muted-foreground">Target 1</div><div className="mt-1 text-sm font-semibold tabular-nums">{target ?? "Not confirmed"}</div></div>
      </div>
      <div className="space-y-3 p-3">
        <div className="grid grid-cols-3 gap-3 border-b border-border pb-3">
          <Metric labelText="Setup" value={number(candidate.setup_score, 0)} detail={candidate.setup_grade ?? "quality"} />
          <Metric labelText="Timing" value={number(candidate.timing_score, 0)} detail={label(candidate.actionability)} />
          <Metric labelText="Execution" value={number(candidate.execution_score, 0)} detail={label(candidate.instrument_status)} />
        </div>
        <PositionSizer equity={equity} entry={plan?.entry_trigger ?? candidate.entry} stop={plan?.invalidation ?? candidate.stop} multiplier={sizeMultiplier} unavailableReason={optionRiskUnavailable ? "Need executable contract max-loss" : undefined} />
        <div className={cn("border-l-4 px-3 py-2 text-sm", tone(candidate.actionability ?? candidate.lane))}>
          <div className="font-semibold">{label(candidate.actionability ?? candidate.lane)}</div>
          <div className="mt-1 text-xs">{candidate.next_action ?? "Revalidate all fields before a shadow decision."}</div>
          {(candidate.reward_remaining_r != null || candidate.move_consumed_pct != null) && <div className="mt-1 text-xs tabular-nums">Reward left {number(candidate.reward_remaining_r, 2)}R · path consumed {number(candidate.move_consumed_pct, 0)}%</div>}
        </div>
        <FactorGrid candidate={candidate} />
        <div className="grid gap-3 border-t border-border pt-3 text-xs sm:grid-cols-2">
          <div><span className="font-semibold">Execution:</span> <span className="text-muted-foreground">{label(plan?.entry_instruction ?? candidate.order_style)}</span><div className="mt-1 text-muted-foreground">Window: {plan?.time_window ?? "Revalidate now"}</div></div>
          <div><span className="font-semibold">Conditional probability:</span> <span className="text-muted-foreground">{probability?.value == null ? "Not calibrated" : `${number(probability.value, 1)}%`}</span><div className="mt-1 text-muted-foreground">{probability?.label ?? "Setup score is not probability"}{probability?.lower_bound != null ? ` · conservative bound ${number(probability.lower_bound, 1)}%` : ""}{probability?.sample_size ? ` · n=${probability.sample_size}` : ""}{probability?.independent_dates ? ` · ${probability.independent_dates} dates` : ""}</div></div>
        </div>
        <div className="border-t border-border pt-3">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">Why it ranks / why to wait</div>
          <div className="mt-2 flex flex-wrap gap-1.5">{candidate.reasons.slice(0, 4).map((reason) => <span key={reason} className="border border-border bg-muted/30 px-2 py-1 text-xs">{label(reason)}</span>)}</div>
          {candidate.blockers.length > 0 && <div className="mt-2 text-xs font-medium text-danger">Do not enter yet: {candidate.blockers.slice(0, 4).map(label).join(" · ")}</div>}
        </div>
      </div>
    </section>
  );
}

function CandidateRow({ candidate, expanded, onToggle, onOpenChart, catalysts = [] }: { candidate: TradingCandidate; expanded: boolean; onToggle: () => void; onOpenChart: (symbol: string) => void; catalysts?: string[] }) {
  const pinSymbol = useDashboardPrefs((state) => state.pinSymbol);
  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        className="grid w-full grid-cols-[64px_minmax(160px,1.4fr)_70px_110px_100px_84px] items-center gap-3 px-3 py-3 text-left text-sm hover:bg-muted/30 max-lg:grid-cols-[60px_minmax(150px,1fr)_60px_90px] max-lg:[&>*:nth-child(5)]:hidden max-lg:[&>*:nth-child(6)]:hidden"
      >
        <span className="font-semibold">{candidate.symbol}</span>
        <span className="min-w-0">
          <span className="block truncate font-medium">{label(candidate.setup)}</span>
          <span className="block truncate text-xs text-muted-foreground">{label(candidate.source)} · {label(candidate.direction)}{catalysts.length ? ` · catalyst: ${catalysts.join(" / ")}` : ""}</span>
        </span>
        <span className="font-bold tabular-nums">{candidate.grade ?? "--"}</span>
        <StatusPill>{candidate.actionability ?? candidate.lane}</StatusPill>
        <span className="tabular-nums">{candidate.decision_score == null ? "--" : `${number(candidate.decision_score, 0)}/100`}</span>
        <span className={cn("text-xs font-medium", candidate.blockers.length ? "text-danger" : "text-success")}>
          {candidate.blockers.length ? `${candidate.blockers.length} blocks` : "clear"}
        </span>
      </button>
      {expanded && (
        <div className="grid gap-4 border-t border-border bg-muted/20 px-3 py-4 md:grid-cols-3">
          <div>
            <div className="text-[11px] font-medium uppercase text-muted-foreground">Trade plan</div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Instrument</dt><dd className="break-all text-right">{candidate.trade_plan?.instrument || candidate.instrument || "--"}</dd>
              <dt className="text-muted-foreground">Entry</dt><dd className="text-right tabular-nums">{candidate.trade_plan?.entry_trigger ?? candidate.entry ?? "--"}</dd>
              <dt className="text-muted-foreground">Stop</dt><dd className="text-right tabular-nums">{candidate.trade_plan?.invalidation ?? candidate.stop ?? "--"}</dd>
              <dt className="text-muted-foreground">Target</dt><dd className="text-right tabular-nums">{candidate.trade_plan?.targets?.[0]?.price ?? candidate.target ?? "--"}</dd>
              <dt className="text-muted-foreground">Order</dt><dd className="text-right">{label(candidate.order_style || "revalidate")}</dd>
            </dl>
          </div>
          <div className="md:col-span-3 border-t border-border pt-3"><FactorGrid candidate={candidate} /></div>
          <div>
            <div className="text-[11px] font-medium uppercase text-muted-foreground">Reasons</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(candidate.reasons.length ? candidate.reasons : ["no positive reason supplied"]).map((reason) => (
                <span key={reason} className="border border-border bg-background px-2 py-1 text-xs text-muted-foreground">{label(reason)}</span>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[11px] font-medium uppercase text-muted-foreground">Blocking conditions</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(candidate.blockers.length ? candidate.blockers : ["none"]).map((blocker) => (
                <span key={blocker} className={cn("border px-2 py-1 text-xs", blocker === "none" ? tone("ready") : tone("blocked"))}>{label(blocker)}</span>
              ))}
            </div>
          </div>
          <details className="md:col-span-3">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Evidence payload</summary>
            <pre className="mt-2 max-h-56 overflow-auto border border-border bg-background p-3 text-xs">{JSON.stringify(candidate.evidence, null, 2)}</pre>
          </details>
          <div className="flex gap-2 md:col-span-3">
            <button type="button" onClick={() => onOpenChart(candidate.symbol)} className="inline-flex items-center gap-2 border border-border px-3 py-2 text-xs font-semibold hover:border-primary hover:text-primary"><LineChart className="h-4 w-4" />Open chart</button>
            <button type="button" onClick={() => pinSymbol(candidate.symbol)} className="inline-flex items-center gap-2 border border-border px-3 py-2 text-xs font-semibold hover:border-primary hover:text-primary"><Pin className="h-4 w-4" />Pin</button>
          </div>
        </div>
      )}
    </div>
  );
}

function SourceRow({ source, onInspect }: { source: TradingSource; onInspect: () => void }) {
  return (
    <div className="grid grid-cols-[minmax(150px,1fr)_110px_100px_80px] items-center gap-3 border-b border-border px-3 py-2.5 text-sm last:border-b-0 max-sm:grid-cols-[1fr_90px] max-sm:[&>*:nth-child(3)]:hidden max-sm:[&>*:nth-child(4)]:hidden">
      <button type="button" onClick={onInspect} className="flex min-w-0 items-center gap-2 text-left hover:text-primary">
        <FileJson className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0"><span className="block truncate">{label(source.name)}</span><span className="block truncate text-[10px] text-muted-foreground">{source.filename}:{source.line_reference ?? "--"} · spec {source.spec_hash?.slice(0, 18) ?? "unavailable"}</span></span>
      </button>
      <StatusPill>{source.freshness}</StatusPill>
      <span className="text-xs tabular-nums text-muted-foreground">{age(source.age_seconds)}</span>
      <span className={cn("text-xs font-medium", source.available ? "text-success" : "text-danger")}>{source.available ? "available" : "missing"}</span>
    </div>
  );
}

export function TradingCockpit() {
  const [data, setData] = useState<TradingDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [filter, setFilter] = useState<CandidateFilter>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sourceName, setSourceName] = useState<string | null>(null);
  const [sourcePayload, setSourcePayload] = useState<Record<string, unknown> | null>(null);
  const [chartSymbol, setChartSymbol] = useState<string | null>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  const [liveReport, setLiveReport] = useState<LiveOpportunityReport | null>(null);
  const [streamConnection, setStreamConnection] = useState<"connecting" | "live" | "degraded" | "snapshot">("connecting");
  const searchRef = useRef<HTMLInputElement | null>(null);
  const previousCommandState = useRef<string | null>(null);
  const previousReconciliationDiff = useRef<string | null>(null);
  const hotkeysEnabled = useDashboardPrefs((state) => state.hotkeys_enabled);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const response = await api.getTradingDashboard();
      setData(response);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Dashboard feed unavailable");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), (data?.refresh_seconds ?? 15) * 1000);
    return () => window.clearInterval(timer);
  }, [load, data?.refresh_seconds]);

  useEffect(() => {
    let active = true;
    let hasStreamPayload = false;
    const snapshot = api.getTradingOpportunities?.();
    if (snapshot) {
      void snapshot.then((report) => {
        if (!active || hasStreamPayload) return;
        setLiveReport(report);
        setStreamConnection("snapshot");
      }).catch(() => {
        if (active) setStreamConnection("degraded");
      });
    }
    if (typeof EventSource === "undefined" || !api.tradingOpportunityStreamUrl) {
      return () => { active = false; };
    }
    const source = new EventSource(api.tradingOpportunityStreamUrl());
    const onOpportunity = (event: MessageEvent<string>) => {
      try {
        const report = JSON.parse(event.data) as LiveOpportunityReport;
        if (!active) return;
        hasStreamPayload = true;
        setLiveReport(report);
        setStreamConnection("live");
      } catch {
        if (active) setStreamConnection("degraded");
      }
    };
    source.addEventListener("opportunity", onOpportunity as EventListener);
    source.onopen = () => { if (active && !hasStreamPayload) setStreamConnection("connecting"); };
    source.onerror = () => { if (active) setStreamConnection("degraded"); };
    return () => {
      active = false;
      source.close();
    };
  }, []);

  useEffect(() => {
    const next = data?.command_card?.state;
    if (!next) return;
    const previous = previousCommandState.current;
    if (previous && previous !== next) {
      if (next === "READY_TO_REVIEW") toast.success("A setup is ready to review", { description: data?.command_card?.symbol ?? undefined });
      else if (next === "STAND_ASIDE" || next === "INVALID") toast.warning(`Decision state changed to ${label(next)}`);
      else toast.info(`Decision state changed to ${label(next)}`);
    }
    previousCommandState.current = next;
  }, [data?.command_card?.state, data?.command_card?.symbol]);

  useEffect(() => {
    const reconciliation = data?.operations?.reconciliation_status;
    if (!reconciliation || reconciliation.diff_count_24h <= 0 || !reconciliation.last_diff_at) return;
    if (previousReconciliationDiff.current !== reconciliation.last_diff_at) {
      toast.warning("Broker reconciliation mismatch", {
        description: `${reconciliation.diff_count_24h} difference(s) recorded in the last 24 hours. Stand aside until resolved.`,
      });
      previousReconciliationDiff.current = reconciliation.last_diff_at;
    }
  }, [data?.operations?.reconciliation_status]);

  const hotkeyBindings = useMemo(() => ({
    refresh: () => void load(true),
    focusSearch: () => { setView("setups"); window.setTimeout(() => searchRef.current?.focus(), 0); },
    toggleLegend: () => setLegendOpen((value) => !value),
    selectTab: (index: number) => { const next = VIEWS[index]; if (next) setView(next.id); },
  }), [load]);
  useHotkeys(hotkeysEnabled, hotkeyBindings);

  const inspectSource = useCallback(async (name: string) => {
    setSourceName(name);
    setSourcePayload(null);
    try {
      setSourcePayload(await api.getTradingDashboardSource(name));
    } catch (caught) {
      setSourcePayload({ error: caught instanceof Error ? caught.message : "Source unavailable" });
    }
  }, []);

  const candidates = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLowerCase();
    return data.candidates.filter((candidate) => {
      const matchesQuery = !needle || `${candidate.symbol} ${candidate.setup} ${candidate.source}`.toLowerCase().includes(needle);
      if (!matchesQuery) return false;
      if (filter === "ready") return candidate.actionability === "shadow_ready";
      if (filter === "watch") return candidate.actionability === "wait" || ["watch", "armed", "qualified_scan", "precision_watch"].includes(candidate.lane);
      if (filter === "blocked") return candidate.blockers.length > 0 || candidate.lane === "blocked";
      return true;
    });
  }, [data, filter, query]);

  if (loading && !data) {
    return <div className="space-y-4 p-5"><Skeleton className="h-16 w-full" /><SkeletonMetrics /><Skeleton className="h-72 w-full" /></div>;
  }

  if (!data) {
    return (
      <div className="mx-auto mt-20 max-w-lg border border-danger/30 bg-danger/10 p-5 text-sm text-danger">
        <div className="flex items-center gap-2 font-semibold"><XCircle className="h-4 w-4" />Cockpit unavailable</div>
        <p className="mt-2">{error}</p>
        <button type="button" onClick={() => void load(true)} className="mt-4 border border-danger/30 px-3 py-2 font-medium">Retry</button>
      </div>
    );
  }

  const best = data.headline.best_setup;
  const board = data.trade_board ?? {
    score_definition: "Setup quality score; not probability of profit.",
    probability_policy: "No percentage without adequate calibration.",
    stocks: data.candidates.filter((item) => item.asset_class === "equity"),
    options: [
      ...(best && ["option", "equity_option", "equity_or_option"].includes(best.asset_class) ? [best] : []),
      ...data.candidates.filter((item) => ["option", "equity_or_option"].includes(item.asset_class)),
    ],
    futures: data.candidates.filter((item) => item.asset_class === "future"),
    review_fields: [],
  };
  const openTrades = Object.values(data.portfolio.open_trades ?? {}).reduce((sum, row) => sum + Number(row.open ?? 0), 0);
  const taskHealth = data.operations.health;
  const unhealthyTasks = data.operations.tasks.filter((task) => String(task.health ?? "").toLowerCase() !== "ok");
  const discovery = data.discovery;
  const discoveryCoverage = discovery?.coverage ?? {};
  const moveCoverage = discovery?.move_coverage ?? {};
  const tickerSlots = data.candidates.slice(0, 5).map((candidate) => ({ symbol: candidate.symbol, state: candidate.actionability ?? candidate.lane, score: candidate.decision_score ?? candidate.setup_score }));
  const inspectedSource = data.sources.find((item) => item.name === sourceName);

  return (
    <div className="min-h-full bg-background">
      <header className="border-b border-border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div>
            <div className="flex items-center gap-2">
              <Gauge className="h-5 w-5 text-primary" />
              <h1 className="text-lg font-semibold">Daily Market Decision Board</h1>
              <StatusPill>{data.mode}</StatusPill>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">Updated {new Date(data.generated_at).toLocaleString()} · polls every {data.refresh_seconds}s</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn("inline-flex items-center gap-1.5 border px-2.5 py-1.5 text-xs font-medium", data.authority.can_submit_orders ? tone("ready") : tone("blocked"))}>
              <ShieldCheck className="h-3.5 w-3.5" />{data.authority.can_submit_orders ? "order authority" : "read only"}
            </span>
            <button type="button" onClick={() => void load(true)} className="border border-border p-2 text-muted-foreground hover:bg-muted hover:text-foreground" title="Refresh dashboard">
              <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
            </button>
          </div>
        </div>
        <div className="flex overflow-x-auto px-5">
          {VIEWS.map((item) => (
            <button key={item.id} type="button" onClick={() => setView(item.id)} className={cn("border-b-2 px-4 py-2 text-sm font-medium", view === item.id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>{item.label}</button>
          ))}
        </div>
      </header>

      {error && <div className="border-b border-warning/30 bg-warning/10 px-5 py-2 text-xs text-warning">Refresh warning: {error}. Showing the last successful snapshot.</div>}

      <TickerStrip slots={tickerSlots} ageSeconds={data.command_card?.evidence_age_seconds ?? null} onSelect={setChartSymbol} />
      <CatalystStrip catalysts={data.evidence.catalysts_today} />

      <main className="space-y-5 p-3 sm:p-5">
        {view === "setups" && (
          <section className={cn("border-l-4 px-4 py-4", best ? "border-success bg-success/5" : "border-warning bg-warning/5")}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground"><Target className="h-4 w-4" />Best eligible setup now</div>
                <div className="mt-2 text-xl font-semibold">{best ? `${best.symbol} · ${label(best.setup)}` : "No entry clears every gate"}</div>
                <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{data.headline.message}</p>
              </div>
              {best ? <StatusPill>{best.lane}</StatusPill> : <StatusPill>stand aside</StatusPill>}
            </div>
            {best && (
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:max-w-3xl">
                <Metric labelText="Entry" value={best.entry?.toString() ?? "--"} />
                <Metric labelText="Stop" value={best.stop?.toString() ?? "--"} />
                <Metric labelText="Target" value={best.target?.toString() ?? "--"} />
                <Metric labelText="Reward / risk" value={best.reward_risk ? `${number(best.reward_risk)}R` : "--"} />
              </div>
            )}
          </section>
        )}

        {view === "overview" && (
          <ErrorBoundary>
          <div className="space-y-5">
            <section className="border-y border-border bg-muted/20 px-3 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="text-sm font-semibold">Today&apos;s ranked decision packet</div><div className="mt-1 max-w-4xl text-xs text-muted-foreground">{board.score_definition} {board.probability_policy}</div></div>
                <div className="flex items-center gap-2 text-xs"><StatusPill>{data.ranking_policy?.mode ?? data.headline.state}</StatusPill><span className="text-muted-foreground">{data.ranking_policy ? `${data.ranking_policy.qualified_candidate_count} probability-qualified now` : "Every plan is revalidated before entry"}</span></div>
              </div>
            </section>
            <CommandCard command={data.command_card} dealer={data.dealer_regime} blockers={data.operations.risk_blockers} />
            <DecisionDesk data={data.decision_desk} />
            <LiveOpportunityPanel report={liveReport} connection={streamConnection} onOpenChart={setChartSymbol} />
            <SimpleSignalBoard signals={data.simple_signals?.signals ?? []} />
            <section className="border-y border-border py-4">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold"><Search className="h-4 w-4 text-primary" />Market-wide discovery coverage</div>
                  <p className="mt-1 text-xs text-muted-foreground">Official movers and most-actives, then 5-minute structure, spread, dollar liquidity, volume pace, and catalyst checks.</p>
                </div>
                <StatusPill>{discovery?.health ?? "missing"}</StatusPill>
              </div>
              <div className="grid grid-cols-2 gap-x-5 gap-y-4 md:grid-cols-3 xl:grid-cols-6">
                <Metric labelText="Discovered" value={String(discoveryCoverage.unique_symbols_discovered ?? 0)} detail="unique market symbols" />
                <Metric labelText="Snapshots" value={String(discoveryCoverage.snapshot_symbols ?? 0)} detail={`${number(discoveryCoverage.snapshot_coverage_pct)}% coverage`} />
                <Metric labelText="5m evaluated" value={String(discoveryCoverage.symbols_evaluated ?? 0)} detail={`${discoveryCoverage.symbols_with_5m_bars ?? 0} with bars`} />
                <Metric labelText="Precision watch" value={String(discoveryCoverage.precision_watch_count ?? 0)} detail="quality watch, not entry" />
                <Metric labelText="Mover audit" value={String(moveCoverage.movers_audited ?? 0)} detail={`${moveCoverage.radar_snapshots_reviewed ?? 0} radar snapshots`} />
                <Metric labelText="Early / late" value={`${moveCoverage.classification_counts?.detected_early ?? 0} / ${moveCoverage.classification_counts?.detected_late ?? 0}`} detail={`${moveCoverage.classification_counts?.missed ?? 0} missed`} />
              </div>
            </section>
            <section className="grid gap-4 xl:grid-cols-3">
              <PlanCard title="Best stock setup" candidate={board.stocks[0]} equity={Number(data.account.equity ?? 0)} onOpenChart={setChartSymbol} />
              <PlanCard title="Best options setup" candidate={board.options[0]} equity={Number(data.account.equity ?? 0)} onOpenChart={setChartSymbol} />
              <PlanCard title="Best futures setup" candidate={board.futures[0]} equity={Number(data.account.equity ?? 0)} onOpenChart={setChartSymbol} />
            </section>
            <section className="grid grid-cols-2 gap-x-5 gap-y-4 border-y border-border py-4 md:grid-cols-4 xl:grid-cols-8">
              <Metric labelText="Market" value={label(data.market.classification)} detail={`force ${number(data.market.force_score)}`} />
              <Metric labelText="Breadth" value={data.market.pct_above_50dma == null ? "--" : `${number(data.market.pct_above_50dma)}%`} detail={label(data.market.breadth_status)} />
              <Metric labelText="Leadership" value={data.market.leading_sectors.slice(0, 3).join(" · ") || "--"} detail={label(data.market.sector_leadership)} />
              <Metric labelText="Equity" value={money(data.account.equity)} detail={`BP ${money(data.account.buying_power)}`} />
              <Metric labelText="Open trades" value={String(openTrades)} detail={data.portfolio.position_integrity?.status ? `integrity ${label(data.portfolio.position_integrity.status)}` : undefined} />
              <Metric labelText="Paper ready" value={String(data.authority.paper_signal_count)} detail="fully gated" />
              <Metric labelText="System health" value={label(data.operations.status)} detail={`${taskHealth.ok ?? 0}/${data.operations.task_count} healthy`} />
              <Metric labelText="Stale inputs" value={String(data.operations.stale_source_count)} detail={`${data.sources.length} tracked`} />
            </section>

            <section className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
              <div className="border border-border bg-card">
                <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                  <div className="flex items-center gap-2 text-sm font-semibold"><TrendingUp className="h-4 w-4 text-primary" />Top setup queue</div>
                  <button type="button" onClick={() => setView("setups")} className="text-xs font-medium text-primary hover:underline">View all</button>
                </div>
                <div className="grid grid-cols-[64px_minmax(160px,1.4fr)_70px_110px_100px_84px] gap-3 border-b border-border bg-muted/30 px-3 py-2 text-[11px] font-medium uppercase text-muted-foreground max-lg:grid-cols-[60px_minmax(150px,1fr)_60px_90px] max-lg:[&>*:nth-child(5)]:hidden max-lg:[&>*:nth-child(6)]:hidden">
                  <span>Symbol</span><span>Setup</span><span>Grade</span><span>Lane</span><span>Score</span><span>Gates</span>
                </div>
                {data.candidates.slice(0, 8).map((candidate) => <CandidateRow key={`${candidate.source}-${candidate.symbol}-${candidate.setup}`} candidate={candidate} expanded={expanded === `${candidate.source}-${candidate.symbol}-${candidate.setup}`} onToggle={() => setExpanded(expanded === `${candidate.source}-${candidate.symbol}-${candidate.setup}` ? null : `${candidate.source}-${candidate.symbol}-${candidate.setup}`)} onOpenChart={setChartSymbol} catalysts={catalystLabels(data.evidence.catalysts_today, candidate.symbol)} />)}
              </div>

              <div className="space-y-5">
                <section className="border border-border bg-card">
                  <div className="flex items-center gap-2 border-b border-border px-3 py-2.5 text-sm font-semibold"><Activity className="h-4 w-4 text-primary" />Market forces</div>
                  <div className="divide-y divide-border text-sm">
                    <div className="flex justify-between px-3 py-2.5"><span className="text-muted-foreground">Regime</span><StatusPill>{data.market.classification ?? "unknown"}</StatusPill></div>
                    <div className="flex justify-between px-3 py-2.5"><span className="text-muted-foreground">Risk veto</span><StatusPill>{data.market.risk_veto?.active ? "active" : "clear"}</StatusPill></div>
                    <div className="flex justify-between px-3 py-2.5"><span className="text-muted-foreground">Breadth</span><span>{label(data.market.breadth_status)}</span></div>
                    <div className="flex justify-between px-3 py-2.5"><span className="text-muted-foreground">Sector lead</span><span>{data.market.leading_sectors.join(", ") || "--"}</span></div>
                    <div className="flex justify-between px-3 py-2.5"><span className="text-muted-foreground">High-impact horizon</span><span>{data.market.high_impact_days_ahead.length}</span></div>
                  </div>
                </section>
                <section className="border border-border bg-card">
                  <div className="flex items-center gap-2 border-b border-border px-3 py-2.5 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-primary" />Execution state</div>
                  <div className="space-y-2 p-3 text-sm">
                    <div className="flex items-center gap-2"><XCircle className="h-4 w-4 text-danger" /><span>Dashboard order submission disabled</span></div>
                    <div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-success" /><span>Paper consumers revalidate all gates</span></div>
                    <div className="flex items-center gap-2"><Database className="h-4 w-4 text-info" /><span>{data.sources.filter((source) => source.available).length}/{data.sources.length} report sources available</span></div>
                    <p className="border-t border-border pt-2 text-xs text-muted-foreground">{data.authority.message}</p>
                  </div>
                </section>
                <SocialEvidencePanel social={data.evidence.social} />
              </div>
            </section>
          </div>
          </ErrorBoundary>
        )}

        {(view === "stocks" || view === "options" || view === "futures") && (
          <div className="space-y-4">
            <section className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
              <div><h2 className="text-base font-semibold">{view === "stocks" ? "Stock plans" : view === "options" ? "Options plans" : "Futures plans"}</h2><p className="mt-1 text-xs text-muted-foreground">Ranked by decision quality: setup, timing, remaining reward, liquidity, and instrument readiness. Late moves remain visible but are never promoted.</p></div>
              <StatusPill>{view === "futures" ? "research and practice" : "paper decision support"}</StatusPill>
            </section>
            <div className="grid gap-4 xl:grid-cols-2">
              {(view === "stocks" ? board.stocks : view === "options" ? board.options : board.futures).map((candidate, index) => <PlanCard key={candidate.plan_id ?? `${candidate.source}-${candidate.symbol}-${index}`} title={`Rank ${index + 1}`} candidate={candidate} equity={Number(data.account.equity ?? 0)} onOpenChart={setChartSymbol} />)}
            </div>
            {view === "options" && <OptionsContextPanel context={data.options_context} />}
          </div>
        )}

        {view === "setups" && (
          <section className="border border-border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-3">
              <div className="flex items-center gap-1 border border-border bg-muted/30 p-0.5">
                {(["all", "ready", "watch", "blocked"] as CandidateFilter[]).map((item) => (
                  <button key={item} type="button" onClick={() => setFilter(item)} className={cn("px-3 py-1.5 text-xs font-medium", filter === item ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>{label(item)}</button>
                ))}
              </div>
              <label className="flex min-w-[220px] items-center gap-2 border border-border bg-background px-2.5 py-1.5 text-sm">
                <Search className="h-4 w-4 text-muted-foreground" />
                <input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Symbol or setup" className="w-full bg-transparent outline-none placeholder:text-muted-foreground" />
              </label>
            </div>
            <div className="grid grid-cols-[64px_minmax(160px,1.4fr)_70px_110px_100px_84px] gap-3 border-b border-border bg-muted/30 px-3 py-2 text-[11px] font-medium uppercase text-muted-foreground max-lg:grid-cols-[60px_minmax(150px,1fr)_60px_90px] max-lg:[&>*:nth-child(5)]:hidden max-lg:[&>*:nth-child(6)]:hidden">
              <span>Symbol</span><span>Setup</span><span>Grade</span><span>Lane</span><span>Score</span><span>Gates</span>
            </div>
            {candidates.map((candidate) => {
              const key = `${candidate.source}-${candidate.symbol}-${candidate.setup}`;
              return <CandidateRow key={key} candidate={candidate} expanded={expanded === key} onToggle={() => setExpanded(expanded === key ? null : key)} onOpenChart={setChartSymbol} catalysts={catalystLabels(data.evidence.catalysts_today, candidate.symbol)} />;
            })}
            {candidates.length === 0 && <div className="p-8 text-center text-sm text-muted-foreground">No setup matches this filter.</div>}
          </section>
        )}

        {view === "risk" && (
          <div className="grid gap-5 xl:grid-cols-2">
            <section className="border border-border bg-card">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2.5 text-sm font-semibold"><WalletCards className="h-4 w-4 text-primary" />Account & exposure</div>
              <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3">
                <Metric labelText="Equity" value={money(data.account.equity)} />
                <Metric labelText="Buying power" value={money(data.account.buying_power)} />
                <Metric labelText="Day change" value={money(data.account.day_change)} />
                <Metric labelText="Open trades" value={String(openTrades)} />
                <Metric labelText="Gross exposure" value={`${number(data.portfolio.gross_pct_equity)}%`} />
                <Metric labelText="Risk posture" value={label(data.portfolio.risk_level ?? "unknown")} />
              </div>
              <details className="border-t border-border p-3">
                <summary className="cursor-pointer text-sm font-medium">Position reconciliation</summary>
                <pre className="mt-3 max-h-72 overflow-auto bg-muted/30 p-3 text-xs">{JSON.stringify(data.portfolio.position_integrity ?? {}, null, 2)}</pre>
              </details>
            </section>
            <section className="border border-border bg-card">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2.5 text-sm font-semibold"><Bot className="h-4 w-4 text-primary" />Bot operations</div>
              <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
                <Metric labelText="Healthy" value={String(taskHealth.ok ?? 0)} />
                <Metric labelText="Stale" value={String(taskHealth.stale ?? 0)} />
                <Metric labelText="Missing" value={String(taskHealth.missing ?? 0)} />
                <Metric labelText="Audit issues" value={String(data.operations.audit_issue_count)} />
              </div>
              <div className="border-t border-border p-3">
                <div className="text-[11px] font-medium uppercase text-muted-foreground">Items needing attention</div>
                <div className="mt-2 space-y-2">
                  {unhealthyTasks.length === 0 ? (
                    <div className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="h-4 w-4" />All tracked tasks report healthy</div>
                  ) : unhealthyTasks.map((task, index) => (
                    <div key={`${task.name}-${index}`} className="flex items-start gap-2 border border-danger/20 bg-danger/5 p-2 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /><span>{String(task.name ?? "Task")}: {label(task.health)}</span></div>
                  ))}
                  {data.operations.risk_blockers.map((blocker) => <div key={blocker} className="flex items-start gap-2 border border-danger/20 bg-danger/5 p-2 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /><span>{label(blocker)}</span></div>)}
                </div>
              </div>
            </section>
            <section className="border border-border bg-card xl:col-span-2">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2.5 text-sm font-semibold"><Clock3 className="h-4 w-4 text-primary" />Task schedule and logger coverage</div>
              <div className="max-h-[430px] overflow-auto">
                <div className="grid grid-cols-[minmax(170px,1fr)_90px_90px_minmax(150px,1fr)] gap-3 border-b border-border bg-muted/30 px-3 py-2 text-[11px] font-medium uppercase text-muted-foreground"><span>Process</span><span>Health</span><span>Rows</span><span>Next run</span></div>
                {data.operations.tasks.map((task, index) => {
                  const taskStatus = (task.task_status ?? {}) as Record<string, unknown>;
                  return <div key={`${task.name}-${index}`} className="grid grid-cols-[minmax(170px,1fr)_90px_90px_minmax(150px,1fr)] gap-3 border-b border-border px-3 py-2.5 text-sm last:border-b-0"><span className="truncate">{String(task.name ?? "unknown")}</span><StatusPill>{String(task.health ?? "unknown")}</StatusPill><span className="tabular-nums text-muted-foreground">{String(task.row_count ?? "--")}</span><span className="truncate text-xs text-muted-foreground">{String(taskStatus.next_run_time ?? "not scheduled")}</span></div>;
                })}
              </div>
            </section>
          </div>
        )}

        {view === "sources" && (
          <div className="grid gap-5 xl:grid-cols-[minmax(420px,0.9fr)_1.1fr]">
            <section className="border border-border bg-card">
              <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                <div className="flex items-center gap-2 text-sm font-semibold"><Database className="h-4 w-4 text-primary" />Source inventory</div>
                <span className="text-xs text-muted-foreground">Select to inspect raw report</span>
              </div>
              <div className="grid grid-cols-[minmax(150px,1fr)_110px_100px_80px] gap-3 border-b border-border bg-muted/30 px-3 py-2 text-[11px] font-medium uppercase text-muted-foreground max-sm:grid-cols-[1fr_90px] max-sm:[&>*:nth-child(3)]:hidden max-sm:[&>*:nth-child(4)]:hidden"><span>Source</span><span>Freshness</span><span>Age</span><span>State</span></div>
              <div className="max-h-[650px] overflow-auto">{data.sources.map((source) => <SourceRow key={source.name} source={source} onInspect={() => void inspectSource(source.name)} />)}</div>
            </section>
            <section className="min-w-0 border border-border bg-card">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2.5 text-sm font-semibold"><FileJson className="h-4 w-4 text-primary" />{sourceName ? label(sourceName) : "Raw source inspector"}</div>
              {sourceName ? <><div className="border-b border-border bg-muted/20 px-4 py-2 text-[10px] text-muted-foreground">{inspectedSource?.path ?? "path unavailable"}:{inspectedSource?.line_reference ?? "--"} · report {inspectedSource?.report_hash ?? "hash unavailable"} · spec {inspectedSource?.spec_hash ?? "unavailable"}</div><pre className="max-h-[660px] overflow-auto p-4 text-xs leading-5">{sourcePayload ? JSON.stringify(sourcePayload, null, 2) : "Loading source..."}</pre></> : <div className="p-8 text-sm text-muted-foreground">Choose a source to inspect every field in its current report.</div>}
            </section>
          </div>
        )}

        <footer className="border-t border-border pt-3 text-xs text-muted-foreground">
          {data.warnings.join(" · ")}
        </footer>
      </main>
      {legendOpen && <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label="Keyboard shortcuts"><div className="w-full max-w-md border border-border bg-card p-5"><div className="flex items-center justify-between"><h2 className="font-bold">Keyboard shortcuts</h2><button type="button" onClick={() => setLegendOpen(false)} className="text-sm text-muted-foreground">Close</button></div><dl className="mt-4 grid grid-cols-[70px_1fr] gap-y-2 text-sm"><dt className="font-mono">1–7</dt><dd>Jump cockpit tabs</dd><dt className="font-mono">/</dt><dd>Focus setup search</dd><dt className="font-mono">r</dt><dd>Refresh dashboard</dd><dt className="font-mono">?</dt><dd>Toggle this legend</dd></dl></div></div>}
      <ChartDrawer symbol={chartSymbol} open={Boolean(chartSymbol)} onClose={() => setChartSymbol(null)} />
    </div>
  );
}
