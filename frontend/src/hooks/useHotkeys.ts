import { useEffect } from "react";

export interface HotkeyBindings {
  refresh?: () => void;
  focusSearch?: () => void;
  toggleLegend?: () => void;
  selectTab?: (index: number) => void;
}

export function useHotkeys(enabled: boolean, bindings: HotkeyBindings): void {
  useEffect(() => {
    if (!enabled) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable;
      if (typing && event.key !== "Escape") return;
      if (event.key === "?") { event.preventDefault(); bindings.toggleLegend?.(); return; }
      if (event.key === "/") { event.preventDefault(); bindings.focusSearch?.(); return; }
      if (event.key.toLowerCase() === "r") { event.preventDefault(); bindings.refresh?.(); return; }
      const index = Number(event.key) - 1;
      if (index >= 0 && index < 7) { event.preventDefault(); bindings.selectTab?.(index); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [bindings, enabled]);
}

