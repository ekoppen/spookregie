import { describe, it, expect } from "vitest";
import { pixelToFraction, fractionToPixel, clampFraction } from "../../admin/frontend/src/lib/overlayMath";

describe("pixelToFraction", () => {
  it("converts a pixel offset to a 0-1 fraction of the container", () => {
    expect(pixelToFraction(50, 200)).toBe(0.25);
  });

  it("handles the container edges", () => {
    expect(pixelToFraction(0, 200)).toBe(0);
    expect(pixelToFraction(200, 200)).toBe(1);
  });
});

describe("fractionToPixel", () => {
  it("is the inverse of pixelToFraction", () => {
    expect(fractionToPixel(0.25, 200)).toBe(50);
  });
});

describe("clampFraction", () => {
  it("clamps values below 0 to 0", () => {
    expect(clampFraction(-0.5)).toBe(0);
  });

  it("clamps values above 1 to 1", () => {
    expect(clampFraction(1.5)).toBe(1);
  });

  it("leaves in-range values unchanged", () => {
    expect(clampFraction(0.42)).toBe(0.42);
  });
});
