"use client";

/**
 * Reusable data table.
 *
 * One component behind every list in the dashboard so that search, filtering,
 * sorting, pagination, selection, empty and loading states behave identically
 * everywhere — a table that works differently on each page is how users stop
 * trusting the controls.
 *
 * Deliberate behaviours:
 *  - The frame never collapses while loading. Skeleton rows replace the body,
 *    so the header, filters and page height stay put and nothing jumps.
 *  - Empty is not the same as filtered-to-empty. "No monitors yet" invites you
 *    to create one; "no results" offers to clear the filters.
 *  - Sorting is tri-state (asc → desc → off) so you can get back to the
 *    server's natural order without reloading.
 *  - The whole table scrolls horizontally inside its own container rather than
 *    forcing the page to scroll sideways on small screens.
 */

import { useMemo, useState } from "react";
import {
  CaretDown,
  CaretUp,
  CaretUpDown,
  MagnifyingGlass,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface Column<T> {
  /** Stable key; also the sort key unless `sortKey` overrides it. */
  key: string;
  header: string;
  /** Cell renderer. Return a node; keep it cheap, this runs per row. */
  cell: (row: T) => React.ReactNode;
  /** Value used for sorting and for the free-text search index. */
  value?: (row: T) => string | number | null | undefined;
  sortable?: boolean;
  /** Hide below `md`. Use for columns that are context, not identity. */
  secondary?: boolean;
  align?: "left" | "right";
  width?: string;
}

export interface FilterDef<T> {
  key: string;
  label: string;
  options: { value: string; label: string }[];
  /** Return true to keep the row. */
  predicate: (row: T, value: string) => boolean;
}

export interface BulkAction<T> {
  label: string;
  onRun: (rows: T[]) => void | Promise<void>;
  destructive?: boolean;
}

interface DataTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  /** Free-text search across every column that defines `value`. */
  searchable?: boolean;
  searchPlaceholder?: string;
  filters?: FilterDef<T>[];
  bulkActions?: BulkAction<T>[];
  pageSize?: number;
  onRowClick?: (row: T) => void;
  /** Shown when there is genuinely no data (not when filters exclude it all). */
  empty?: { title: string; description?: string; action?: React.ReactNode };
  /** Extra controls rendered in the toolbar, right-aligned. */
  toolbar?: React.ReactNode;
  className?: string;
}

