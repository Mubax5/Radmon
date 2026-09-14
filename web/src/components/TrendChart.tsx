import { useMemo, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";

export type TrendPoint = {
  at: string;
  value: number;
};

type PlotPoint = TrendPoint & {
  x: number;
  y: number;
};

const WIDTH = 640;
const HEIGHT = 270;
const LEFT = 64;
const RIGHT = 18;
const TOP = 18;
const BOTTOM = 46;
const PLOT_WIDTH = WIDTH - LEFT - RIGHT;
const PLOT_HEIGHT = HEIGHT - TOP - BOTTOM;

function axisTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function tooltipTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

export function TrendChart({ points, unit }: { points: TrendPoint[]; unit: string }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const finite = useMemo(
    () => points.filter((point) => Number.isFinite(point.value)),
    [points],
  );

  const layout = useMemo(() => {
    if (!finite.length) {
      return {
        plotPoints: [] as PlotPoint[],
        min: 0,
        max: 0,
        yTicks: [] as Array<{ value: number; y: number }>,
        xTickIndexes: [] as number[],
      };
    }

    const values = finite.map((point) => point.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const rawSpan = max - min;
    const padding = rawSpan > 0 ? rawSpan * 0.12 : Math.max(Math.abs(max) * 0.08, 0.05);
    const yMin = Math.max(0, min - padding);
    const yMax = max + padding;
    const ySpan = Math.max(yMax - yMin, 1e-9);

    const times = finite.map((point) => Date.parse(point.at));
    const validTimeline = times.every(Number.isFinite) && finite.length > 1 && times[times.length - 1] !== times[0];
    const timeMin = validTimeline ? Math.min(...times) : 0;
    const timeMax = validTimeline ? Math.max(...times) : Math.max(1, finite.length - 1);
    const timeSpan = Math.max(timeMax - timeMin, 1);

    const plotPoints = finite.map((point, index) => {
      const position = validTimeline ? times[index] : index;
      const x = LEFT + ((position - timeMin) / timeSpan) * PLOT_WIDTH;
      const y = TOP + PLOT_HEIGHT - ((point.value - yMin) / ySpan) * PLOT_HEIGHT;
      return { ...point, x, y };
    });

    const yTicks = Array.from({ length: 5 }, (_, index) => {
      const ratio = index / 4;
      return {
        value: yMax - ratio * ySpan,
        y: TOP + ratio * PLOT_HEIGHT,
      };
    });

    const candidates = finite.length === 1
      ? [0]
      : [0, Math.floor((finite.length - 1) / 2), finite.length - 1];
    const xTickIndexes = Array.from(new Set(candidates));

    return { plotPoints, min, max, yTicks, xTickIndexes };
  }, [finite]);

  if (finite.length === 0) {
    return <div className="trend-chart-empty">Belum ada measurement untuk rentang ini.</div>;
  }

  const plotPoints = layout.plotPoints;
  const latest = finite[finite.length - 1]?.value ?? 0;
  const polyline = plotPoints.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const safeIndex = activeIndex == null ? null : Math.min(activeIndex, plotPoints.length - 1);
  const active = safeIndex == null ? null : plotPoints[safeIndex];

  function selectNearest(clientX: number, target: SVGSVGElement) {
    const rect = target.getBoundingClientRect();
    if (!rect.width) return;
    const viewX = ((clientX - rect.left) / rect.width) * WIDTH;
    let nearest = 0;
    let distance = Number.POSITIVE_INFINITY;
    plotPoints.forEach((point, index) => {
      const nextDistance = Math.abs(point.x - viewX);
      if (nextDistance < distance) {
        distance = nextDistance;
        nearest = index;
      }
    });
    setActiveIndex(nearest);
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    selectNearest(event.clientX, event.currentTarget);
  }

  function handleKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const fallback = event.key === "ArrowLeft" ? plotPoints.length - 1 : 0;
    const current = safeIndex ?? fallback;
    const delta = event.key === "ArrowLeft" ? -1 : 1;
    setActiveIndex(Math.max(0, Math.min(plotPoints.length - 1, current + delta)));
  }

  const tooltipLeft = active
    ? `${Math.max(14, Math.min(86, (active.x / WIDTH) * 100))}%`
    : "50%";
  const tooltipTop = active
    ? `${Math.max(12, Math.min(88, (active.y / HEIGHT) * 100))}%`
    : "50%";

  return (
    <div
      className="trend-chart"
      aria-label={`Tren dose rate. Terbaru ${latest.toFixed(3)} ${unit}. Minimum ${layout.min.toFixed(3)}. Maksimum ${layout.max.toFixed(3)}.`}
    >
      <div className="trend-chart-plot">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-labelledby="dose-trend-title dose-trend-desc"
          tabIndex={0}
          onFocus={() => setActiveIndex((current) => current ?? plotPoints.length - 1)}
          onBlur={() => setActiveIndex(null)}
          onKeyDown={handleKeyDown}
          onPointerDown={(event) => selectNearest(event.clientX, event.currentTarget)}
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setActiveIndex(null)}
          onPointerCancel={() => setActiveIndex(null)}
        >
          <title id="dose-trend-title">Tren dose rate</title>
          <desc id="dose-trend-desc">Measurement dose rate terbaru dalam {unit}. Arahkan pointer atau gunakan tombol panah untuk memeriksa titik.</desc>

          {layout.yTicks.map((tick, index) => (
            <g key={`y-${index}`}>
              <line
                className="trend-chart-grid"
                x1={LEFT}
                y1={tick.y}
                x2={WIDTH - RIGHT}
                y2={tick.y}
              />
              <text
                className="trend-chart-y-label"
                x={LEFT - 9}
                y={tick.y + 4}
                textAnchor="end"
              >
                {tick.value.toFixed(3)}
              </text>
            </g>
          ))}

          {layout.xTickIndexes.map((index) => {
            const point = plotPoints[index];
            const anchor = index === 0 ? "start" : index === plotPoints.length - 1 ? "end" : "middle";
            return (
              <text
                className="trend-chart-x-label"
                key={`x-${index}`}
                x={point.x}
                y={HEIGHT - 14}
                textAnchor={anchor}
              >
                {axisTime(point.at)}
              </text>
            );
          })}

          {plotPoints.length === 1 ? (
            <circle className="trend-chart-line-point" cx={plotPoints[0].x} cy={plotPoints[0].y} r="5" />
          ) : (
            <polyline
              className="trend-chart-line"
              points={polyline}
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          )}

          {active ? (
            <>
              <line
                className="trend-chart-crosshair"
                x1={active.x}
                y1={TOP}
                x2={active.x}
                y2={TOP + PLOT_HEIGHT}
              />
              <circle className="trend-chart-active-point" cx={active.x} cy={active.y} r="5" />
            </>
          ) : null}

          <rect
            className="trend-chart-hit-area"
            x={LEFT}
            y={TOP}
            width={PLOT_WIDTH}
            height={PLOT_HEIGHT}
            fill="transparent"
          />
        </svg>

        {active ? (
          <div
            className="trend-chart-tooltip"
            style={{ left: tooltipLeft, top: tooltipTop }}
            role="status"
            aria-live="polite"
          >
            <strong>{active.value.toFixed(3)} {unit}</strong>
            <span>{tooltipTime(active.at)}</span>
          </div>
        ) : null}
      </div>
      <div className="trend-chart-hint">Sentuh/geser grafik atau gunakan tombol panah untuk melihat nilai.</div>
    </div>
  );
}
