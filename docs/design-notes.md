# Design notes: Meta's design language, and Jig's own take on it

Written before any UI work, as the brief asked. The goal is for Jig to *feel* at home
next to Meta's developer products while using none of Meta's assets: no logos, no
Meta or Muse names in our branding, no proprietary fonts, no copied icons or images.

## What we looked at (2026-10-26)

- **dev.meta.ai** (Model API docs and dashboard) and **meta.ai**. This container could
  not reach them directly, so observations come from search-indexed copies of those pages.
- **Meta's official cookbook demo UIs** (`github.com/meta-models/meta-model-cookbook`,
  MIT-licensed), e.g. the Muse robotics kiosk page. These are first-party Meta developer
  UIs, and the most concrete source we have for tokens Meta uses in dev tooling.
- **Public write-ups of Meta's brand and store design system** (third-party
  reconstructions; treated as directional, not authoritative).
- **developers.meta.com/horizon/design** (fonts and icons guidance for Horizon OS).

## Patterns observed

### Color
- One confident blue carries every primary action. Meta's brand blue is **#0064E0**,
  with a brighter azure **#0082FB** used on dark backgrounds and in gradients. The
  cookbook UI declares exactly these two (`--blue: #0064e0; --azure: #0082fb`).
- Neutrals are cool and slightly blue-tinted, never pure gray. Light surfaces sit on an
  off-white canvas (around #F1F4F7). Body text is a deep blue-black (around #1C2B33)
  rather than #000.
- Dark mode is a deep navy-ink, not black: cookbook values are ink `#09101D`, panel
  `#121826`, hairlines `#26324A`, muted text `#A9B5C8`.
- Status colors are used sparingly: a green near #31A24C for success, purple #7F50D5 as
  an occasional AI accent, red reserved for destructive or failing states.

### Type
- Meta's brand face is *Optimistic* (proprietary, Dalton Maag). Developer UIs, including
  Meta's own cookbook demos, fall back to **Inter** / system UI.
- Scale is restrained: big, tight, semibold display headings; 14–16 px body; 12–13 px
  captions with generous line height. Weight contrast does the hierarchy, not color.
- Tabular numbers for data.

### Spacing and layout
- Airy. A 4 px base grid, with 8/12/16/24/32 doing most of the work. Cards breathe:
  16–24 px padding.
- Content is grouped into rounded cards on a tinted canvas instead of divided by lines.

### Corner radii
- Large and friendly. Cards 15–22 px in the cookbook UI, up to 24–32 px on marketing
  surfaces. Buttons and chips are **pills** (fully rounded). Inputs 10–12 px.

### Elevation
- Mostly flat; separation comes from surface tint. Shadows are soft, wide and low-opacity,
  used for floating layers (menus, popovers, modals): e.g. `0 14px 40px rgb(0 0 0 / 0.4)`
  on dark. Hover lifts by a pixel or two with a slightly stronger shadow.

### Buttons and inputs
- Primary: solid blue pill, white semibold label. Secondary: tinted neutral pill.
  Tertiary: text-only in blue. Marketing pages sometimes use a black pill as primary.
- Inputs: filled neutral background, no heavy border, a 2 px blue focus ring.
- Icon buttons are circular.

### Dark mode
- First-class, not an inversion. Navy-ink canvas, slightly lighter panels, hairline
  borders at low contrast, and the brighter azure for accents so blue stays legible.

### Motion
- Quick and calm: 120–200 ms, ease-out for enter, ease-in for exit. Small translate
  (2–4 px) plus fade, no bouncy springs. `prefers-reduced-motion` turns it off.

## Jig's design system (our own tokens)

Defined in `frontend/src/styles/tokens.css`. Values are ours; the feel is Meta-adjacent.

| Token | Light | Dark |
|---|---|---|
| `--accent` | `#0A66E8` | `#3A8DFF` |
| `--accent-strong` (hover) | `#0753C2` | `#5FA3FF` |
| `--accent-soft` (tinted fills) | `#E6F0FE` | `#14284A` |
| `--canvas` | `#F2F5F8` | `#0A0F1A` |
| `--surface` (cards) | `#FFFFFF` | `#121927` |
| `--surface-2` (inputs, chips) | `#ECF0F4` | `#1A2334` |
| `--line` | `#DFE5EC` | `#253047` |
| `--text` | `#17222B` | `#E8EDF5` |
| `--text-muted` | `#5B6B78` | `#9AA8BC` |
| `--success` | `#1F9D55` | `#3CC47C` |
| `--warning` | `#C27A00` | `#F2B13B` |
| `--danger` | `#D93A3A` | `#FF6B6B` |
| `--ai` (agent accents) | `#7048E8` | `#9B7BFF` |

- **Type:** Inter Variable (OFL-1.1, bundled via `@fontsource-variable/inter`).
  Scale: 12 / 13 / 14 / 16 / 20 / 28 px; weights 400 / 500 / 600 / 700; tabular numerals
  in data readouts.
- **Spacing:** 4 px grid (`--space-1` to `--space-8`: 4, 8, 12, 16, 20, 24, 32, 40).
- **Radii:** `--radius-sm` 8, `--radius-md` 12, `--radius-lg` 18, `--radius-xl` 24,
  `--radius-pill` 999.
- **Elevation:** `--shadow-1` (cards, barely there), `--shadow-2` (hover/raised),
  `--shadow-pop` (menus and dialogs).
- **Motion:** `--ease-out: cubic-bezier(.2,.8,.2,1)`, 150 ms default, 220 ms for panels;
  disabled under `prefers-reduced-motion`.
- **Icons:** Lucide (ISC), 16–18 px, 1.75 stroke.
- **Brand mark:** Jig's own mark (a simple rounded square holding an "L" bracket
  profile), drawn as inline SVG. Not derived from any Meta mark.
- **Credit line:** "Built with Meta Muse models" in small muted text, allowed by the brief.

## Product-specific rules

- **The viewport is the hero.** Panels float as cards around it with gutters, so the
  model is never boxed in by heavy chrome.
- **One verdict, big.** FEA outcome is a single large PASS/FAIL badge with the safety
  factor; details sit behind it.
- **Agents are visibly agents.** Agent Trace entries use the `--ai` purple accent and a
  per-agent glyph, so it is always clear what the AI did and what deterministic checks
  decided.
- **Plain English first.** Every engineering term in the UI gets a tooltip
  (safety factor, von Mises, fillet, overhang...).
- **The FEA disclaimer is persistent** wherever results are shown: "FEA results are
  simulation estimates, not certification. Verify critical parts with physical testing."
