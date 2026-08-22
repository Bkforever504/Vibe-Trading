import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_WATCHLIST, useDashboardPrefs } from "../dashboardPrefs";

describe("dashboardPrefs", () => {
  beforeEach(() => {
    localStorage.clear();
    useDashboardPrefs.setState({ risk_pct: 0.5, watchlist_symbols: [...DEFAULT_WATCHLIST], hotkeys_enabled: true, theme: "dark" });
  });

  it("deduplicates pins and normalizes symbols", () => {
    useDashboardPrefs.getState().pinSymbol(" spy ");
    expect(useDashboardPrefs.getState().watchlist_symbols.filter((symbol) => symbol === "SPY")).toHaveLength(1);
  });

  it("clamps risk and removes symbols", () => {
    useDashboardPrefs.getState().setRiskPct(99);
    useDashboardPrefs.getState().unpinSymbol("SPY");
    expect(useDashboardPrefs.getState().risk_pct).toBe(5);
    expect(useDashboardPrefs.getState().watchlist_symbols).not.toContain("SPY");
  });
});