type SortState = { key: string; dir: "asc" | "desc" } | null;

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  loading = false,
  searchable = true,
  searchPlaceholder = "Search…",
  filters = [],
  bulkActions = [],
  pageSize = 20,
  onRowClick,
  empty,
  toolbar,
  className,
}: DataTableProps<T>) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string | number>>(new Set());

  const filtersApplied =
    query.trim() !== "" || Object.values(active).some((v) => v && v !== "all");

  const visible = useMemo(() => {
    let out = rows;

    for (const f of filters) {
      const v = active[f.key];
      if (v && v !== "all") out = out.filter((r) => f.predicate(r, v));
    }

    const q = query.trim().toLowerCase();
    if (q) {
      out = out.filter((row) =>
        columns.some((c) => {
          const v = c.value?.(row);
          return v != null && String(v).toLowerCase().includes(q);
        }),
      );
    }

    if (sort) {
      const col = columns.find((c) => c.key === sort.key);
      if (col?.value) {
        out = [...out].sort((a, b) => {
          const av = col.value!(a) ?? "";
          const bv = col.value!(b) ?? "";
          const cmp =
            typeof av === "number" && typeof bv === "number"
              ? av - bv
              : String(av).localeCompare(String(bv), undefined, { numeric: true });
          return sort.dir === "asc" ? cmp : -cmp;
        });
      }
    }

    return out;
  }, [rows, columns, filters, active, query, sort]);

  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize));
  // Filtering can shrink the list below the current page. Clamp on read rather
  // than storing an out-of-range page and correcting it in an effect — that
  // renders one frame of a convincing but empty table first.
  const safePage = Math.min(page, pageCount);
  const paged = useMemo(
    () => visible.slice((safePage - 1) * pageSize, safePage * pageSize),
    [visible, safePage, pageSize],
  );

  function toggleSort(key: string) {
    setSort((cur) => {
      if (cur?.key !== key) return { key, dir: "asc" };
      if (cur.dir === "asc") return { key, dir: "desc" };
      return null; // third click returns to the server's order
    });
  }

  const pageKeys = paged.map(rowKey);
  const allOnPageSelected =
    pageKeys.length > 0 && pageKeys.every((k) => selected.has(k));

  function toggleAllOnPage() {
    setSelected((cur) => {
      const next = new Set(cur);
      if (allOnPageSelected) pageKeys.forEach((k) => next.delete(k));
      else pageKeys.forEach((k) => next.add(k));
      return next;
    });
  }

  const selectedRows = rows.filter((r) => selected.has(rowKey(r)));
  const showToolbar = searchable || filters.length > 0 || toolbar;

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {showToolbar && (
        // Filters live in one row above the content they scope — never inside
        // the table, never per-column.
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {searchable && (
            <div className="relative flex-1 min-w-0 sm:max-w-xs">
              <MagnifyingGlass
                className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(1);
                }}
                placeholder={searchPlaceholder}
                aria-label={searchPlaceholder}
                className="pl-8"
              />
            </div>
          )}

          {filters.map((f) => (
            <Select
              key={f.key}
              value={active[f.key] ?? "all"}
              onValueChange={(v) => {
                setActive((cur) => ({ ...cur, [f.key]: v }));
                setPage(1);
              }}
            >
              <SelectTrigger className="w-full sm:w-40" aria-label={f.label}>
                <SelectValue placeholder={f.label} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All {f.label.toLowerCase()}</SelectItem>
                {f.options.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ))}

          {filtersApplied && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setQuery("");
                setActive({});
                setPage(1);
              }}
            >
              <X className="size-4" aria-hidden />
              Clear
            </Button>
          )}

          {toolbar && <div className="sm:ml-auto">{toolbar}</div>}
        </div>
      )}

      {bulkActions.length > 0 && selectedRows.length > 0 && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm"
        >
          <span className="font-medium tabular">
            {selectedRows.length} selected
          </span>
          <div className="ml-auto flex flex-wrap gap-2">
            {bulkActions.map((a) => (
              <Button
                key={a.label}
                size="sm"
                variant={a.destructive ? "destructive" : "secondary"}
                className="cursor-pointer"
                onClick={async () => {
                  await a.onRun(selectedRows);
                  setSelected(new Set());
                }}
              >
                {a.label}
              </Button>
            ))}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelected(new Set())}
              // Cancel discards a selection, so it reads as the "undo" of this
              // bar — red on hover signals that without making it a loud
              // destructive button competing with the real actions.
              className="cursor-pointer hover:bg-destructive/10 hover:text-destructive"
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* The table scrolls inside this box; the page never scrolls sideways. */}
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/50">
              {bulkActions.length > 0 && (
                <th scope="col" className="w-10 px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={allOnPageSelected}
                    onChange={toggleAllOnPage}
                    aria-label="Select all rows on this page"
                    className="size-4 cursor-pointer accent-[var(--primary)]"
                  />
                </th>
              )}
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  style={c.width ? { width: c.width } : undefined}
                  className={cn(
                    "px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                    c.align === "right" ? "text-right" : "text-left",
                    c.secondary && "hidden md:table-cell",
                  )}
                  aria-sort={
                    sort?.key === c.key
                      ? sort.dir === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                >
                  {c.sortable && c.value ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(c.key)}
                      className={cn(
                        "inline-flex cursor-pointer items-center gap-1 rounded transition-colors hover:text-foreground",
                        c.align === "right" && "flex-row-reverse",
                      )}
                    >
                      {c.header}
                      {sort?.key === c.key ? (
                        sort.dir === "asc" ? (
                          <CaretUp className="size-3" aria-hidden />
                        ) : (
                          <CaretDown className="size-3" aria-hidden />
                        )
                      ) : (
                        <CaretUpDown className="size-3 opacity-40" aria-hidden />
                      )}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {loading ? (
              // Skeleton rows keep the frame; the layout must not jump when
              // real data lands.
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-border last:border-0">
                  {bulkActions.length > 0 && <td className="px-3 py-3" />}
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn("px-3 py-3", c.secondary && "hidden md:table-cell")}
                    >
                      <Skeleton className="h-4 w-full max-w-32" />
                    </td>
                  ))}
                </tr>
              ))
            ) : paged.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length + (bulkActions.length > 0 ? 1 : 0)}
                  className="px-3 py-12 text-center"
                >
                  {filtersApplied ? (
                    // Filtered to nothing is a different problem from having
                    // nothing, and needs a different way out.
                    <div className="flex flex-col items-center gap-2">
                      <p className="text-sm font-medium">No matching results</p>
                      <p className="text-sm text-muted-foreground">
                        Try a different search or filter.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setQuery("");
                          setActive({});
                        }}
                      >
                        Clear filters
                      </Button>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2">
                      <p className="text-sm font-medium">
                        {empty?.title ?? "Nothing here yet"}
                      </p>
                      {empty?.description && (
                        <p className="max-w-sm text-sm text-muted-foreground">
                          {empty.description}
                        </p>
                      )}
                      {empty?.action}
                    </div>
                  )}
                </td>
              </tr>
            ) : (
              paged.map((row) => {
                const key = rowKey(row);
                const isSelected = selected.has(key);
                return (
                  <tr
                    key={key}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={cn(
                      "border-b border-border transition-colors last:border-0",
                      isSelected ? "bg-row-selected" : "hover:bg-row-hover",
                      onRowClick && "cursor-pointer",
                    )}
                  >
                    {bulkActions.length > 0 && (
                      <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() =>
                            setSelected((cur) => {
                              const next = new Set(cur);
                              if (next.has(key)) next.delete(key);
                              else next.add(key);
                              return next;
                            })
                          }
                          aria-label="Select row"
                          className="size-4 cursor-pointer accent-[var(--primary)]"
                        />
                      </td>
                    )}
                    {columns.map((c) => (
                      <td
                        key={c.key}
                        className={cn(
                          "px-3 py-2.5",
                          c.align === "right" && "text-right",
                          c.secondary && "hidden md:table-cell",
                        )}
                      >
                        {c.cell(row)}
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {!loading && visible.length > pageSize && (
        <div className="flex items-center justify-between gap-2 text-sm">
          <p className="text-muted-foreground tabular">
            {(safePage - 1) * pageSize + 1}–{Math.min(safePage * pageSize, visible.length)} of{" "}
            {visible.length}
          </p>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={safePage === 1}
              onClick={() => setPage(Math.max(1, safePage - 1))}
            >
              Previous
            </Button>
            <span className="px-2 text-muted-foreground tabular">
              {safePage} / {pageCount}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={safePage >= pageCount}
              onClick={() => setPage(Math.min(pageCount, safePage + 1))}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
