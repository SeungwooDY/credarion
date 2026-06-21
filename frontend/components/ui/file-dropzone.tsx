"use client";

import { cn } from "@/lib/utils";
import { useFileUpload } from "@/components/hooks/use-file-upload";
import { FileSpreadsheet, Upload, UploadCloud, X } from "lucide-react";

interface FileDropzoneProps {
  /** Currently selected file (owned by the parent), or null. */
  file: File | null;
  /** Comma-separated accepted extensions, e.g. ".csv,.xlsx,.xls". */
  accept: string;
  onSelect: (file: File) => void;
  onRemove: () => void;
  disabled?: boolean;
  className?: string;
  /** Localized strings. */
  labels: {
    click: string;
    hint: string;
    formats: string;
    replace: string;
    remove: string;
  };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Drag-and-drop file picker for spreadsheet uploads (CSV/XLSX) — adapted from
 * the image-upload dropzone, minus the image preview. Controlled: the parent
 * holds the file and reacts to `onSelect` / `onRemove`.
 */
export function FileDropzone({
  file,
  accept,
  onSelect,
  onRemove,
  disabled = false,
  className,
  labels,
}: FileDropzoneProps) {
  const { fileInputRef, isDragging, openPicker, handleFileChange, dragHandlers } =
    useFileUpload({ accept, onSelect });

  return (
    <div className={className}>
      <input
        type="file"
        accept={accept}
        className="hidden"
        ref={fileInputRef}
        onChange={handleFileChange}
        disabled={disabled}
      />

      {!file ? (
        <div
          onClick={disabled ? undefined : openPicker}
          {...(disabled ? {} : dragHandlers)}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-muted-foreground/25 bg-muted/50 px-4 py-8 text-center transition-colors hover:bg-muted",
            isDragging && "border-accent/50 bg-accent/5",
            disabled && "pointer-events-none opacity-50",
          )}
        >
          <div className="rounded-full bg-card p-2.5 shadow-sm">
            <UploadCloud className="h-5 w-5 text-muted-foreground" />
          </div>
          <div>
            <p className="text-sm font-medium">{labels.click}</p>
            <p className="text-xs text-muted-foreground">{labels.hint}</p>
            <p className="mt-1 text-[11px] text-muted-foreground/70">{labels.formats}</p>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2.5">
          <div className="rounded-md bg-accent/10 p-2">
            <FileSpreadsheet className="h-4 w-4 text-accent" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{file.name}</p>
            <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
          </div>
          <button
            type="button"
            onClick={openPicker}
            disabled={disabled}
            title={labels.replace}
            aria-label={labels.replace}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            <Upload className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onRemove}
            disabled={disabled}
            title={labels.remove}
            aria-label={labels.remove}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-red-600 disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}
