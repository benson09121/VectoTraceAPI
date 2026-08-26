"use client";

import Link from "next/link";
import Image from "next/image";
import { SignOut } from "@phosphor-icons/react";
import { useState, useEffect } from "react";
import { AuthProvider, useAuth } from "@/lib/auth";
import { QueryProvider } from "@/lib/query-provider";
import { api } from "@/lib/api";
import { OrgSwitcher } from "@/components/org-switcher";
import {
  CollapseToggle,
  MobileNav,
  SidebarNav,
  ThemeToggle,
  useSidebarCollapsed,
} from "@/components/shell";
import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function Shell({ children }: { children: React.ReactNode }) {
  const { user, org, loading, logout } = useAuth();
  const [collapsed, setCollapsed] = useSidebarCollapsed();
  const [showcaseMode, setShowcaseMode] = useState(false);

  useEffect(() => {
    api.getSystemConfig().then((cfg) => {
      setShowcaseMode(cfg.is_showcase_mode);
    }).catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="size-6 animate-spin rounded-full border-2 border-muted border-t-primary" />
          <p className="text-sm text-muted-foreground">Loading…</p>
        </div>
      </div>
    );
  }

  const initials =
    `${user?.first_name?.[0] ?? ""}${user?.last_name?.[0] ?? ""}`.toUpperCase() ||
    user?.email?.[0]?.toUpperCase() ||
    "?";

  return (
    <div className="flex min-h-screen">
      {/* Sidebar: persistent on desktop, drawer below lg. A dense dashboard
          needs its navigation always visible, not behind a menu. */}
      {/* Branded chrome. The brand colour lives here, never on the data
          surface, so it can be bold without competing with the health colours
          the user actually needs to read. */}
      <aside
        className={cn(
          "hidden shrink-0 flex-col gap-3 border-r border-sidebar-border bg-sidebar p-3 transition-[width] duration-200 lg:flex",
          collapsed ? "w-[68px]" : "w-60",
        )}
      >
        <Link
          href="/overview"
          className={cn(
            "flex items-center gap-2 rounded-md px-2 py-1.5",
            collapsed && "justify-center px-0",
          )}
          aria-label="VectoTrace"
        >
          {collapsed ? (
            <Image
              src="/vectotrace-symbol.png"
              alt="VectoTrace"
              width={24}
              height={24}
              className="shrink-0 brightness-0 invert"
            />
          ) : (
            <Image
              src="/vectotrace-primary-lockup.png"
              alt="VectoTrace"
              width={140}
              height={32}
              className="shrink-0 brightness-0 invert"
            />
          )}
        </Link>

        <OrgSwitcher collapsed={collapsed} />
        <SidebarNav collapsed={collapsed} />

        {/* Pushed to the bottom: a control you use rarely shouldn't sit above
            the navigation you use constantly. */}
        <div className="mt-auto border-t border-sidebar-border pt-2">
          <CollapseToggle collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {showcaseMode && (
          <div className="bg-primary px-4 py-2 text-center text-sm font-medium text-primary-foreground">
            VectoTrace is currently in Showcase Mode. Demo accounts and data are automatically reset every 24 hours.
          </div>
        )}
        <header className="sticky top-0 z-40 flex items-center gap-2 border-b border-border bg-background/95 px-4 py-2.5 backdrop-blur">
          <MobileNav>
            <OrgSwitcher />
          </MobileNav>

          <Link href="/overview" className="flex items-center lg:hidden">
            <Image
              src="/vectotrace-primary-lockup.png"
              alt="VectoTrace"
              width={110}
              height={24}
              className="dark:invert"
            />
          </Link>

          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  className="flex size-8 cursor-pointer items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90"
                  aria-label="Account menu"
                >
                  {initials}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="font-normal">
                  <p className="text-sm font-medium">
                    {user?.first_name} {user?.last_name}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/profile" className="cursor-pointer">
                    Profile settings
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link href="/settings" className="cursor-pointer">
                    Organization
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout} className="cursor-pointer">
                  <SignOut className="size-4" aria-hidden />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <main className="flex-1 px-4 py-6 sm:px-6">
          {org ? (
            children
          ) : (
            <div className="mx-auto max-w-md rounded-lg border border-dashed border-border p-12 text-center">
              <h2 className="font-medium">No organization yet</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Create one from the switcher to start adding monitors.
              </p>
            </div>
          )}
        </main>
      </div>

      <Toaster />
    </div>
  );
}

export default function DashLayout({ children }: { children: React.ReactNode }) {
  return (
    // Query outside Auth: the client must survive an org switch, so its cache
    // is keyed by org id rather than torn down and rebuilt on every change.
    <QueryProvider>
      <AuthProvider>
        <Shell>{children}</Shell>
      </AuthProvider>
    </QueryProvider>
  );
}
