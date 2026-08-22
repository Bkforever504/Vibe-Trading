export const tradingPalette = {
  base: "hsl(var(--background))",
  surface: "hsl(var(--card))",
  elevated: "hsl(var(--muted))",
  border: "hsl(var(--border))",
  text: "hsl(var(--foreground))",
  mutedText: "hsl(var(--muted-foreground))",
  accent: "hsl(var(--primary))",
  confirmed: "hsl(var(--success))",
  waiting: "hsl(var(--warning))",
  blocked: "hsl(var(--danger))",
  information: "hsl(var(--info))",
} as const;

export const tradingSpacing = {
  strip: "2.75rem",
  panel: "1rem",
  rail: "20rem",
  drawer: "min(92vw, 52rem)",
} as const;

export const tradingFontStacks = {
  sans: ["Inter", "system-ui", "sans-serif"],
  mono: ["JetBrains Mono", "ui-monospace", "monospace"],
} as const;

