"use client";

/**
 * Request timing breakdown — a stacked bar splitting a check into DNS,
 * connect, TLS handshake and time-to-first-byte.
 *
 * "Your site is slow" is not actionable. "DNS took 800ms of the 900ms" is.
 * The backend records these phases per check; this is where they become
 * legible.
 *
 * Segments carry a legend AND a per-segment label, so identity never depends
 * on colour alone. Segments too narrow for their own label fall back to the
 * legend and the tooltip rather than clipping text inside a 4px sliver.
 */

import { cn } from "@/lib/utils";

export interface Timings {
  dns_ms?: number | null;
  connect_ms?: number | null;
  tls_ms?: number | null;
  ttfb_ms?: number | null;
  response_time_ms?: number | null;
}

// Fixed order = fixed colour. A phase keeps its hue whether or not the
// phases before it were recorded.
const PHASES = [
  // `ink` is chosen per step from that step's own luminance: white clears
  // 4.5:1 on the two dark steps but only reaches 1.8:1 on the lightest, so a
  // blanket white label would be unreadable on the right-hand segments.
  { key: "dns_ms", label: "DNS", color: "var(--phase-dns)", ink: "text-white" },
  { key: "connect_ms", label: "Connect", color: "var(--phase-connect)", ink: "text-white" },
  { key: "tls_ms", label: "TLS", color: "var(--phase-tls)", ink: "text-slate-900" },
  { key: "ttfb_ms", label: "TTFB", color: "var(--phase-ttfb)", ink: "text-slate-900" },
] as const;

export function TimingBar({
  timings,
  className,
}: {
  timings: Timings;
  className?: string;
}) {
  const parts = PHASES.map((p) => ({
    ...p,
    ms: (timings[p.key] as number | null | undefined) ?? 0,
  })).filter((p) => p.ms > 0);

  const total = parts.reduce((sum, p) => sum + p.ms, 0);

  if (total === 0) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        No timing breakdown recorded for this check.
      </p>
    );
  }

  // Setup is connect + TLS. When the checker reuses a pooled connection there
  // is no handshake to perform, so setup collapses to ~0 and the bar is one
  // near-solid block of waiting time. That is accurate but reads as broken, so
  // say what happened instead of drawing a meaningless chart.
  const setupMs =
    ((timings.connect_ms as number | null) ?? 0) + ((timings.tls_ms as number | null) ?? 0);
  const reusedConnection = setupMs <= 1 && (timings.ttfb_ms ?? 0) > 0;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div
        className="flex h-7 w-full overflow-hidden rounded-md"
        role="img"
        aria-label={
          `Request timing: ` +
          parts.map((p) => `${p.label} ${p.ms} milliseconds`).join(", ")
        }
      >
        {parts.map((p, i) => {
          const pct = (p.ms / total) * 100;
          return (
            <div
              key={p.key}
              // 2px surface gap between segments; white does the separating,
              // never a border drawn around the mark.
              className={cn(
                "flex items-center justify-center overflow-hidden",
                i > 0 && "ml-[2px]",
              )}
              style={{ width: `${pct}%`, background: p.color }}
              title={`${p.label}: ${p.ms}ms`}
            >
              {/* Only label a segment wide enough to hold the text. */}
              {pct > 14 && (
                <span className={cn("px-1 text-[11px] font-medium tabular", p.ink)}>
                  {p.ms}
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {parts.map((p) => (
          <span key={p.key} className="flex items-center gap-1.5">
            <span
              className="size-2 shrink-0 rounded-[2px]"
              style={{ background: p.color }}
              aria-hidden
            />
            {/* Text wears text tokens; the swatch carries identity. */}
            <span className="text-muted-foreground">{p.label}</span>
            <span className="tabular font-medium">{p.ms}ms</span>
          </span>
        ))}
        <span className="ml-auto text-muted-foreground">
          Total <span className="tabular font-medium text-foreground">{total}ms</span>
        </span>
      </div>

      {reusedConnection && (
        <p className="text-xs text-muted-foreground">
          Connection was reused, so there was no DNS lookup or TLS handshake to
          pay for — almost all of this check was spent waiting for the server to
          respond. The first check after a restart shows the full setup cost.
        </p>
      )}
    </div>
  );
}
