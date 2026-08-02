import { useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
const STORAGE_KEY = "kb-theme";

export function readThemePreference(
  storage: Pick<Storage, "getItem"> = localStorage,
): ThemePreference {
  const value = storage.getItem(STORAGE_KEY);
  return value === "light" || value === "dark" || value === "system"
    ? value
    : "system";
}

export function resolveTheme(
  preference: ThemePreference,
  systemDark: boolean,
): ResolvedTheme {
  return preference === "system" ? (systemDark ? "dark" : "light") : preference;
}

export function applyTheme(preference: ThemePreference): ResolvedTheme {
  const resolved = resolveTheme(
    preference,
    matchMedia("(prefers-color-scheme: dark)").matches,
  );
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.bsTheme = resolved;
  document.documentElement.style.colorScheme = resolved;
  localStorage.setItem(STORAGE_KEY, preference);
  return resolved;
}

export function useThemePreference() {
  const [preference, setPreference] =
    useState<ThemePreference>(readThemePreference);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(preference);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [preference]);
  return { preference, setPreference };
}
