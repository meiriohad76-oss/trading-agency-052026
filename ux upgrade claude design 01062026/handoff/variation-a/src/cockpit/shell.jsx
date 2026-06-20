// Cockpit shared shell — animation hooks, tooltip, overlay, countdown.
// Theme-neutral; uses CSS variables that vA/vC scopes already define.

// ── countdown timer ───────────────────────────────────────────────
window.useCockpitCountdown = function(initialSeconds = 13 * 60 + 14) {
  const [s, setS] = React.useState(initialSeconds);
  React.useEffect(() => {
    const t = setInterval(() => setS(v => v > 0 ? v - 1 : 13 * 60), 1000);
    return () => clearInterval(t);
  }, []);
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return { mm, ss, total: s };
};

// ── animated number (for dial fills, etc.) ────────────────────────
window.useAnimatedValue = function(target, duration = 700, deps = []) {
  const [v, setV] = React.useState(0);
  React.useEffect(() => {
    let raf, start;
    const tick = (now) => {
      if (!start) start = now;
      const p = Math.min(1, (now - start) / duration);
      // ease-out cubic
      const e = 1 - Math.pow(1 - p, 3);
      setV(target * e);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, deps);
  return v;
};

// ── tooltip ───────────────────────────────────────────────────────
window.CockpitTip = function({ tip, children, side = 'top' }) {
  const [show, setShow] = React.useState(false);
  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}>
      {children}
      {show && (
        <span style={{
          position: 'absolute',
          [side === 'top' ? 'bottom' : 'top']: 'calc(100% + 6px)',
          left: '50%', transform: 'translateX(-50%)',
          background: '#000', border: '1px solid var(--bd-2, #2a3d57)',
          color: '#fff', fontSize: 11, padding: '6px 9px', borderRadius: 3,
          whiteSpace: 'normal', width: 220, lineHeight: 1.4,
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
          fontWeight: 400, letterSpacing: 'normal', textTransform: 'none',
          boxShadow: '0 8px 24px rgba(0,0,0,.5)',
          zIndex: 100, pointerEvents: 'none',
        }}>
          {tip}
        </span>
      )}
    </span>
  );
};

// ── why-? marker (uses Tooltip; tiny circular '?') ─────────────────
window.WhyMark = function({ tip }) {
  return (
    <CockpitTip tip={tip}>
      <span style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 12, height: 12, borderRadius: '50%',
        border: '1px solid currentColor', opacity: .55,
        fontSize: 9, fontWeight: 600, cursor: 'help',
        marginLeft: 5, lineHeight: 1,
      }}>?</span>
    </CockpitTip>
  );
};

// ── overlay ───────────────────────────────────────────────────────
window.CockpitOverlay = function({ open, onClose, title, sub, badge, children, width = 1180, accent, scope = 'vA' }) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    // Lock background scroll while a panel is open.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  // Portal to <body> so the overlay anchors to the real viewport, not the
  // scaled/letterboxed artboard (which is often taller than the screen and
  // vertically clipped — that would push panels off-screen). The scope class
  // re-supplies the variation's CSS vars + Tweaks overrides outside .vA/.vC.
  const node = (
    <div
      className={scope}
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)',
        backdropFilter: 'blur(2px)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        padding: '40px 24px', zIndex: 80, animation: 'cockpitFadeIn .15s ease',
      }}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width, maxWidth: 'calc(100% - 24px)', maxHeight: 'calc(100% - 80px)',
          background: 'var(--panel, #0d1219)', border: `1px solid ${accent || 'var(--pri-d, var(--amber-d, #b87a18))'}`,
          boxShadow: `0 30px 80px rgba(0,0,0,.6), 0 0 0 1px ${accent || 'var(--pri-d, var(--amber-d, #b87a18))'}, 0 0 40px rgba(0,0,0,.3)`,
          display: 'flex', flexDirection: 'column',
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
        }}>
        <div style={{
          padding: '14px 22px', display: 'flex', alignItems: 'center', gap: 16,
          borderBottom: '1px solid var(--bd, #1d2c40)',
          background: 'linear-gradient(180deg, rgba(255,255,255,.02) 0%, transparent 100%)',
        }}>
          {badge && (
            <span style={{
              fontSize: 10, letterSpacing: '.18em', padding: '4px 9px',
              border: `1px solid ${accent || 'var(--amber, #ffb845)'}`,
              color: accent || 'var(--amber, #ffb845)', fontWeight: 500,
            }}>{badge}</span>
          )}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 500, color: 'var(--tx, #e6ecf3)', letterSpacing: -.1 }}>{title}</div>
            {sub && <div style={{ fontSize: 12, color: 'var(--tx-2, #97a7bc)', marginTop: 2 }}>{sub}</div>}
          </div>
          <button onClick={onClose} style={{
            fontFamily: 'inherit', fontSize: 11, letterSpacing: '.14em', textTransform: 'uppercase',
            padding: '7px 12px', background: 'transparent',
            border: '1px solid var(--bd-2, #2a3d57)', color: 'var(--tx-2, #97a7bc)',
            cursor: 'pointer', borderRadius: 2,
          }}>Close · Esc</button>
        </div>
        <div style={{
          flex: 1, overflow: 'auto', padding: 22,
          background: 'var(--bg, #0a1018)',
        }}>
          {children}
        </div>
      </div>
    </div>
  );

  return ReactDOM.createPortal(node, document.body);
};

// ── one-time keyframes ────────────────────────────────────────────
if (typeof document !== 'undefined' && !document.getElementById('cockpit-shell-styles')) {
  const s = document.createElement('style');
  s.id = 'cockpit-shell-styles';
  s.textContent = `
    @keyframes cockpitFadeIn { from { opacity: 0; } to { opacity: 1; } }
    @keyframes cockpitPulse {
      0%, 100% { opacity: 1; }
      50% { opacity: .35; }
    }
    @keyframes cockpitFlyChip {
      0% { transform: translate(0,0) scale(1); opacity: 1; }
      80% { transform: var(--fly-end) scale(.9); opacity: 1; }
      100% { transform: var(--fly-end) scale(.7); opacity: 0; }
    }
    .cockpit-pulse { animation: cockpitPulse 1.6s ease-in-out infinite; }
    .cockpit-flychip {
      position: absolute; pointer-events: none; z-index: 60;
      animation: cockpitFlyChip 700ms cubic-bezier(.4,1,.6,1) forwards;
    }
  `;
  document.head.appendChild(s);
}
