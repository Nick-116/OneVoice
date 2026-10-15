import { describe, expect, it, vi } from "vitest";
import { applyTheme } from "./theme";

describe("applyTheme", () => {
  it("sets brand CSS variables as RGB channels and ignores invalid values", () => {
    const set = vi.fn();
    vi.stubGlobal("document", { documentElement: { style: { setProperty: set } } });
    vi.stubGlobal("window", { localStorage: { setItem: vi.fn(), getItem: vi.fn() } });
    applyTheme({ "500": "#F37121", "700": "#BE591A", "800": "red; background: url(x)" });
    expect(set).toHaveBeenCalledWith("--brand-500", "243 113 33");
    expect(set).toHaveBeenCalledWith("--brand-700", "190 89 26");
    expect(set).not.toHaveBeenCalledWith("--brand-800", expect.anything());
    vi.unstubAllGlobals();
  });
});
