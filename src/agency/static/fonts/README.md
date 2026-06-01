# Local Font Policy

The cockpit uses system-local sans and mono stacks today:

- Sans: `ui-sans-serif`, `system-ui`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `sans-serif`
- Mono: `ui-monospace`, `SFMono-Regular`, `SF Mono`, `Menlo`, `Consolas`, `Liberation Mono`, `monospace`

No CDN font dependency is allowed for the Raspberry Pi cockpit. WOFF2 files are
deferred until a licensed font package is selected; until then, this documented
local fallback keeps kiosk startup independent from internet access. Named
non-system web fonts are intentionally not referenced until bundled `.woff2`
files exist in this directory.

When bundled fonts are added, place the `.woff2` files in this directory and
add `@font-face` rules in `src/agency/static/styles.css` using local relative
URLs only.
