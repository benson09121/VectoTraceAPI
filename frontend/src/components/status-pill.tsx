import { cn } from "@/lib/utils";
import type { ServerStatus } from "@/lib/types";

const LABELS: Record<ServerStatus, string> = {
  up: "Up",
  down: "Down",
  degraded: "Degraded",
};

const DOT: Record<ServerStatus, string> = {
  up: "bg-up",
  down: "bg-down",
  degraded: "bg-degraded",
};

export function StatusPill({
  status,
  className,
}: {
  status: ServerStatus;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        className,
      )}
    >
      <span className={cn("size-2 rounded-full", DOT[status])} aria-hidden />
      {LABELS[status]}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const tone =
    severity === "critical"
      ? "bg-down/15 text-down border-down/30"
      : severity === "major"
        ? "bg-degraded/15 text-degraded border-degraded/30"
        : "bg-muted text-muted-foreground";
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2 py-0.5 text-xs font-medium capitalize",
        tone,
      )}
    >
      {severity}
    </span>
  );
}
