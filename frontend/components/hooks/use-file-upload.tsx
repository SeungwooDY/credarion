"use client";

import { useCallback, useRef, useState } from "react";

interface UseFileUploadProps {
  /** Comma-separated extension list, e.g. ".csv,.xlsx,.xls". Empty = accept any. */
  accept?: string;
  onSelect?: (file: File) => void;
  /** Allow picking/dropping several files; accepted ones go to `onSelectMany`. */
  multiple?: boolean;
  onSelectMany?: (files: File[]) => void;
}

/**
 * File-picker mechanics for a drag-and-drop dropzone — adapted from the
 * "use-image-upload" hook for generic (non-image) files. Ownership of the
 * selected file lives with the parent; this hook only wires the hidden input,
 * drag state, and extension validation, calling `onSelect` with accepted files.
 */
export function useFileUpload({
  accept = "",
  onSelect,
  multiple = false,
  onSelectMany,
}: UseFileUploadProps = {}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const isAccepted = useCallback(
    (file: File) => {
      const exts = accept
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
      if (!exts.length) return true;
      const name = file.name.toLowerCase();
      return exts.some((ext) =>
        ext.startsWith(".") ? name.endsWith(ext) : file.type === ext,
      );
    },
    [accept],
  );

  const openPicker = useCallback(() => fileInputRef.current?.click(), []);

  const deliver = useCallback(
    (fileList: FileList | null | undefined) => {
      const accepted = Array.from(fileList ?? []).filter(isAccepted);
      if (!accepted.length) return;
      if (multiple) onSelectMany?.(accepted);
      else onSelect?.(accepted[0]);
    },
    [isAccepted, multiple, onSelect, onSelectMany],
  );

  const handleFileChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      deliver(event.target.files);
      // Reset so selecting the same file again still fires onChange.
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [deliver],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      deliver(e.dataTransfer.files);
    },
    [deliver],
  );

  return {
    fileInputRef,
    isDragging,
    openPicker,
    handleFileChange,
    dragHandlers: { onDragOver: handleDragOver, onDragEnter: handleDragEnter, onDragLeave: handleDragLeave, onDrop: handleDrop },
  };
}
