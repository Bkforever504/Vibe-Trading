import { useDashboardPrefs } from "@/stores/dashboardPrefs";

interface PositionSizerProps {
  equity: number;
  entry: number | null | undefined;
  stop: number | null | undefined;
  multiplier?: number;
  unavailableReason?: string;
}

function usd(value: number): string {
  return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function PositionSizer({ equity, entry, stop, multiplier = 1, unavailableReason }: PositionSizerProps) {
  const riskPct = useDashboardPrefs((state) => state.risk_pct);
  const setRiskPct = useDashboardPrefs((state) => state.setRiskPct);
  const riskBudget = equity * (riskPct / 100);
  const perUnitRisk = !unavailableReason && entry != null && stop != null ? Math.abs(entry - stop) * multiplier : 0;
  const quantity = perUnitRisk > 0 ? Math.floor(riskBudget / perUnitRisk) : 0;
  const maxLoss = quantity * perUnitRisk;

  return (
    <div className="grid gap-3 border-t border-border pt-3 text-xs sm:grid-cols-[120px_1fr_1fr_1fr] sm:items-end">
      <label>
        <span className="block text-[10px] font-semibold uppercase text-muted-foreground">Risk %</span>
        <input
          aria-label="Risk percent"
          type="number"
          min="0.05"
          max="5"
          step="0.05"
          value={riskPct}
          onChange={(event) => setRiskPct(Number(event.target.value))}
          className="mt-1 w-full border border-border bg-background px-2 py-1.5 tabular-nums outline-none focus:border-primary"
        />
      </label>
      <div><div className="text-[10px] uppercase text-muted-foreground">Risk budget</div><div className="mt-1 font-semibold tabular-nums">{usd(riskBudget)}</div></div>
      <div><div className="text-[10px] uppercase text-muted-foreground">Max size</div><div className="mt-1 font-semibold tabular-nums">{perUnitRisk > 0 ? quantity : "--"}</div></div>
      <div><div className="text-[10px] uppercase text-muted-foreground">Max loss</div><div className="mt-1 font-semibold tabular-nums">{perUnitRisk > 0 ? `${usd(maxLoss)} · ${(maxLoss / equity * 100).toFixed(2)}%` : unavailableReason ?? "Need entry + stop"}</div></div>
    </div>
  );
}
