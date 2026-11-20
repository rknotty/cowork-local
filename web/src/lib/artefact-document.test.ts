import { describe, expect, it } from "vitest";
import {
  buildHtmlPreviewDocument,
  buildSvgPreviewDocument,
  PREVIEW_CONTENT_SECURITY_POLICY,
} from "./artefact-document";

const EXPECTED_META =
  `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; ` +
  `script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:">`;

describe("artefact preview documents", () => {
  it("should use the exact policy that blocks all network access", () => {
    expect(PREVIEW_CONTENT_SECURITY_POLICY).toBe(
      "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:"
    );
  });

  it("should inject the CSP meta tag before any artefact markup", () => {
    const html = '<html><head><script src="https://example.invalid/x.js"></script></head></html>';

    const document = buildHtmlPreviewDocument(html);

    expect(document.startsWith(`<!doctype html>${EXPECTED_META}`)).toBe(true);
    expect(document.indexOf(EXPECTED_META)).toBeLessThan(document.indexOf("<script"));
    expect(document.endsWith(html)).toBe(true);
  });

  it("should replace the artefact's own doctype so the meta tag stays first", () => {
    const document = buildHtmlPreviewDocument(
      `${String.fromCharCode(0xfeff)}  <!-- c --><!DOCTYPE html>\n<html></html>`
    );

    expect(document).toBe(`<!doctype html>${EXPECTED_META}<html></html>`);
  });

  it("should still inject the policy into an empty or fragment artefact", () => {
    expect(buildHtmlPreviewDocument("")).toBe(`<!doctype html>${EXPECTED_META}`);
    expect(buildHtmlPreviewDocument("<p>Hi</p>")).toBe(`<!doctype html>${EXPECTED_META}<p>Hi</p>`);
  });

  it("should wrap an SVG artefact in a document carrying the same policy", () => {
    const svg = '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"></svg>';

    const document = buildSvgPreviewDocument(svg);

    expect(document.startsWith(`<!doctype html>${EXPECTED_META}`)).toBe(true);
    expect(document).not.toContain("<?xml");
    expect(document.endsWith('<svg xmlns="http://www.w3.org/2000/svg"></svg>')).toBe(true);
  });
});
