import { describe, expect, it } from "vitest";
import { slugFromPath } from "../App";

describe("slugFromPath", () => {
  it("accepts /campus/<slug> (canonical) and /<slug>", () => {
    expect(slugFromPath("/campus/east-hartford")).toBe("east-hartford");
    expect(slugFromPath("/campus/east-hartford/")).toBe("east-hartford");
    expect(slugFromPath("/east-hartford")).toBe("east-hartford");
  });
  it("treats / and /campus as the campus chooser", () => {
    expect(slugFromPath("/")).toBeNull();
    expect(slugFromPath("/campus")).toBeNull();
  });
  it("rejects anything else", () => {
    expect(slugFromPath("/campus/a/b")).toBeUndefined();
    expect(slugFromPath("/campus/BAD SLUG")).toBeUndefined();
    expect(slugFromPath("/x/y")).toBeUndefined();
  });
});
