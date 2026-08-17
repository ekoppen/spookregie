import { describe, it, expect } from "vitest";
import { parseLogPayload } from "../../admin/frontend/src/lib/wsMessage";

describe("parseLogPayload", () => {
  it("parses a valid log payload", () => {
    const payload = JSON.stringify({ ts: 123.0, level: "INFO", msg: "test" });
    const result = parseLogPayload(payload);
    expect(result).toEqual({ node: "", ts: 123.0, level: "INFO", msg: "test" });
  });

  it("returns null for malformed JSON instead of throwing", () => {
    expect(parseLogPayload("dit is geen JSON")).toBeNull();
  });

  it("returns null for valid JSON that isn't a log-shaped object", () => {
    expect(parseLogPayload(JSON.stringify([1, 2, 3]))).toBeNull();
  });
});
