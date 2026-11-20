import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";

const THEME_STORAGE_KEY = "workbench.theme";

const isThemeChoice = (candidate: unknown): candidate is ThemeChoice =>
  candidate === "system" || candidate === "light" || candidate === "dark";

const readStoredTheme = (): ThemeChoice => {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    // Storage can be blocked by browser policy; the system theme is a safe default.
    return "system";
  }
};

const storeTheme = (theme: ThemeChoice): void => {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The choice still applies for this page load; it just will not persist.
  }
};

/**
 * Tracks the colour theme. "system" follows prefers-color-scheme; an explicit
 * choice is stored in this browser and applied through `data-theme` on <html>.
 *
 * @returns The current choice and a setter
 */
export function useTheme(): [ThemeChoice, (theme: ThemeChoice) => void] {
  const [theme, setThemeState] = useState<ThemeChoice>(readStoredTheme);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
  }, [theme]);

  const setTheme = useCallback((next: ThemeChoice): void => {
    storeTheme(next);
    setThemeState(next);
  }, []);

  return [theme, setTheme];
}
