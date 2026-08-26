"use client";

/**
 * Heartbeat bar — the signature element of every uptime product.
 *
 * One vertical bar per check, oldest on the left. Colour carries the result,
 * but colour is never the only channel: each bar has a tooltip on hover AND on
 * keyboard focus, and the strip as a whole has a text summary for screen
 * readers, so a red/green-blind or keyboard-only reader is not locked out of
 * the primary status display.
 *
 * The tooltip is `position: fixed` on purpose. The strip also renders inside a
 * table cell with `overflow-x: auto`; an absolutely-positioned tooltip would be
 * clipped by that container exactly when the row is interesting. Fixed
 * positioning escapes every ancestor, so one implementation works in both
 * places.
 *
 * Missing beats render as neutral placeholders rather than collapsing the
 * strip, so a monitor with 3 checks and one with 40 line up in a table column
 * instead of jittering to different widths.
 */

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

export interface Beat {
  result: "success" | "failure";
  response_time_ms: number | null;
  checked_at: string;
}

interface HeartbeatBarProps {
  beats: Beat[];
  /** Pad to this many slots so strips align across rows. */
  slots?: number;
  size?: "sm" | "md";
  /** Show the "N ago … now" scale underneath. */
  showScale?: boolean;
  className?: string;
}

function ago(iso: string): string {
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

type Anchor = { beat: Beat; x: number; y: number };

/** The floating readout. Rendered into <body> so no ancestor can clip it. */
function BeatTooltip({ anchor }: { anchor: Anchor }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: anchor.x, top: anchor.y, ready: false });

  // Measure, then clamp inside the viewport. Done in a layout effect so the
  // tooltip never paints in the wrong place first.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const margin = 8;
    const left = Math.min(
      Math.max(margin, anchor.x - box.width / 2),
      window.innerWidth - box.width - margin,
    );
    // Prefer above the bar; flip below if there isn't room.
    const above = anchor.y - box.height - 10;
    const top = above < margin ? anchor.y + 20 : above;
    setPos({ left, top, ready: true });
  }, [anchor]);

  const ok = anchor.beat.result === "success";

  return createPortal(
    <div
      ref={ref}
      role="tooltip"
      style={{
        position: "fixed",
        left: pos.left,
        top: pos.top,
        // Avoid a visible jump between the initial guess and the clamped
        // position by staying invisible for the first frame.
        visibility: pos.ready ? "visible" : "hidden",
      }}
      className="pointer-events-none z-[100] rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg"
    >
      <div className="flex items-center gap-1.5 font-medium">
        <span
          className={cn("size-1.5 rounded-full", ok ? "bg-up" : "bg-down")}
          aria-hidden
        />
        <span className={ok ? "text-up" : "text-down"}>{ok ? "Up" : "Down"}</span>
        {anchor.beat.response_time_ms != null && (
          <span className="tabular text-popover-foreground">
            {anchor.beat.response_time_ms} ms
          </span>
        )}
      </div>
      <p className="mt-0.5 whitespace-nowrap text-muted-foreground tabular">
        {new Date(anchor.beat.checked_at).toLocaleString()}
      </p>
    </div>,
    document.body,
  );
}

export function HeartbeatBar({
  beats,
  slots = 40,
  size = "md",
  showScale = false,
  className,
}: HeartbeatBarProps) {
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  // Pad on the LEFT so the newest beat is always hard right — the eye should
  // find "now" in the same place on every row.
  const padding = Math.max(0, slots - beats.length);
  const cells: (Beat | null)[] = [...Array(padding).fill(null), ...beats.slice(-slots)];

  const failed = beats.filter((b) => b.result === "failure").length;
  const summary =
    beats.length === 0
      ? "No checks recorded yet"
      : `${beats.length} recent checks, ${failed} failed`;

  const show = useCallback((el: HTMLElement, beat: Beat, i: number) => {
    const box = el.getBoundingClientRect();
    setAnchor({ beat, x: box.left + box.width / 2, y: box.top });
    setHoverIndex(i);
  }, []);

  const hide = useCallback(() => {
    setAnchor(null);
    setHoverIndex(null);
  }, []);

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {/* A group, not role="img": the bars are focusable buttons, and
          role="img" would hide every one of them from assistive tech. The
          label gives the whole strip a summary; each bar labels itself. */}
      <div
        className="flex items-end gap-[2px]"
        role="group"
        aria-label={summary}
        onMouseLeave={hide}
      >
        {cells.map((beat, i) =>
          beat === null ? (
            <div
              key={i}
              className={cn(
                "flex-1 rounded-[2px] bg-muted",
                size === "sm" ? "h-4 min-w-[3px]" : "h-8 min-w-[4px]",
              )}
            />
          ) : (
            // A real beat is focusable so keyboard users get the same readout
            // hover gives — the tooltip must never be mouse-only.
            <button
              key={i}
              type="button"
              tabIndex={0}
              aria-label={`${beat.result === "success" ? "Up" : "Down"}${
                beat.response_time_ms != null ? `, ${beat.response_time_ms} milliseconds` : ""
              }, ${new Date(beat.checked_at).toLocaleString()}`}
              onMouseEnter={(e) => show(e.currentTarget, beat, i)}
              onFocus={(e) => show(e.currentTarget, beat, i)}
              onBlur={hide}
              className={cn(
                "flex-1 cursor-pointer rounded-[2px] transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                size === "sm" ? "h-4 min-w-[3px]" : "h-8 min-w-[4px]",
                beat.result === "success" ? "bg-up" : "bg-down",
                // Dim the others so the hovered bar reads as selected without
                // changing its size — a scale transform here would shift every
                // neighbouring bar and make the strip jitter.
                hoverIndex != null && hoverIndex !== i && "opacity-50",
              )}
            />
          ),
        )}
      </div>

      {showScale && (
        <div className="flex justify-between text-[11px] text-muted-foreground">
          <span>{beats.length > 0 ? ago(beats[0].checked_at) : ""}</span>
          <span>now</span>
        </div>
      )}

      {anchor && <BeatTooltip anchor={anchor} />}
    </div>
  );
}

/**
 * Uptime percentage badge, as seen beside each monitor name in Uptime Kuma.
 * Tinted by health so the number and its colour agree.
 */
export function UptimeBadge({
  value,
  className,
}: {
  value: number | null | undefined;
  className?: string;
}) {
  if (value == null) {
    return (
      <span
        className={cn(
          "rounded px-1.5 py-0.5 text-[11px] font-medium tabular text-muted-foreground bg-muted",
          className,
        )}
      >
        —
      </span>
    );
  }

  const tone =
    value >= 99
      ? "bg-up/15 text-up"
      : value >= 95
        ? "bg-degraded/15 text-degraded"
        : "bg-down/15 text-down";

  return (
    <span
      className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium tabular", tone, className)}
      title={`${value}% uptime over recent checks`}
    >
      {value.toFixed(2)}%
    </span>
  );
}
