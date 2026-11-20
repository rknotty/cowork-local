import type { ArtefactKind } from "../api/types";

const BYTES_PER_KILOBYTE = 1024;
const MS_PER_SECOND = 1000;

/**
 * Formats a duration for display.
 *
 * @param durationMs - Duration in milliseconds
 * @returns e.g. "340 ms" or "2.4 s"
 */
export function formatDuration(durationMs: number): string {
  if (durationMs < MS_PER_SECOND) {
    return `${Math.round(durationMs)} ms`;
  }
  return `${(durationMs / MS_PER_SECOND).toFixed(1)} s`;
}

/**
 * Formats a file size for display.
 *
 * @param sizeBytes - Size in bytes
 * @returns e.g. "512 B", "3.4 KB" or "1.2 MB"
 */
export function formatBytes(sizeBytes: number): string {
  if (sizeBytes < BYTES_PER_KILOBYTE) {
    return `${sizeBytes} B`;
  }
  const kilobytes = sizeBytes / BYTES_PER_KILOBYTE;
  if (kilobytes < BYTES_PER_KILOBYTE) {
    return `${kilobytes.toFixed(1)} KB`;
  }
  return `${(kilobytes / BYTES_PER_KILOBYTE).toFixed(1)} MB`;
}

/**
 * Formats a token count with thousands separators.
 *
 * @param tokens - A token count
 * @returns e.g. "12,480"
 */
export function formatTokens(tokens: number): string {
  return tokens.toLocaleString("en-GB");
}

/**
 * Formats an ISO timestamp as a short local date and time.
 *
 * @param isoTimestamp - An ISO 8601 string
 * @returns A local date-time, or the input unchanged when it cannot be parsed
 */
export function formatTimestamp(isoTimestamp: string): string {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) {
    return isoTimestamp;
  }
  return parsed.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Formats a turn duration in seconds with one decimal place, always in seconds
 * so answers can be compared at a glance.
 *
 * @param durationMs - Milliseconds
 * @returns For example "12.4 s" or "134.0 s"
 */
export function formatSeconds(durationMs: number): string {
  return `${(durationMs / 1000).toFixed(1)} s`;
}

/**
 * Shortens a model ID for inline display by dropping the version suffix.
 * The full ID belongs in a title attribute next to it.
 *
 * @param modelId - e.g. "qwen3-14b-generic-gpu:2"
 * @returns e.g. "qwen3-14b-generic-gpu"
 */
export function shortModelName(modelId: string): string {
  const [name] = modelId.split(":");
  return name ?? modelId;
}

const KIND_BY_EXTENSION: Record<string, ArtefactKind> = {
  html: "html",
  htm: "html",
  svg: "svg",
  md: "markdown",
  markdown: "markdown",
  docx: "docx",
  pptx: "pptx",
  xlsx: "xlsx",
  pdf: "pdf",
};

/**
 * Infers how to preview a workspace file from its extension, for files opened
 * from the file list rather than announced by an `artefact` event.
 *
 * @param relativePath - Path relative to the session workspace
 * @returns The matching artefact kind, or "text" for anything unrecognised
 */
export function inferArtefactKind(relativePath: string): ArtefactKind {
  const extension = relativePath.split(".").pop()?.toLowerCase() ?? "";
  return KIND_BY_EXTENSION[extension] ?? "text";
}
