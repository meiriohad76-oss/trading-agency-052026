# 09 · Raspberry Pi Deployment Notes

The target hardware is a Raspberry Pi (likely 4 or 5). The cockpit runs in **kiosk mode** — full-screen browser, no chrome, no taskbar, no way to alt-tab away. The user interacts via touchscreen or a wireless keyboard/mouse.

Some constraints below are general kiosk wisdom; others are Pi-specific. **[CONFIRM]** with the human which Pi model and whether the display is touch or not.

## Performance budget

The Pi has limited resources compared to a dev machine. The cockpit must be light:

- **Cold start to interactive: < 3 seconds.** The Pi boots into kiosk; the cockpit should be visible and responsive within 3 seconds of the browser opening.
- **Idle CPU: < 5%.** Between cycles, the cockpit is wallpaper. The countdown ticks; nothing else should be running.
- **Memory: < 200 MB after 8 hours.** No leaks. The prototype's React state is tiny; this is achievable if the implementation is disciplined about event listeners and intervals.
- **Frame rate: 60 fps on transitions, 30 fps minimum.** The arc-gauge needle animation, the conviction bar fills, the fly-to-manifest chip — all should be smooth. They're SVG + CSS transform, which the Pi's GPU handles fine.

## Drop external dependencies

The prototype loads React and Babel from unpkg.com. **The Pi may not have reliable internet.** Bundle everything:

- **No CDNs.** React, ReactDOM, any libs → bundle locally.
- **No Babel in browser.** Pre-compile the JSX. The prototype uses `@babel/standalone` for convenience; production uses Vite / esbuild / whatever the Codex build pipeline is.
- **No Google Fonts.** The prototype uses system fonts only (`-apple-system` / Segoe UI / system-ui) — which the Pi may not have. **Bundle the actual font files** for the sans + mono stacks:
  - Sans: ship **Inter** or **IBM Plex Sans** locally
  - Mono: ship **JetBrains Mono** or **IBM Plex Mono** locally
  - Use `@font-face` with WOFF2 files in `/public/fonts/`

## Browser & kiosk setup

**[CONFIRM]** with the human, but recommended stack:

- **OS:** Raspberry Pi OS Lite or full
- **Browser:** Chromium (comes with full Pi OS) — has good kiosk support
- **Launch:** `chromium-browser --kiosk --noerrdialogs --disable-infobars --disable-pinch --overscroll-history-navigation=disabled http://localhost:PORT`
- **Autostart:** systemd service that launches the browser on boot, restarts on crash
- **Cursor:** `unclutter` to auto-hide the mouse cursor when idle
- **Screen sleep:** disable (`xset -dpms` + `xset s off`)

## Local server

The cockpit should be served by a local HTTP server (probably the same Node process that runs the agent). This avoids `file://` quirks and lets the app fetch from `/api/*` cleanly.

Don't ship a separate frontend dev server in production — bundle the static assets and serve from the agent's existing HTTP server.

## Input

### Touch (likely default)

- **Hit targets:** bump all tappable elements to **≥ 44px** in at least one dimension. The prototype's decision buttons (Approve/Defer/Reject) are too small for touch as-is — enlarge.
- **No hover.** Tooltips (`<CockpitTip>`) should appear on tap-and-hold (~300ms). The prototype uses mouseEnter/mouseLeave; add touch handlers.
- **Tap highlight:** disable the default `-webkit-tap-highlight-color: transparent` globally. The cockpit handles its own visual feedback.
- **Pinch / pan disabled.** The CSS `touch-action: manipulation` on tappable elements; the kiosk launch flag `--disable-pinch` blocks page-level zoom.

### Keyboard / mouse fallback

If the Pi has a wireless keyboard:
- **Escape closes overlays** — already implemented in `<CockpitOverlay>`
- **Tab cycling** — verify focus order makes sense; the prototype doesn't worry about this
- **Enter on focused button** — standard HTML, no work needed

## Display

**Target: 1920 × 1080 landscape.** The prototype's artboards are 1440 × 1100 (A) and 1440 × 1000 (C). The standalone HTML files use a **fit-scale** transform to fill the viewport while preserving the design's pixel relationships.

For other resolutions:
- **1280 × 720:** scales down proportionally; readability is borderline at the smallest text sizes (9px labels). Consider bumping minimums by 1px on small displays.
- **2560 × 1440 (rare for Pi):** scales up. Should look fine.
- **Portrait orientation:** **don't support it.** The cockpit is fundamentally landscape. If the Pi has a portrait display, that's a different product.

## Power & resilience

- **Crash recovery:** if the browser crashes, systemd should restart it. The cockpit should restore session state from localStorage (see `07-data-schema.md → session state`).
- **Network loss:** the agent runs locally, so even if internet dies, the agent can still cycle (off-cached data) and the cockpit still works. The cockpit's only network dep is to the agent's local API.
- **Power loss:** when the Pi reboots, the cockpit comes back up automatically. The user shouldn't notice the difference between a clean reboot and a crash.
- **Updates:** the cockpit ships as a single bundle (HTML + JS + CSS + fonts) that can be replaced on disk. The systemd service watches the bundle directory and restarts the browser on file change. Or rely on the user to refresh manually after `git pull`.

## Telemetry / observability

The cockpit is **single-user, single-device.** Don't ship analytics, don't phone home, don't even log to a remote service. If something goes wrong:
- Browser console logs to local file (via the systemd service redirect)
- Agent logs to local file
- That's it.

The user owns the data. Period.

## Security

- The cockpit and the agent are on the **same Pi**. No CORS issues, no auth between them is strictly required — but **do add a localhost-only bind** to the agent's API. Don't listen on `0.0.0.0` by default.
- If the Pi is on a home network, anyone with network access could in principle reach the cockpit. **[CONFIRM]** — likely fine for a personal-use kiosk, but if the human wants tighter security: HTTP basic auth on the agent's API, or a TLS cert via local CA.
- **The submit gate's confirmation phrase is not security.** It's a UX speed-bump. A determined toddler with access to the Pi could submit orders. If real money is ever involved (post-v1), add a real auth flow (PIN / hardware key / biometric).

## What the prototype's standalone files DON'T do that the real product needs

| Concern | Prototype | Real product |
|---|---|---|
| Module bundling | Babel-in-browser via `<script type="text/babel">` | Pre-compiled bundle |
| Fonts | System stack | Locally-served WOFF2 |
| State persistence | None — reloads reset everything | localStorage for tweak prefs + session restore |
| API integration | Static `window.COCKPIT_DATA` | Fetch from `/api/*` + SSE for monitor stream |
| Submission | UI-only (state flips to "submitted") | POST to broker, await ack, handle errors |
| Error states | None — assumes data is valid | API errors, network blips, malformed payloads |
| Auth | None | TBD (likely none for v1, see above) |
| Logging | None | Local file via the agent process |
| Updates | Manual | Probably manual; auto-update is overkill for one user |

## Quick-start for Codex

If you want to test the prototype on the Pi before writing any new code:

```bash
# On the Pi
cd /home/pi
git clone <this-project>
cd <this-project>

# Serve the prototype statically
python3 -m http.server 8080

# In the browser (kiosk):
chromium-browser --kiosk http://localhost:8080/Variation%20A.html
```

The prototype runs on the Pi as-is (with the unpkg CDN dependency — needs internet for first load). This is a useful intermediate step before doing the full bundling work. Confirms the design works on the target hardware before you build the production version.
