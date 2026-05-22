# Raspberry Pi Cockpit Runbook

This is the local-only kiosk target for the V3 cockpit. The Pi should expose the
agency through the planned Cloudflare tunnel later, but the FastAPI process
binds to `127.0.0.1` by default.

## Start The App

```powershell
.\scripts\start_dev.ps1 -Kiosk
```

The script uses `/cockpit` as the operator start path and keeps uvicorn bound to
`127.0.0.1`. Real provider keys still belong in `.env`; do not store them in the
browser.

## Chromium Kiosk Command

Use a local Chromium profile dedicated to the agency:

```bash
chromium-browser \
  --kiosk http://127.0.0.1:8000/cockpit \
  --no-first-run \
  --disable-session-crashed-bubble \
  --disable-infobars \
  --user-data-dir=/home/pi/.config/trading-agency-cockpit
```

## systemd Restart

Create a service that restarts the app after boot or failure. Keep logs local.

```ini
[Unit]
Description=Trading Agency Cockpit
After=network-online.target

[Service]
WorkingDirectory=/opt/trading-agency
ExecStart=/opt/trading-agency/.venv/bin/python -m uvicorn agency.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONPATH=/opt/trading-agency/src:/opt/trading-agency/research/src
Environment=DATABASE_URL=sqlite+aiosqlite:////opt/trading-agency/agency_local.db

[Install]
WantedBy=multi-user.target
```

## Kiosk Usability

- Hide the cursor with `unclutter` after confirming touch input works.
- Disable screen sleep with `xset s off`, `xset -dpms`, and the desktop power
  manager.
- Use the cockpit touch target CSS; primary controls are at least 44px high.
- Tooltips are available on focus and tap, not only hover.
- Keep the device on local power and use a read-only dashboard account for
  remote tunnel access.

## Performance Checklist

- Cold load: time from Chromium launch to visible BLUF. Target under 3 seconds
  on dev hardware; measure Pi hardware before declaring final.
- Idle CPU: run `top` or `pidstat 5` while the cockpit sits between cycles.
  Target under 5 percent average for the browser plus uvicorn.
- 8-hour memory: record browser and uvicorn RSS at start, 4 hours, and 8 hours.
  Target under 200 MB for the app process; browser memory should be watched for
  trend growth.
- Animation: confirm gauges and panel open/close remain visually smooth. Target
  60 fps where possible and 30 fps minimum.
- Kiosk restart: reboot the Pi and confirm systemd restarts uvicorn and Chromium
  returns to `/cockpit`.
- Local log locations: systemd journal for the app, Chromium profile logs, and
  repository `logs/` when started through the Windows/dev script.

## Deferred Hardware Measurement

The repository can verify static Pi readiness and browser behavior at
`1280x720` plus a touch-emulated mobile viewport. Final CPU, memory, and cold
load numbers require the physical Pi.
