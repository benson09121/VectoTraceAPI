"use client";

/**
 * Response time over time for one monitor.
 *
 * Hand-rolled SVG rather than a charting library: it is one line, one axis pair
 * and a crosshair, which is far less code than configuring Recharts — and it
 * keeps the bundle free of a dependency for a single chart.
 *
 * Design rules applied: 2px line with round caps, hairline solid gridlines one
 * step off the surface, no legend (a single series is named by the card title),
 * the endpoint value direct-labelled rather than every point, text in text
 * tokens rather than the series colour, and a crosshair that snaps to the
 * nearest point so the reader aims at a time, not at a 2px line.
 */

import { useId, useMemo, useRef, useState } from "react";
import type { ApiLog } from "@/lib/types";

const HEIGHT = 200;
const PAD = { top: 16, right: 16, bottom: 24, left: 48 };

type Point = { x: number; y: number; ms: number; at: Date; ok: boolean };

function niceTicks(max: number): number[] {
  if (max <= 0) return [0];
  const raw = max / 3;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * mag >= raw)! * mag;
  const out: number[] = [];
  for (let v = 0; v <= max + step / 2; v += step) out.push(v);
  return out;
}

export function ResponseTimeChart({ checks }: { checks: ApiLog[] }) {
  const gradientId = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [width, setWidth] = useState(720);

  // Oldest to newest; failures have no timing so they can't be plotted as
  // points on a duration axis, but they still matter — marked on the baseline.
  const ordered = useMemo(
    () => [...checks].sort((a, b) => +new Date(a.checked_at) - +new Date(b.checked_at)),
    [checks],
  );

  const timed = useMemo(
    () => ordered.filter((c) => c.response_time_ms != null),
    [ordered],
  );

  const { points, failures, ticks, maxY } = useMemo(() => {
    if (timed.length === 0) {
      return { points: [] as Point[], failures: [] as Point[], ticks: [0], maxY: 0 };
    }

    const times = ordered.map((c) => +new Date(c.checked_at));
    const t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const span = t1 - t0 || 1;

    const peak = Math.max(...timed.map((c) => c.response_time_ms!));
    const tickVals = niceTicks(peak);
    const top = tickVals[tickVals.length - 1] || 1;

    const plotW = width - PAD.left - PAD.right;
    const plotH = HEIGHT - PAD.top - PAD.bottom;
    const toX = (t: number) => PAD.left + ((t - t0) / span) * plotW;
    const toY = (ms: number) => PAD.top + plotH - (ms / top) * plotH;

    const mk = (c: ApiLog): Point => ({
      x: toX(+new Date(c.checked_at)),
      y: c.response_time_ms != null ? toY(c.response_time_ms) : PAD.top + plotH,
      ms: c.response_time_ms ?? 0,
      at: new Date(c.checked_at),
      ok: c.result === "success",
    });

    return {
      points: timed.map(mk),
      failures: ordered.filter((c) => c.response_time_ms == null).map(mk),
      ticks: tickVals,
      maxY: top,
    };
  }, [ordered, timed, width]);

  if (timed.length < 2) {
    return (
      <p className="text-sm text-muted-foreground">
        Not enough timing data yet — the graph appears once a monitor has two or more
        successful checks.
      </p>
    );
  }

  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const line = points.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
  const area = `${line} L${points[points.length - 1].x} ${PAD.top + plotH} L${points[0].x} ${PAD.top + plotH} Z`;
  const last = points[points.length - 1];
  const active = hover != null ? points[hover] : null;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = ((e.clientX - rect.left) / rect.width) * width;
    // Snap to nearest point so the pointer never has to hit the line itself.
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(points[i].x - x) < Math.abs(points[best].x - x)) best = i;
    }
    setHover(best);
    if (rect.width !== width) setWidth(rect.width);
  }

  return (
    <div className="w-full">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        className="w-full touch-none"
        style={{ height: HEIGHT }}
        role="img"
        aria-label={`Response time over time. Latest ${last.ms} milliseconds. Full values are listed in the recent checks table below.`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-1)" stopOpacity="0.14" />
            <stop offset="100%" stopColor="var(--chart-1)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {ticks.map((v) => {
          const y = PAD.top + plotH - (v / (maxY || 1)) * plotH;
          return (
            <g key={v}>
              <line
                x1={PAD.left} y1={y} x2={width - PAD.right} y2={y}
                stroke="var(--border)" strokeWidth="1"
              />
              <text
                x={PAD.left - 8} y={y + 4} textAnchor="end"
                className="fill-muted-foreground"
                style={{ fontSize: 11, fontVariantNumeric: "tabular-nums" }}
              >
                {v.toLocaleString()}
              </text>
            </g>
          );
        })}

        <path d={area} fill={`url(#${gradientId})`} />
        <path
          d={line} fill="none" stroke="var(--chart-1)" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round"
        />

        {/* Failed checks have no duration; a tick on the baseline keeps them
            visible instead of silently vanishing from the series. */}
        {failures.map((f, i) => (
          <line
            key={i}
            x1={f.x} y1={PAD.top + plotH - 6} x2={f.x} y2={PAD.top + plotH}
            stroke="var(--chart-fail)" strokeWidth="2" strokeLinecap="round"
          />
        ))}

        {active && (
          <line
            x1={active.x} y1={PAD.top} x2={active.x} y2={PAD.top + plotH}
            stroke="var(--border)" strokeWidth="1"
          />
        )}

        {/* Endpoint marker: 8px dot with a 2px surface ring so it stays legible
            wherever it lands. */}
        <circle
          cx={last.x} cy={last.y} r="4"
          fill="var(--chart-1)" stroke="var(--background)" strokeWidth="2"
        />
        {active && active !== last && (
          <circle
            cx={active.x} cy={active.y} r="4"
            fill="var(--chart-1)" stroke="var(--background)" strokeWidth="2"
          />
        )}

        {/* Label the endpoint only — a number on every point goes unread. */}
        <text
          x={Math.min(last.x + 8, width - PAD.right)}
          y={Math.max(last.y - 8, PAD.top + 10)}
          textAnchor={last.x > width - 80 ? "end" : "start"}
          className="fill-foreground"
          style={{ fontSize: 11, fontWeight: 600 }}
        >
          {last.ms.toLocaleString()}ms
        </text>

        <text
          x={PAD.left} y={HEIGHT - 6}
          className="fill-muted-foreground" style={{ fontSize: 11 }}
        >
          {points[0].at.toLocaleTimeString()}
        </text>
        <text
          x={width - PAD.right} y={HEIGHT - 6} textAnchor="end"
          className="fill-muted-foreground" style={{ fontSize: 11 }}
        >
          {last.at.toLocaleTimeString()}
        </text>
      </svg>

      {active && (
        <div className="mt-1 flex items-center gap-2 text-sm">
          <span
            className="inline-block h-0.5 w-3 rounded-full"
            style={{ background: "var(--chart-1)" }}
            aria-hidden
          />
          {/* Value leads, label follows: the reader already knows the series. */}
          <span className="font-semibold tabular-nums">{active.ms.toLocaleString()}ms</span>
          <span className="text-muted-foreground">{active.at.toLocaleString()}</span>
        </div>
      )}
    </div>
  );
}
