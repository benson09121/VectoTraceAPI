"use client";

/**
 * Status pages list.
 *
 * Was a stack of cards, each one embedding the org's entire monitor list as
 * toggles — five pages and ten monitors meant fifty switches on one screen and
 * no way to find anything. It's a `DataTable` now (DESIGN.md §6); attaching
 * monitors moved into the per-page Manage drawer where it belongs.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowSquareOut, Plus, Trash } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { StatusPageDetail } from "@/components/status-page-detail";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/shell";
import { keys, useMonitors, useStatusPages } from "@/lib/queries";
import { useAuth } from "@/lib/auth";
import type { StatusPage } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export default function StatusPagesPage() {
  const { org } = useAuth();
  const qc = useQueryClient();
  const pages = useStatusPages(org);
  const monitors = useMonitors(org);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ slug: "", title: "" });
  const [busy, setBusy] = useState(false);

  if (!org) return null;
  const refresh = () => qc.invalidateQueries({ queryKey: keys.statusPages(org.id) });

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createStatusPage(org!.id, form);
      toast.success("Status page created");
      setForm({ slug: "", title: "" });
      setOpen(false);
      refresh();
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.status === 400
          ? "That slug is already taken."
          : "Could not create status page",
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove(page: StatusPage) {
    if (!confirm(`Delete the "${page.title}" status page?`)) return;
    try {
      await api.deleteStatusPage(org!.id, page.id);
      toast.success("Status page deleted");
      refresh();
    } catch {
      toast.error("Only org admins can delete status pages");
    }
  }

  const columns: Column<StatusPage>[] = [
    {
      key: "title",
      header: "Page",
      sortable: true,
      value: (p) => `${p.title} ${p.slug}`,
      cell: (p) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{p.title}</p>
          <code className="font-mono text-xs text-muted-foreground">
            /status/{p.slug}
          </code>
        </div>
      ),
    },
    {
      key: "monitors",
      header: "Monitors",
      sortable: true,
      value: (p) => p.monitors.length,
      cell: (p) => <span className="tabular">{p.monitors.length}</span>,
    },
    {
      key: "subscriber_count",
      header: "Subscribers",
      sortable: true,
      value: (p) => p.subscriber_count,
      cell: (p) => <span className="tabular">{p.subscriber_count}</span>,
    },
    {
      key: "access",
      header: "Access",
      sortable: true,
      secondary: true,
      value: (p) => (p.is_password_protected ? "private" : p.is_public ? "public" : "hidden"),
      cell: (p) => (
        // Word, not just colour — access is exactly the thing you must not
        // misread at a glance.
        <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
          {p.is_password_protected ? "Password" : p.is_public ? "Public" : "Hidden"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (p) => (
        <div className="flex justify-end gap-1">
          <StatusPageDetail
            orgId={org.id}
            page={p}
            monitors={monitors.data ?? []}
            onChange={refresh}
          />
          <Button variant="outline" size="sm" asChild className="cursor-pointer">
            <a href={`/status/${p.slug}`} target="_blank" rel="noreferrer">
              <ArrowSquareOut className="size-4" aria-hidden /> View
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="cursor-pointer hover:text-destructive"
            onClick={() => remove(p)}
            aria-label={`Delete ${p.title}`}
          >
            <Trash className="size-4" aria-hidden />
          </Button>
        </div>
      ),
    },
  ];

  const newPageDialog = (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="cursor-pointer">
          <Plus className="size-4" aria-hidden /> New page
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New status page</DialogTitle>
        </DialogHeader>
        <form onSubmit={create} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              required
              autoFocus
              placeholder="Acme Status"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="slug">Slug</Label>
            <Input
              id="slug"
              required
              placeholder="acme"
              className="font-mono"
              value={form.slug}
              onChange={(e) =>
                setForm({
                  ...form,
                  slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"),
                })
              }
            />
            <p className="text-xs text-muted-foreground">
              Public at /status/{form.slug || "your-slug"}
            </p>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              className="cursor-pointer hover:bg-destructive/10 hover:text-destructive"
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy} className="cursor-pointer">
              {busy ? "Creating…" : "Create page"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <PageHeader
        title="Status pages"
        description="Public pages your users can check without an account."
        actions={newPageDialog}
      />

      <DataTable
        rows={pages.data ?? []}
        columns={columns}
        rowKey={(p) => p.id}
        loading={pages.isLoading}
        searchPlaceholder="Search status pages…"
        empty={{
          title: "No status pages yet",
          description: "Create one to share your uptime publicly.",
          action: newPageDialog,
        }}
      />
    </div>
  );
}
