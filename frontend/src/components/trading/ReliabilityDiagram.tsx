import type { CalibrationReliabilityBin } from "@/lib/api";

export function ReliabilityDiagram({ bins }: { bins: CalibrationReliabilityBin[] }) {
  if (!bins.length) {
    return <div className="flex h-56 items-center justify-center border border-dashed border-border text-sm text-muted-foreground">Not enough out-of-sample observations to draw reliability.</div>;
  }
  const point = (value: number) => 22 + Math.max(0, Math.min(1, value)) * 206;
  return (
    <figure>
      <svg viewBox="0 0 250 250" className="mx-auto h-auto w-full max-w-[360px]" role="img" aria-label="Predicted probability versus observed win rate reliability diagram">
        <rect x="22" y="22" width="206" height="206" className="fill-muted/30 stroke-border" />
        <line x1="22" y1="228" x2="228" y2="22" className="stroke-muted-foreground" strokeDasharray="5 5" />
        {bins.map((bin, index) => (
          <g key={`${bin.mean_probability}-${index}`}>
            <line x1={point(bin.mean_probability)} y1={228} x2={point(bin.mean_probability)} y2={250 - point(bin.observed_rate)} className="stroke-primary/30" />
            <circle cx={point(bin.mean_probability)} cy={250 - point(bin.observed_rate)} r={Math.min(9, 3 + Math.sqrt(bin.count))} className="fill-primary stroke-background" />
          </g>
        ))}
        <text x="125" y="247" textAnchor="middle" className="fill-muted-foreground text-[9px]">Predicted probability</text>
        <text x="8" y="125" textAnchor="middle" transform="rotate(-90 8 125)" className="fill-muted-foreground text-[9px]">Observed win rate</text>
      </svg>
      <figcaption className="mt-2 text-center text-xs text-muted-foreground">Dashed line is perfect calibration. Bubble size represents bin count.</figcaption>
    </figure>
  );
}
