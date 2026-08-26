"use client";

/**
 * Dashboard chrome: sidebar navigation, page header, and stat tiles.
 *
 * Kept in one file because these three only ever appear together, and splitting
 * them across files would mean three imports on every page for no benefit.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import {
  Bell,
  CaretLeft,
  CaretRight,
  ChartLine,
  Gear,
  List as ListIcon,
  Moon,
  Pulse,
  SignOut,
  Sun,
  Warning,
  Wrench,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

export function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const isDark = theme === "dark" || (theme === "system" && systemPrefersDark());

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="cursor-pointer"
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}

/** Guarded so this is safe during the server render. */
function systemPrefersDark(): boolean {
  return typeof window !== "undefined"
    ? matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

const NAV = [
  { href: "/overview", label: "Overview", icon: ChartLine },
  { href: "/monitors", label: "Monitors", icon: Pulse },
  { href: "/incidents", label: "Incidents", icon: Warning },
  { href: "/status-pages", label: "Status pages", icon: Bell },
  { href: "/maintenance", label: "Maintenance", icon: Wrench },
  { href: "/settings", label: "Settings", icon: Gear },
];

export function SidebarNav({
  onNavigate,
  collapsed = false,
  className,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
  className?: string;
}) {
  const pathname = usePathname();

  return (
    <nav className={cn("flex flex-col gap-0.5", className)} aria-label="Main">
      {NAV.map(({ href, label, icon: Icon }) => {
        // startsWith so detail pages keep their section highlighted, but guard
        // against "/monitors" matching "/monitors-archive".
        const current = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={current ? "page" : undefined}
            // Collapsed, the aria-label carries the name so the rail is never
            // a row of mystery glyphs to a screen reader.
            aria-label={collapsed ? label : undefined}
            title={collapsed ? label : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md text-sm transition-colors",
              collapsed ? "justify-center p-2.5" : "px-3 py-2",
              current
                ? "bg-sidebar-active font-medium text-sidebar-active-foreground"
                : "text-sidebar-foreground hover:bg-white/10",
            )}
          >
            <Icon className="size-4 shrink-0" weight={current ? "fill" : "regular"} aria-hidden />
            {!collapsed && label}
          </Link>
        );
      })}
    </nav>
  );
}

import Image from "next/image";

export function MobileNav({ children }: { children?: React.ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="cursor-pointer lg:hidden"
        onClick={() => setOpen(true)}
        aria-label="Open navigation"
      >
        <ListIcon className="size-5" />
      </Button>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          {/* 50% scrim: strong enough to isolate the drawer from the page. */}
          <button
            className="absolute inset-0 bg-black/50"
            onClick={() => setOpen(false)}
            aria-label="Close navigation"
            tabIndex={-1}
          />
          <div className="absolute inset-y-0 left-0 flex w-64 flex-col gap-4 border-r border-border bg-card p-4">
            <div className="flex items-center justify-between">
              <Image
                src="/vectotrace-primary-lockup.png"
                alt="VectoTrace"
                width={120}
                height={28}
                className="dark:invert"
              />
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
                className="cursor-pointer"
              >
                <X className="size-4" />
              </Button>
            </div>
            {children}
            <SidebarNav onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page header
// ---------------------------------------------------------------------------

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </header>
  );
}

// ---------------------------------------------------------------------------
// Stat tile
// ---------------------------------------------------------------------------

export function StatTile({
  label,
  value,
  hint,
  tone = "default",
  loading,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "up" | "down" | "degraded";
  loading?: boolean;
}) {
  const toneClass = {
    default: "text-foreground",
    up: "text-up",
    down: "text-down",
    degraded: "text-degraded",
  }[tone];

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {loading ? (
        <div className="mt-2 h-7 w-16 animate-pulse rounded bg-muted" />
      ) : (
        // Proportional figures, not tabular: a large standalone number looks
        // loose when every digit is forced to the width of a zero.
        <p className={cn("mt-1 text-2xl font-semibold", toneClass)}>{value}</p>
      )}
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export { SignOut };

// ---------------------------------------------------------------------------
// Sidebar collapse
// ---------------------------------------------------------------------------

const RAIL_KEY = "vt-sidebar-collapsed";

/**
 * Collapsed state, read through `useSyncExternalStore` for the same reason the
 * theme is: localStorage is external mutable state, and copying it into React
 * state inside an effect costs an extra render and can flash the wrong width.
 */
const railListeners = new Set<() => void>();

function subscribeRail(cb: () => void) {
  railListeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    railListeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

export function useSidebarCollapsed(): [boolean, (v: boolean) => void] {
  const collapsed = useSyncExternalStore(
    subscribeRail,
    () => localStorage.getItem(RAIL_KEY) === "1",
    () => false, // server render: always expanded
  );
  const set = (v: boolean) => {
    localStorage.setItem(RAIL_KEY, v ? "1" : "0");
    railListeners.forEach((l) => l());
  };
  return [collapsed, set];
}

export function CollapseToggle({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      className="flex w-full cursor-pointer items-center justify-center rounded-md p-2 text-sidebar-muted transition-colors hover:bg-white/10 hover:text-sidebar-foreground"
    >
      {collapsed ? (
        <CaretRight className="size-4" aria-hidden />
      ) : (
        <CaretLeft className="size-4" aria-hidden />
      )}
    </button>
  );
}
