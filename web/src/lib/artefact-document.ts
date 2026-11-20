/**
 * The policy applied to every HTML or SVG artefact preview. `default-src 'none'`
 * blocks every fetch, frame, font, form target and connection; only inline
 * script, inline style and data: images are let back in.
 */
export const PREVIEW_CONTENT_SECURITY_POLICY =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:";

const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CONTENT_SECURITY_POLICY}">`;
const BYTE_ORDER_MARK_CODE = 0xfeff;
const LEADING_NOISE = /^(?:\s|<!--[\s\S]*?-->|<\?xml[\s\S]*?\?>|<!doctype[^>]*>)+/i;

const stripLeadingNoise = (source: string): string => {
  const withoutMark = source.charCodeAt(0) === BYTE_ORDER_MARK_CODE ? source.slice(1) : source;
  return withoutMark.replace(LEADING_NOISE, "");
};

/**
 * Prepares an HTML artefact for `srcdoc`. The CSP meta tag is placed before any
 * of the artefact's own markup, because a policy only governs what the parser
 * meets after it. The artefact's doctype is replaced so the meta stays first.
 *
 * @param html - The artefact's HTML source
 * @returns A document whose first element is the CSP meta tag
 */
export function buildHtmlPreviewDocument(html: string): string {
  return `<!doctype html>${CSP_META}${stripLeadingNoise(html)}`;
}

/**
 * Wraps an SVG artefact in a minimal HTML document carrying the same CSP.
 *
 * @param svg - The artefact's SVG source
 * @returns A document whose first element is the CSP meta tag
 */
export function buildSvgPreviewDocument(svg: string): string {
  const style = "<style>html,body{margin:0;background:#fff}svg{max-width:100%;height:auto}</style>";
  return `<!doctype html>${CSP_META}${style}${stripLeadingNoise(svg)}`;
}
