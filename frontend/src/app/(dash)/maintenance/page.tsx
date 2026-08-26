"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/shell";
import { DataTable, type Column } from "@/components/data-table";
import { useAuth } from "@/lib/auth";
import type { MaintenanceWindow } from "@/lib/types";
import { Button } from "@/components/ui/button";

export default function MaintenanceWindowsPage() {
  const { org } = useAuth();
  const qc = useQueryClient();

  const { data: windows, isLoading } = useQuery({
    queryKey: ["maintenance", org?.id],
    queryFn: () => api.listMaintenance(org!.id),
    enabled: !!org?.id,
  });

  if (!org) return null;

  async function remove(id: number) {
    if (!confirm("Delete this maintenance window?")) return;
    try {
      await api.deleteMaintenance(org!.id, id);
      toast.success("Maintenance window deleted");
      qc.invalidateQueries({ queryKey: ["maintenance", org!.id] });
    } catch {
      toast.error("Could not delete maintenance window");
    }
  }

  const columns: Column<MaintenanceWindow>[] = [
    {
      key: "title",
      header: "Title",
      sortable: true,
      value: (w) => w.title,
      cell: (w) => <div className="font-medium">{w.title}</div>,
    },

    {
      key: "state",
      header: "State",
      sortable: true,
      value: (w) => w.state,
      cell: (w) => <div className="capitalize">{w.state}</div>,
    },
    {
      key: "start",
      header: "Start",
      sortable: true,
      value: (w) => w.starts_at,
      cell: (w) => (
        <span className="tabular text-muted-foreground">
          {new Date(w.starts_at).toLocaleString()}
        </span>
      ),
    },
    {
      key: "end",
      header: "End",
      sortable: true,
      value: (w) => w.ends_at,
      cell: (w) => (
        <span className="tabular text-muted-foreground">
          {new Date(w.ends_at).toLocaleString()}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (w) => (
        <Button
          variant="ghost"
          size="icon"
          className="cursor-pointer hover:text-destructive"
          onClick={() => remove(w.id)}
          aria-label="Delete maintenance window"
        >
          <Trash className="size-4" aria-hidden />
        </Button>
      ),
    },
  ];

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PageHeader
        title="Maintenance Windows"
        description="Schedule downtime to prevent alerts during planned work."
        actions={
          <Button disabled>
            <Plus className="mr-2 size-4" /> New Window
          </Button>
        }
      />

      <DataTable
        rows={windows ?? []}
        columns={columns}
        rowKey={(w) => w.id}
        loading={isLoading}
        searchPlaceholder="Search maintenance windows..."
        pageSize={10}
        empty={{
          title: "No maintenance windows",
          description: "Create a maintenance window to suppress alerts.",
        }}
      />
    </div>
  );
}
