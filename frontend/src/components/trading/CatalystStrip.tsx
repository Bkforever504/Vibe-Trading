import type { TradingCatalystsToday } from "@/lib/api";

function eventLabel(event: unknown): string {
  if (typeof event === "string") return event;
  if (!event || typeof event !== "object") return "Scheduled market catalyst";
  const row = event as Record<string, unknown>;
  return String(row.event ?? row.name ?? row.title ?? row.label ?? "Scheduled market catalyst");
}

export function CatalystStrip({ catalysts }: { catalysts: TradingCatalystsToday }) {
  const events = catalysts.days.flatMap((day) => {
    const date = String(day.date ?? "Upcoming");
    const rows = Array.isArray(day.events) ? day.events : Array.isArray(day.items) ? day.items : [day];
    return rows.map((event) => ({ date, label: eventLabel(event) }));
  }).slice(0, 8);

  return (
    <section className="flex min-h-9 items-center gap-3 overflow-x-auto border-b border-border bg-warning/5 px-3 text-xs" aria-label="Today's catalysts">
      <span className="shrink-0 font-semibold uppercase text-warning">Catalysts · {catalysts.freshness}</span>
      {events.length ? events.map((event, index) => (
        <span key={`${event.date}-${event.label}-${index}`} className="shrink-0 border-l border-warning/30 pl-3">
          <span className="text-muted-foreground">{event.date}</span> · {event.label}
        </span>
      )) : <span className="text-muted-foreground">No sourced catalyst for today or tomorrow.</span>}
    </section>
  );
}

