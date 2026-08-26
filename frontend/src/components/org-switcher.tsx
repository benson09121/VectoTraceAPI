"use client";

/**
 * Organization switcher.
 *
 * One control, not two. The previous version put a bare "+" icon button beside
 * the switcher: it ate sidebar width, and it read as unrelated to the thing it
 * created. Creating an org now lives inside the dropdown under a separator —
 * the same pattern Linear, Vercel and GitHub use — so the action sits with the
 * object it acts on.
 *
 * Styled against the branded sidebar tokens rather than the content-surface
 * tokens, because it lives in the chrome.
 */

import { useState } from "react";
import Link from "next/link";
import { Buildings, CaretUpDown, Check, Gear, Plus } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export function OrgSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const { orgs, org, setOrg, refreshOrgs } = useAuth();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function createOrg(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await api.createOrg(name);
      await refreshOrgs();
      setOrg(created);
      setName("");
      setOpen(false);
      toast.success(`${created.name} created — you are its admin`);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Could not create the organization",
      );
    } finally {
      setBusy(false);
    }
  }

  const initial = (org?.name ?? "?").charAt(0).toUpperCase();

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            aria-label={org ? `Organization: ${org.name}` : "Choose organization"}
            title={collapsed ? (org?.name ?? "Choose organization") : undefined}
            className={cn(
              "flex w-full cursor-pointer items-center gap-2 rounded-md border border-sidebar-border bg-white/5 text-sm text-sidebar-foreground transition-colors hover:bg-white/10",
              collapsed ? "justify-center p-2" : "px-2.5 py-2",
            )}
          >
            {collapsed ? (
              // Collapsed rail: a single initial keeps the org identifiable
              // without a label, and the title attribute carries the full name.
              <span className="flex size-6 items-center justify-center rounded bg-sidebar-active text-xs font-semibold text-sidebar-active-foreground">
                {initial}
              </span>
            ) : (
              <>
                <Buildings className="size-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-left">
                  {org?.name ?? "No organization"}
                </span>
                <CaretUpDown className="size-4 shrink-0 opacity-60" aria-hidden />
              </>
            )}
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-60">
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
            Organizations
          </DropdownMenuLabel>

          {orgs.map((o) => (
            <DropdownMenuItem
              key={o.id}
              onClick={() => setOrg(o)}
              className="cursor-pointer"
            >
              <Check
                className={cn("size-4", o.id === org?.id ? "opacity-100" : "opacity-0")}
                aria-hidden
              />
              <span className="truncate">{o.name}</span>
            </DropdownMenuItem>
          ))}

          {orgs.length === 0 && (
            <p className="px-2 py-3 text-center text-xs text-muted-foreground">
              You are not in an organization yet.
            </p>
          )}

          <DropdownMenuSeparator />

          <DropdownMenuItem onClick={() => setOpen(true)} className="cursor-pointer">
            <Plus className="size-4" aria-hidden />
            Create organization…
          </DropdownMenuItem>

          {org && (
            <DropdownMenuItem asChild className="cursor-pointer">
              <Link href="/settings">
                <Gear className="size-4" aria-hidden />
                Organization settings
              </Link>
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create organization</DialogTitle>
            <DialogDescription>
              Monitors, status pages and alert channels all belong to an
              organization. You will be its admin.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={createOrg} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="org-name">Name</Label>
              <Input
                id="org-name"
                required
                autoFocus
                placeholder="Acme Engineering"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setOpen(false)}
                className="cursor-pointer"
              >
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !name.trim()} className="cursor-pointer">
                {busy ? "Creating…" : "Create organization"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
