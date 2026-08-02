import { beforeEach, describe, expect, it, vi } from "vitest";
import { applyTheme, readThemePreference, resolveTheme } from "./theme";

describe("theme behavior", () => {
  beforeEach(() => localStorage.clear());
  it("defaults invalid persisted values to system", () => {
    localStorage.setItem("kb-theme", "invalid");
    expect(readThemePreference()).toBe("system");
  });
  it("resolves system preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
  it("applies and persists a theme", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    expect(applyTheme("dark")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("kb-theme")).toBe("dark");
  });
});
