import { AlertTriangle } from "lucide-react";

function readable(value: string): string {
  return value.replace(/_/g, " ");
}

export function BlockerChips({ blockers }: { blockers: string[] }) {
  if (!blockers.length) return null;
  return (
    <div className="mt-3" aria-label="Blocking conditions">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase text-danger">
        <AlertTriangle className="h-3.5 w-3.5" /> Stand-aside blockers
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {blockers.map((blocker) => (
          <span key={blocker} className="border border-danger/30 bg-danger/10 px-2 py-1 text-xs text-danger">
            {readable(blocker)}
          </span>
        ))}
      </div>
    </div>
  );
}

