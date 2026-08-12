"use client";

/**
 * Global open/closed state for the AI chat panel — same lightweight
 * external-store pattern as the language and period stores, so any component
 * (sidebar item, floating bubble) can open the one chat panel.
 */
import { useSyncExternalStore } from "react";

let isOpen = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

export function openChat() {
  isOpen = true;
  emit();
}

export function closeChat() {
  isOpen = false;
  emit();
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

export function useChatOpen(): boolean {
  return useSyncExternalStore(subscribe, () => isOpen, () => false);
}
