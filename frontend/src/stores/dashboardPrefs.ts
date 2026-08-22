import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export const DEFAULT_WATCHLIST = ["SPY", "QQQ", "IWM", "AAPL", "NVDA"];

interface DashboardPrefsState {
  risk_pct: number;
  watchlist_symbols: string[];
  hotkeys_enabled: boolean;
  theme: "dark";
  setRiskPct: (value: number) => void;
  setHotkeysEnabled: (enabled: boolean) => void;
  pinSymbol: (symbol: string) => void;
  unpinSymbol: (symbol: string) => void;
  setWatchlistSymbols: (symbols: string[]) => void;
}

function cleanSymbols(symbols: string[]): string[] {
  return [...new Set(symbols.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean))].slice(0, 25);
}

export const useDashboardPrefs = create<DashboardPrefsState>()(
  persist(
    (set) => ({
      risk_pct: 0.5,
      watchlist_symbols: DEFAULT_WATCHLIST,
      hotkeys_enabled: true,
      theme: "dark",
      setRiskPct: (value) => set({ risk_pct: Math.min(5, Math.max(0.05, Number(value) || 0.5)) }),
      setHotkeysEnabled: (hotkeys_enabled) => set({ hotkeys_enabled }),
      pinSymbol: (symbol) => set((state) => ({
        watchlist_symbols: cleanSymbols([...state.watchlist_symbols, symbol]),
      })),
      unpinSymbol: (symbol) => set((state) => ({
        watchlist_symbols: state.watchlist_symbols.filter((item) => item !== symbol.trim().toUpperCase()),
      })),
      setWatchlistSymbols: (watchlist_symbols) => set({ watchlist_symbols: cleanSymbols(watchlist_symbols) }),
    }),
    {
      name: "vibe-dashboard-prefs-v1",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: ({ risk_pct, watchlist_symbols, hotkeys_enabled, theme }) => ({
        risk_pct,
        watchlist_symbols,
        hotkeys_enabled,
        theme,
      }),
    },
  ),
);

