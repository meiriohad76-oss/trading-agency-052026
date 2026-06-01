# 08 · Tweaks & Configuration

The prototype exposes four configurable axes through a floating "Tweaks" panel. In the real product, these ship as **runtime user preferences** — accessible through the same panel, persisted across sessions on the Pi.

The four axes are independent — any combination should render correctly. The prototype's Tweaks panel demonstrates this; matrix-test on integration.

## Axis 1: Color preset

Three options. All map to the same role-based palette; only the accent hue + saturation changes.

| Preset | Description | Hex (vA palette) |
|---|---|---|
| `amber` | Single accent — amber. Most coherent / restrained. | `--amber: #ffb845`, `--cyan: #ffb845` (same) |
| `duotone` | Amber + cyan — distinguishes "LLM voice" from "primary". | `--amber: #ffb845`, `--cyan: #5ad7f0` |
| `saturated` | Higher-chroma everything — for users who want more pop. | `--amber: #ffce3a`, `--cyan: #00e0ff`, `--green: #00ff9d`, `--red: #ff3a4e` |

**Default: `amber`** (the most reserved option; the cockpit looks expensive when restrained).

Variation C uses different variable names (`--pri`, `--pri-d`, `--acc`) — the preset definitions in the standalone HTML files handle the mapping. Keep them in sync if you change anything.

## Axis 2: Theme

Three options for the background + neutrals.

| Theme | Description |
|---|---|
| `dark` | Pure dark slate — `--bg: #06080d`. The deepest backdrop. |
| `accent` | Slightly blue-shifted dark — `--bg: #0a1018`. Default. Reads "cockpit". |
| `light` | Warm paper background — `--bg: #f4ede0`. Inverted everything; for daytime / glare conditions. |

**Default: `accent`** for the prototype on the design canvas. **For Pi kiosk**, `accent` is also the default — but the light theme is worth offering for users in a sunny room.

The `light` theme **inverts the text colors** (`--tx` becomes near-black, `--tx-2` and `--tx-3` become warm browns). Status colors (green/red/amber) stay roughly the same — they're warm enough to read on either backdrop.

## Axis 3: Density

Two options. This is the **most product-significant** of the four — it's not just visual taste, it changes what the user sees.

| Density | Description |
|---|---|
| `full` | Default. Everything: instrument cluster, engine strip, telemetry, glows, animations. |
| `calm` | Stripped: hides the cluster (Variation A), hides the middle telemetry block + bottom engine strip (Variation C), kills text-shadow glows, dims thin separators. |

**When the user wants `calm`:** between cycles, when the cockpit is wallpaper. They're not making decisions; they don't need the loud chrome. The Portfolio Monitor panel is still accessible if they want to watch the event stream.

**Implementation:** the prototype uses CSS `.vA.calm` / `.vC.calm` selectors that override styles via `!important`. This is heavy-handed; on integration, prefer either:
- A React-level conditional (don't render the cluster when calm) — cleaner
- A data-attribute on the root (`data-density="calm"`) with CSS rules

But **either works** — the calm mode is a real-product concern, just clean it up however fits your stack.

**[CONFIRM]** with the human: should calm mode be **auto-engaged** between cycles (e.g. after submission, the cockpit fades to calm) or **manual only**? The prototype is manual. Auto could be nice but the trigger logic needs care.

## Axis 4: Scenario

The four states from `06-states.md`. In the prototype, this is a debug toggle. **In the real product, scenario is determined by the backend** — not user-selectable.

The Tweaks panel should still expose it for QA / demo purposes — possibly behind a "developer" flag.

## The Tweaks panel itself

In the prototype, the panel is a floating draggable card in the bottom-right corner. The source is in `tweaks-panel.jsx` (a starter component — read it, don't re-engineer it).

**For the real product on Pi:** the floating panel may not be the right UX. Consider:
- A gear icon in the topbar that opens a settings overlay
- A long-press gesture on the brand logo (kiosk-friendly hidden access)
- A dedicated settings screen reachable from the engine strip

**[CONFIRM]** what UX the human wants. The prototype's floating panel is a designer's convenience, not a product decision.

## Things that are NOT tweaks

- **Brand / name** — "AGENCY · COCKPIT" / "AGENCY · MISSION CTRL". Configurable in code only.
- **Layout pattern (A vs C)** — these are different products. The Pi ships one or the other. Building both in one binary is overkill.
- **Cycle interval** — determined by the agent, not user-configurable.
- **Threshold values** — those live in the Policy panel, not the Tweaks panel. They affect decisions, not visuals.

## CSS variable contract

The full set of CSS variables, defined per scope (`.vA` / `.vC`) and overridden by tweak presets. Both variations share the role names but use different variable names:

| Role | `.vA` var | `.vC` var |
|---|---|---|
| Background | `--bg` / `--bg-2` / `--bg-3` | `--bg` |
| Panel | `--panel` | `--panel` / `--panel-2` |
| Border | `--bd` / `--bd-2` | `--bd` / `--bd-2` |
| Text primary | `--tx` | `--tx` |
| Text secondary | `--tx-2` | `--tx-2` |
| Text tertiary | `--tx-3` | `--tx-3` |
| Primary accent | `--amber` / `--amber-d` | `--pri` / `--pri-d` |
| Secondary accent | `--cyan` | `--acc` |
| Positive | `--green` | `--pos` |
| Negative | `--red` | `--neg` |
| Warning | `--orange` (rarely used) | `--warn` |

**Unify the variable names on integration.** Pick one set (the `.vA` set or a fresh role-based set) and migrate. The split is a prototype artifact.

## The EDITMODE marker

In the prototype, the tweak defaults are wrapped in `/*EDITMODE-BEGIN*/{...}/*EDITMODE-END*/` so the design tool can rewrite them on user changes. **This is design-tool plumbing — strip it from the production build.** Hard-code the defaults or load from the Pi's config file.
