# Local Font Policy

The cockpit uses system-local sans and mono stacks today:

- Sans: `Inter`, `Segoe UI`, `Arial`, `sans-serif`
- Mono: `ui-monospace`, `SFMono-Regular`, `Consolas`, `Liberation Mono`, `monospace`

No CDN font dependency is allowed for the Raspberry Pi cockpit. WOFF2 files are
deferred until a licensed font package is selected; until then, this documented
local fallback keeps kiosk startup independent from internet access.

When bundled fonts are added, place the `.woff2` files in this directory and
add `@font-face` rules in `src/agency/static/styles.css` using local relative
URLs only.
