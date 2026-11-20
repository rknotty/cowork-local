# Interface design decisions

Applied 2026-11-19 with the `scc-brand-alignment` and `ux-design` skills.
Tokens live in `src/styles/tokens.css`. Change this file and the tokens together.

## Screen brief

|                |                                                                                             |
| -------------- | ------------------------------------------------------------------------------------------- |
| Who            | An SCC Digital consultant, on their own laptop, most of the working day                     |
| One job        | Hand a document task to the local model and check what it actually did before relying on it |
| Primary action | Send a message; approve or deny an action                                                   |
| Primary object | The turn: the answer, the tool calls behind it and the files it changed                     |
| Density        | Dense working tool: 14px body, 12px secondary, 32px controls, 4px grid                      |
| Character      | Quiet authority. One accent, flat surfaces, hairline borders, the SCC gradient used once    |

## Brand application

| Element      | Decision                                                                                                                                               |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Signature    | Black header with the white SCC logo top-right (the brand's default placement) and a 3px hero-gradient rule beneath. The gradient appears nowhere else |
| Accent       | SCC blue `#0541DC` in light theme (8.4:1 on white). SCC light cyan `#6BD5FF` in dark theme, because blue on black is 2.5:1                             |
| Errors       | SCC magenta `#E5006B` (5.7:1 on white). The brand has no red; magenta is its emphasis colour, and errors are the only emphasis this tool needs         |
| Neutrals     | Brand black, white, `#F5F5F5` tint, `#D8D8D8` grey for hairlines, `#6B6B6B` for muted text and control boundaries                                      |
| Display face | Bw Gradual, product name and page titles only, Regular weight                                                                                          |
| Body face    | DM Sans for all UI and text                                                                                                                            |
| Radius       | Brand scale: 4px controls, 8px cards, panels, alerts and previews                                                                                      |
| Data green   | Not used: the brand restricts it to data visualisation                                                                                                 |

## Deliberate deviations

| Deviation                                                             | Why                                                                                                                                                                                                                    |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dark-theme error text is `#FF5C9D`, a lightened brand magenta         | Brand magenta is 3.2:1 on the dark surfaces and fails WCAG AA for text. Accessibility takes precedence                                                                                                                 |
| Dark surfaces `#0A0A0A`, `#141414`, `#050505` and white-alpha borders | The brand defines no dark UI ramp. These are derived from brand black and white, and give elevation by lightness rather than shadow                                                                                    |
| Selection fill is brand blue at 8% (cyan at 12% in dark)              | A soft fill is needed for selected rows. Derived from the accent rather than a new hue                                                                                                                                 |
| Display face at Regular weight, `font-synthesis: none`                | Only Bw Gradual Regular is installed on this device. A synthesised bold looks smeared                                                                                                                                  |
| Brand fonts are not bundled                                           | They are installed on this device, and the interface must make no network requests. On another machine the stacks fall back to Inter Tight, Inter, Helvetica Neue and Arial. Bundling Bw Gradual needs a licence check |
| Completed tool calls use muted grey, not green                        | Done states recede. Each badge carries its text label, so meaning never rests on colour                                                                                                                                |

## Governance and AI disclosure

- Every assistant answer carries an "AI-generated" label, the model that wrote it (full ID with version on hover), and "Check before relying on it".
- The network indicator reads "Local only", with a tooltip explaining it, instead of "Offline", which read as a fault.
- The status bar uses tabular figures so speed and context readings do not jitter.

## Open questions

- Product name: "Local Workbench" is a working title. An SCC product name needs the product development review the plan describes.
- Tagline: not used. It belongs on external sign-offs, not in a working tool's chrome.
