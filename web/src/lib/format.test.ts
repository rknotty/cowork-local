import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatDuration,
  formatTimestamp,
  formatTokens,
  inferArtefactKind,
  shortModelName,
} from "./format";

describe("format helpers", () => {
  it("should show short durations in milliseconds and longer ones in seconds", () => {
    expect(formatDuration(340)).toBe("340 ms");
    expect(formatDuration(2400)).toBe("2.4 s");
  });

  it("should scale file sizes to a readable unit", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("should group token counts with separators", () => {
    expect(formatTokens(32768)).toBe("32,768");
  });

  it("should return an unparseable timestamp unchanged", () => {
    expect(formatTimestamp("not a date")).toBe("not a date");
    expect(formatTimestamp("2026-01-15T09:30:00Z")).toContain("2026");
  });

  it("should drop the version suffix from a model ID", () => {
    expect(shortModelName("example-model-14b:2")).toBe("example-model-14b");
    expect(shortModelName("plain")).toBe("plain");
  });

  it("should infer the artefact kind from the extension, defaulting to text", () => {
    expect(inferArtefactKind("out/page.HTML")).toBe("html");
    expect(inferArtefactKind("notes.md")).toBe("markdown");
    expect(inferArtefactKind("deck.pptx")).toBe("pptx");
    expect(inferArtefactKind("data.csv")).toBe("text");
    expect(inferArtefactKind("README")).toBe("text");
  });
});
