"use client";

/**
 * Theme preference, read from localStorage.
 *
 * localStorage is external mutable state, so it is read through
 * `useSyncExternalStore` rather than copied into React state inside an effect.
 * That avoids the extra render an effect+setState would cause, and it keeps
 * two components showing the theme (the header toggle and the profile page)
 * in sync automatically — changing it in one updates the other with no prop
 * drilling or context.
 */

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark" | "system";

const KEY = "vt-theme";
const listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  // `storage` fires for other tabs; the local set below notifies this one.
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

function getSnapshot(): Theme {
  return (localStorage.getItem(KEY) as Theme) ?? "system";
}

// The server has no localStorage; "system" matches the pre-paint script's
// default, so the first client render agrees with the markup.
function getServerSnapshot(): Theme {
  return "system";
}

export function prefersDark(theme: Theme): boolean {
  return (
    theme === "dark" ||
    (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches)
  );
}

export function setTheme(next: Theme) {
  localStorage.setItem(KEY, next);
  document.documentElement.classList.toggle("dark", prefersDark(next));
  listeners.forEach((l) => l());
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return [theme, setTheme];
}
