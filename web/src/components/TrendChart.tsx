export type TrendPoint = {
  at: string;
  value: number;
};

function normalizedPoints(points: TrendPoint[]): string {
  if (points.length === 0) return "";
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1e-9);
  const left = 24;
  const top = 18;
  const width = 592;
  const height = 172;

  return points.map((point, index) => {
    const x = points.length === 1 ? left + width / 2 : left + (index / (points.length - 1)) * width;
    const y = top + height - ((point.value - min) / span) * height;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
}

export function TrendChart({ points, unit }: { points: TrendPoint[]; unit: string }) {
  const finite = points.filter((point) => Number.isFinite(point.value));
  if (finite.length === 0) {
    return <div className="trend-chart-empty">No measurements available for this range.</div>;
  }

  const values = finite.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const lastPoint = finite[finite.length - 1];
  const latest = lastPoint?.value ?? 0;
  const polyline = normalizedPoints(finite);

  return (
    <div className="trend-chart" aria-label={`Dose rate trend. Latest ${latest.toFixed(3)} ${unit}. Minimum ${min.toFixed(3)}. Maximum ${max.toFixed(3)}.`}>
      <svg viewBox="0 0 640 220" role="img" aria-labelledby="dose-trend-title dose-trend-desc">
        <title id="dose-trend-title">Dose rate trend</title>
        <desc id="dose-trend-desc">Recent dose rate measurements in {unit}.</desc>
        <line x1="24" y1="190" x2="616" y2="190" stroke="currentColor" opacity="0.16" />
        <line x1="24" y1="18" x2="24" y2="190" stroke="currentColor" opacity="0.16" />
        {finite.length === 1 ? (
          <circle cx="320" cy="104" r="5" fill="currentColor" />
        ) : (
          <polyline
            points={polyline}
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        )}
        <text x="24" y="212" fontSize="11" fill="currentColor" opacity="0.6">{finite[0]?.at ?? ""}</text>
        <text x="616" y="212" textAnchor="end" fontSize="11" fill="currentColor" opacity="0.6">{lastPoint?.at ?? ""}</text>
      </svg>
    </div>
  );
}
