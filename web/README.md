# Local Workbench web interface

A single-page React and TypeScript app for the local agent orchestrator. It renders
the orchestrator's events and posts the user's actions. It makes no decisions of its
own. The API and event contract is in `../docs/event-contract.md`.

The product name is one constant in `src/brand.ts`.

## Run

Requires Node 20 or later.

```
npm install
npm run dev
```

`npm run dev` serves the app on `127.0.0.1` and proxies `/api` to the orchestrator at
`http://127.0.0.1:8765`, so start the orchestrator first.

## Build

```
npm run build
```

The output goes to `dist/`. In production the orchestrator serves `dist/` itself, at
the same origin as the API. The app only ever calls relative `/api/...` URLs, so it
must be served same-origin; there is no configurable API host.

## Test and check

```
npm test              # Vitest, jsdom
npm run test:coverage # the same, with a coverage report
npm run lint          # ESLint
npm run type-check    # tsc --noEmit
npm run format:check  # Prettier
```

Tests run against a typed in-memory orchestrator in `src/test/mock-orchestrator.ts`,
which replaces `fetch` and `EventSource`. Nothing in the tests touches the network.

## No external requests

Every asset is bundled: no CDN, no web fonts, no analytics. The app makes requests
only to its own origin. Two further guards keep it that way:

- HTML and SVG artefact previews render in an `<iframe sandbox="allow-scripts">` from
  `srcdoc`, with a Content-Security-Policy meta tag injected ahead of the artefact's
  markup (`default-src 'none'`), so a preview cannot fetch anything.
- Markdown from the model does not render raw HTML, and images are shown only when
  they are inline `data:` URIs.

## Layout of the source

- `src/api/` contract types, the API client and its error mapping, event validation
- `src/state/` the session reducer, the event-stream hook and the React contexts
- `src/hooks/` data loading, health polling, uploads, voice recording, theme
- `src/components/` the rail, conversation, right panel, memory page and status bar
- `src/lib/` artefact preview documents and formatting helpers
- `src/styles/` design tokens (light and dark), layout and syntax colours
- `src/test/` the mock orchestrator and render helpers used by the tests
