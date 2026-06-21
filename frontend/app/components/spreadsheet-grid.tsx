"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useT } from "@/app/lib/i18n";

export interface GridColumn {
  key: string;
  label: string;
  width: number;
  editable?: boolean;
  type?: "text" | "number" | "select";
  options?: { value: string; label: string; color?: string }[];
  align?: "left" | "right" | "center";
}

export interface GridRow {
  id: string;
  [key: string]: unknown;
}

interface CellRef {
  row: number;
  col: number;
}

function cellEq(a: CellRef | null, b: CellRef | null) {
  if (!a || !b) return false;
  return a.row === b.row && a.col === b.col;
}

export default function SpreadsheetGrid({
  columns,
  rows,
  edits,
  onCellChange,
}: {
  columns: GridColumn[];
  rows: GridRow[];
  edits: Record<string, Record<string, unknown>>;
  onCellChange: (rowId: string, colKey: string, value: unknown) => void;
}) {
  const t = useT();
  const [active, setActive] = useState<CellRef | null>(null);
  const [editing, setEditing] = useState<CellRef | null>(null);
  const [editValue, setEditValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  const commitEdit = useCallback(() => {
    if (!editing) return;
    const col = columns[editing.col];
    const row = rows[editing.row];
    if (!col || !row) return;

    const original = row[col.key];
    let newVal: unknown = editValue;
    if (col.type === "number") {
      const parsed = parseFloat(editValue);
      newVal = isNaN(parsed) ? original : parsed;
    }
    if (newVal !== original) {
      onCellChange(row.id, col.key, newVal);
    }
    setEditing(null);
  }, [editing, editValue, columns, rows, onCellChange]);

  const startEdit = useCallback(
    (cell: CellRef) => {
      const col = columns[cell.col];
      if (!col?.editable) return;
      const row = rows[cell.row];
      const val = edits[row.id]?.[col.key] ?? row[col.key];
      setEditing(cell);
      setEditValue(val == null ? "" : String(val));
    },
    [columns, rows, edits]
  );

  const moveActive = useCallback(
    (dr: number, dc: number) => {
      setActive((prev) => {
        if (!prev) return { row: 0, col: 0 };
        const r = Math.max(0, Math.min(rows.length - 1, prev.row + dr));
        const c = Math.max(0, Math.min(columns.length - 1, prev.col + dc));
        return { row: r, col: c };
      });
    },
    [rows.length, columns.length]
  );

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
    if (editing && selectRef.current) {
      selectRef.current.focus();
    }
  }, [editing]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (editing) {
        if (e.key === "Escape") {
          e.preventDefault();
          setEditing(null);
        } else if (e.key === "Enter") {
          e.preventDefault();
          commitEdit();
          moveActive(1, 0);
        } else if (e.key === "Tab") {
          e.preventDefault();
          commitEdit();
          moveActive(0, e.shiftKey ? -1 : 1);
        }
        return;
      }

      if (e.key === "ArrowDown") { e.preventDefault(); moveActive(1, 0); }
      else if (e.key === "ArrowUp") { e.preventDefault(); moveActive(-1, 0); }
      else if (e.key === "ArrowRight" || e.key === "Tab") {
        e.preventDefault();
        moveActive(0, e.shiftKey ? -1 : 1);
      }
      else if (e.key === "ArrowLeft") { e.preventDefault(); moveActive(0, -1); }
      else if (e.key === "Enter" || e.key === "F2") {
        e.preventDefault();
        if (active) startEdit(active);
      }
      else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        if (active) {
          const col = columns[active.col];
          const row = rows[active.row];
          if (col?.editable && row) {
            onCellChange(row.id, col.key, col.type === "number" ? null : "");
          }
        }
      }
      else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
        if (active) {
          const col = columns[active.col];
          if (col?.editable && col.type !== "select") {
            setEditing(active);
            setEditValue(e.key);
          }
        }
      }
    },
    [editing, active, commitEdit, moveActive, startEdit, columns, rows, onCellChange]
  );

  function getCellValue(row: GridRow, colKey: string): unknown {
    return edits[row.id]?.[colKey] ?? row[colKey];
  }

  function isEdited(rowId: string, colKey: string): boolean {
    return edits[rowId]?.[colKey] !== undefined;
  }

  function formatDisplay(value: unknown, col: GridColumn): string {
    if (value == null || value === "") return "";
    if (col.type === "number") {
      const n = Number(value);
      return isNaN(n) ? String(value) : n.toLocaleString(undefined, { maximumFractionDigits: 4 });
    }
    if (col.type === "select") {
      const opt = col.options?.find((o) => o.value === value);
      return opt?.label ?? String(value);
    }
    return String(value);
  }

  function getSelectColor(value: unknown, col: GridColumn): string | undefined {
    if (col.type !== "select") return undefined;
    return col.options?.find((o) => o.value === value)?.color;
  }

  return (
    <div
      ref={gridRef}
      className="border border-border rounded-xl overflow-auto bg-card focus:outline-none max-h-[70vh]"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 z-10">
          <tr className="bg-zinc-100">
            <th className="border-b border-r border-border bg-zinc-100 px-2 py-2 text-center font-medium text-zinc-500 w-10 sticky left-0 z-20">
              #
            </th>
            {columns.map((col) => (
              <th
                key={col.key}
                className="border-b border-r border-border bg-zinc-100 px-2 py-2 font-medium text-zinc-500 whitespace-nowrap"
                style={{
                  width: col.width,
                  minWidth: col.width,
                  textAlign: col.align || "left",
                }}
              >
                {col.label}
                {col.editable && (
                  <span className="ml-1 text-accent opacity-50 text-[9px]">*</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={row.id}
              className={`${ri % 2 === 0 ? "bg-white" : "bg-zinc-50/50"} hover:bg-blue-50/30`}
            >
              <td className="border-b border-r border-border px-2 py-1.5 text-center text-zinc-400 font-mono sticky left-0 bg-inherit z-[5]">
                {ri + 1}
              </td>
              {columns.map((col, ci) => {
                const isActive = cellEq(active, { row: ri, col: ci });
                const isEditing = cellEq(editing, { row: ri, col: ci });
                const edited = isEdited(row.id, col.key);
                const value = getCellValue(row, col.key);
                const selectColor = getSelectColor(value, col);

                return (
                  <td
                    key={col.key}
                    className={`border-b border-r border-border px-0 py-0 relative cursor-default ${
                      isActive
                        ? "ring-2 ring-inset ring-blue-500 z-[6]"
                        : ""
                    } ${edited ? "bg-green-50" : ""}`}
                    style={{
                      width: col.width,
                      minWidth: col.width,
                    }}
                    onClick={() => {
                      setActive({ row: ri, col: ci });
                      if (editing && !cellEq(editing, { row: ri, col: ci })) {
                        commitEdit();
                      }
                    }}
                    onDoubleClick={() => {
                      setActive({ row: ri, col: ci });
                      startEdit({ row: ri, col: ci });
                    }}
                  >
                    {isEditing && col.type === "select" ? (
                      <select
                        ref={selectRef}
                        value={String(value ?? "")}
                        onChange={(e) => {
                          onCellChange(row.id, col.key, e.target.value);
                          setEditing(null);
                        }}
                        onBlur={() => setEditing(null)}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") {
                            e.preventDefault();
                            setEditing(null);
                          }
                        }}
                        className="w-full h-full px-2 py-1.5 text-xs border-none outline-none bg-white"
                      >
                        {col.options?.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    ) : isEditing ? (
                      <input
                        ref={inputRef}
                        type={col.type === "number" ? "number" : "text"}
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={commitEdit}
                        className="w-full h-full px-2 py-1.5 text-xs border-none outline-none bg-white"
                        style={{ textAlign: col.align || "left" }}
                      />
                    ) : (
                      <div
                        className={`px-2 py-1.5 truncate ${
                          col.editable ? "cursor-cell" : ""
                        }`}
                        style={{
                          textAlign: col.align || "left",
                          color: selectColor,
                          fontWeight: selectColor ? 500 : undefined,
                        }}
                      >
                        {formatDisplay(value, col)}
                      </div>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length + 1}
                className="px-4 py-12 text-center text-zinc-400 text-sm"
              >
                {t("grid.no_data")}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
