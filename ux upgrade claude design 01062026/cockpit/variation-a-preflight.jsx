// Variation A — PRE-FLIGHT CHECKLIST
// A literal cockpit: instrument cluster on top, three-phase checklist below.
// Phase 1 Candidates → Phase 2 Portfolio → Phase 3 Clearance → Submitted.

const { useState, useMemo } = React;
const D = window.COCKPIT_DATA;

// shared shell + panel components (loaded by shell.jsx / panels.jsx)
const WhyMark = window.WhyMark;
const CockpitTip = window.CockpitTip;
const CockpitOverlay = window.CockpitOverlay;
const PanelUniverse = window.PanelUniverse;
const PanelSignals = window.PanelSignals;
const PanelTickerDetail = window.PanelTickerDetail;
const PanelAudit = window.PanelAudit;
const PanelPolicy = window.PanelPolicy;
const PanelMonitor = window.PanelMonitor;

// ───────────────────────── primitives ─────────────────────────

function StatusLight({ state, size = 8 }) {
  const colorMap = {
    live: 'var(--green)',
    stale: 'var(--amber)',
    block: 'var(--red)',
    off: 'var(--tx-3)',
  };
  const c = colorMap[state] || colorMap.off;
  return (
    <span
      style={{
        display: 'inline-block', width: size, height: size, borderRadius: '50%',
        background: c, boxShadow: `0 0 ${size}px ${c}, 0 0 2px ${c}`,
        flexShrink: 0,
      }}
    />
  );
}

// Half-circle gauge — 0..1 input, needle rotates -90° → +90°, zones colored.
function ArcGauge({ value, zones, label, big, unit, sub, tip }) {
  const v = Math.max(0, Math.min(1, value));
  const animV = window.useAnimatedValue(v, 800, [value]);
  const angle = -90 + animV * 180;
  const R = 70;
  // build arc segments
  const arc = (from, to, color) => {
    const a0 = (-90 + from * 180) * Math.PI / 180;
    const a1 = (-90 + to * 180) * Math.PI / 180;
    const x0 = 80 + R * Math.cos(a0), y0 = 80 + R * Math.sin(a0);
    const x1 = 80 + R * Math.cos(a1), y1 = 80 + R * Math.sin(a1);
    return (
      <path key={from}
        d={`M ${x0} ${y0} A ${R} ${R} 0 0 1 ${x1} ${y1}`}
        stroke={color} strokeWidth="10" fill="none" strokeLinecap="butt" />
    );
  };
  return (
    <div style={{ textAlign: 'center' }}>
      <svg viewBox="0 0 160 100" width="160" height="100">
        {/* track */}
        <path d="M 10 80 A 70 70 0 0 1 150 80" stroke="rgba(255,255,255,.06)" strokeWidth="10" fill="none" />
        {zones.map((z, i) => arc(z.from, z.to, z.color))}
        {/* tick marks */}
        {[0, 0.25, 0.5, 0.75, 1].map((t, i) => {
          const a = (-90 + t * 180) * Math.PI / 180;
          const r0 = 56, r1 = 60;
          return (
            <line key={i}
              x1={80 + r0 * Math.cos(a)} y1={80 + r0 * Math.sin(a)}
              x2={80 + r1 * Math.cos(a)} y2={80 + r1 * Math.sin(a)}
              stroke="rgba(255,255,255,.4)" strokeWidth="1.2" />
          );
        })}
        {/* needle */}
        <g transform={`rotate(${angle} 80 80)`} style={{ transition: 'transform .5s cubic-bezier(.4,2,.6,1)' }}>
          <line x1="80" y1="80" x2="80" y2="18" stroke="var(--amber)" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="80" cy="18" r="2.5" fill="var(--amber)" />
        </g>
        <circle cx="80" cy="80" r="5" fill="var(--bg)" stroke="var(--amber)" strokeWidth="1.5" />
      </svg>
      <div className="mono" style={{ fontSize: 24, fontWeight: 500, letterSpacing: -.5, color: 'var(--tx)', marginTop: -8 }}>
        {big}<span style={{ fontSize: 12, color: 'var(--tx-3)', marginLeft: 2 }}>{unit}</span>
      </div>
      <div style={{ fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)', marginTop: 2, display: 'inline-flex', alignItems: 'center' }}>
        {label}{tip && <WhyMark tip={tip} />}
      </div>
      {sub && <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3)', marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

// Conviction needle — compact half-dial used per ticker row.
function ConvictionDial({ value, size = 64 }) {
  const v = Math.max(0, Math.min(1, value));
  const animV = window.useAnimatedValue(v, 700, [value]);
  const angle = -90 + animV * 180;
  const color = v >= 0.62 ? 'var(--green)' : v >= 0.40 ? 'var(--amber)' : 'var(--red)';
  return (
    <svg viewBox="0 0 80 50" width={size} height={size * 50 / 80} style={{ display: 'block' }}>
      <path d="M 6 42 A 34 34 0 0 1 74 42" stroke="rgba(255,255,255,.08)" strokeWidth="5" fill="none" />
      {/* colored fill up to value */}
      <path d="M 6 42 A 34 34 0 0 1 74 42" stroke={color} strokeWidth="5" fill="none"
        strokeDasharray={`${animV * 106.8} 200`} />
      <g transform={`rotate(${angle} 40 42)`}>
        <line x1="40" y1="42" x2="40" y2="12" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
      </g>
      <circle cx="40" cy="42" r="3" fill="var(--bg)" stroke={color} strokeWidth="1.3" />
    </svg>
  );
}

// 7-seg style numeral (fakes the look with a panel + tabular mono numerals)
function SegDisplay({ value, unit, label, color = 'var(--amber)' }) {
  return (
    <div style={{
      background: '#03070d', border: '1px solid var(--bd)',
      padding: '8px 12px 6px', borderRadius: 4, textAlign: 'left',
      minWidth: 96,
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,.04)',
    }}>
      <div style={{ fontSize: 9, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--tx-3)' }}>{label}</div>
      <div className="mono" style={{
        fontSize: 22, fontWeight: 500, color, letterSpacing: -.3,
        textShadow: `0 0 6px ${color === 'var(--amber)' ? 'rgba(255,184,69,.4)' : 'rgba(90,215,240,.4)'}`,
      }}>{value}<span style={{ fontSize: 11, color: 'var(--tx-3)', marginLeft: 3 }}>{unit}</span></div>
    </div>
  );
}

// ───────────────────────── instrument cluster ─────────────────────────

function InstrumentCluster({ approvedCount }) {
  const acct = D.account;
  return (
    <div data-tour="cluster" style={{
      display: 'grid', gridTemplateColumns: '1fr auto', gap: 24,
      padding: '18px 24px 22px',
      background: 'linear-gradient(180deg, #0e1828 0%, #0a1018 100%)',
      borderBottom: '1px solid var(--bd)',
    }}>
      {/* primary 4 gauges */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, alignItems: 'end' }}>
        <ArcGauge
          value={(D.market.spy20d + 5) / 10}
          zones={[
            { from: 0, to: 0.40, color: 'var(--red)' },
            { from: 0.40, to: 0.62, color: 'var(--amber)' },
            { from: 0.62, to: 1, color: 'var(--green)' },
          ]}
          label="Market Regime" big="BAL" unit="" sub="SPY +2.4% · breadth 62%"
          tip="Top-down regime score blends SPY 20d return, VIX, breadth above 50dma, and sector dispersion. Balanced means no strong top-down edge — stock-specific evidence must carry the decision."
        />
        <ArcGauge
          value={acct.grossPostTrade / acct.grossCap}
          zones={[
            { from: 0, to: 0.70, color: 'var(--green)' },
            { from: 0.70, to: 0.90, color: 'var(--amber)' },
            { from: 0.90, to: 1, color: 'var(--red)' },
          ]}
          label="Gross Exposure" big={`${acct.grossPostTrade}`} unit="%"
          sub={`current ${acct.grossExposure}% → post-trade ${acct.grossPostTrade}%`}
          tip={`How much of the account is invested. Currently ${acct.grossExposure}%; will be ${acct.grossPostTrade}% if all approved orders fill. Hard cap ${acct.grossCap}%.`}
        />
        <ArcGauge
          value={acct.cashAvailable / 30}
          zones={[
            { from: 0, to: 0.333, color: 'var(--red)' },
            { from: 0.333, to: 0.5, color: 'var(--amber)' },
            { from: 0.5, to: 1, color: 'var(--green)' },
          ]}
          label="Cash Reserve" big={`${acct.cashAvailable}`} unit="%"
          sub={`floor ${acct.cashCap}%`}
          tip={`Cash kept uninvested. Floor of ${acct.cashCap}% — the policy will block any order that drops cash below this.`}
        />
        <ArcGauge
          value={acct.largestName / acct.largestNameCap}
          zones={[
            { from: 0, to: 0.6, color: 'var(--green)' },
            { from: 0.6, to: 0.85, color: 'var(--amber)' },
            { from: 0.85, to: 1, color: 'var(--red)' },
          ]}
          label="Concentration" big={`${acct.largestName}`} unit="%"
          sub={`cap ${acct.largestNameCap}%`}
          tip={`Largest single-name exposure. Cap ${acct.largestNameCap}% — any candidate that would push a name past this is auto-blocked.`}
        />
      </div>

      {/* digital readouts */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'stretch' }}>
        <SegDisplay value={`$${(acct.buyingPower / 1000).toFixed(0)}K`} unit="" label="Buying Power" color="var(--cyan)" />
        <SegDisplay value={approvedCount} unit={` / ${D.candidates.length}`} label="Ready to Trade" />
        <SegDisplay value={`+${acct.weekPnl}`} unit="% WTD" label="P/L Week" color="var(--green)" />
      </div>
    </div>
  );
}

function EngineStrip() {
  return (
    <div data-tour="engines" style={{
      display: 'flex', gap: 0, padding: '10px 24px', borderBottom: '1px solid var(--bd)',
      background: '#091221', alignItems: 'center', overflow: 'hidden',
    }}>
      <span style={{ fontSize: 10, letterSpacing: '.16em', textTransform: 'uppercase', color: 'var(--tx-3)', marginRight: 16 }}>Engines</span>
      <div style={{ display: 'flex', gap: 14, flex: 1, flexWrap: 'wrap' }}>
        {D.engines.map(e => (
          <div key={e.name} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
            <StatusLight state={e.state === 'live' ? 'live' : 'stale'} size={7} />
            <span style={{ color: e.state === 'live' ? 'var(--tx-2)' : 'var(--amber)' }}>{e.name}</span>
            <span className="mono" style={{ color: 'var(--tx-3)' }}>· {e.age}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ───────────────────────── phase header (pre-flight checklist) ─────────────────────────

function PhaseRail({ phase, decisionsCount, approvedCount }) {
  const phases = [
    { key: 'candidates', n: '01', t: 'Candidates', sub: `${approvedCount} approved · ${decisionsCount - approvedCount} reviewed` },
    { key: 'portfolio',  n: '02', t: 'Portfolio',  sub: '5 positions · 1 close candidate' },
    { key: 'clearance',  n: '03', t: 'Clearance',  sub: 'submit gate · paper mode' },
    { key: 'submitted',  n: '04', t: 'Cleared',    sub: 'orders in flight' },
  ];
  const idx = phases.findIndex(p => p.key === phase);
  return (
    <div data-tour="phaserail" style={{
      display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 1,
      borderBottom: '1px solid var(--bd)', background: 'var(--bd)',
    }}>
      {phases.map((p, i) => {
        const active = i === idx;
        const done = i < idx;
        const locked = i > idx;
        return (
          <div key={p.key} style={{
            padding: '14px 18px', background: active ? '#0f1c2f' : done ? '#0a1320' : 'var(--bg)',
            position: 'relative', opacity: locked ? 0.42 : 1,
            transition: 'opacity .2s',
          }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              <span className="mono" style={{
                fontSize: 11,
                color: done ? 'var(--green)' : active ? 'var(--amber)' : 'var(--tx-3)',
                letterSpacing: '.1em',
              }}>
                {done ? '✓' : locked ? '◌' : p.n}
              </span>
              <span style={{
                fontSize: 14, fontWeight: 500,
                color: active ? 'var(--tx)' : done ? 'var(--tx-2)' : 'var(--tx-3)',
                letterSpacing: '.02em',
              }}>{p.t}</span>
              {locked && (
                <span className="mono" style={{
                  marginLeft: 'auto', fontSize: 9, color: 'var(--tx-3)',
                  letterSpacing: '.18em',
                  border: '1px solid var(--bd-2)', padding: '2px 6px', borderRadius: 2,
                }}>LOCKED</span>
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--tx-3)', marginTop: 4, marginLeft: 22 }}>
              {locked ? `unlocks after ${phases[i - 1].t.toLowerCase()}` : p.sub}
            </div>
            {active && (
              <div style={{
                position: 'absolute', left: 0, right: 0, bottom: -1, height: 2, background: 'var(--amber)',
                boxShadow: '0 0 8px var(--amber)',
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ───────────────────────── scenario states ─────────────────────────

function OutageStateA() {
  const blockedEngines = [
    { name: 'Market data', detail: 'WebSocket disconnected · last tick 18m ago' },
    { name: 'Fundamentals API', detail: '503 from upstream · 4 retries · circuit open' },
  ];
  return (
    <div style={{ padding: '60px 60px 80px', textAlign: 'left', maxWidth: 1080, margin: '0 auto' }}>
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 10,
        padding: '6px 12px', border: '1px solid var(--red)',
        background: 'rgba(255,104,104,.08)',
        fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--red)',
        marginBottom: 22,
      }}>
        ◉ SELECTION BLOCKED · CYCLE C-14:32
      </div>
      <h1 style={{ fontSize: 44, fontWeight: 500, letterSpacing: -.6, lineHeight: 1.1, margin: '0 0 14px' }}>
        Two critical engines are down.<br />
        <span style={{ color: 'var(--tx-2)' }}>No candidates can be cleared this cycle.</span>
      </h1>
      <p style={{ fontSize: 15, color: 'var(--tx-2)', maxWidth: 720, margin: '0 0 36px', lineHeight: 1.55 }}>
        The agent will retry automatically. You can leave the cockpit and come back — there's nothing to action right now.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, background: 'var(--bd)', marginBottom: 36 }}>
        {blockedEngines.map(e => (
          <div key={e.name} style={{ background: 'var(--panel)', padding: 22 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--red)', boxShadow: '0 0 10px var(--red)' }} />
              <span style={{ fontSize: 11, letterSpacing: '.16em', textTransform: 'uppercase', color: 'var(--red)' }}>OFFLINE</span>
            </div>
            <div style={{ fontSize: 20, fontWeight: 500, marginTop: 8, letterSpacing: -.2 }}>{e.name}</div>
            <div className="mono" style={{ fontSize: 12, color: 'var(--tx-3)', marginTop: 6 }}>{e.detail}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <div style={{
          padding: '11px 18px', border: '1px solid var(--amber)', color: 'var(--amber)',
          fontSize: 12, letterSpacing: '.14em', textTransform: 'uppercase',
        }}>auto-retry in 4:12</div>
        <span style={{ fontSize: 12, color: 'var(--tx-3)' }}>
          Last successful cycle: <span className="mono" style={{ color: 'var(--tx-2)' }}>C-13:58 · 34m ago</span>
        </span>
      </div>
    </div>
  );
}

function NoActionableStateA({ onAdvance }) {
  return (
    <div style={{ padding: '40px 24px 60px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--amber)' }}>
            ▸ Phase 01 · Pre-flight check
          </div>
          <h2 style={{ margin: '4px 0 0', fontSize: 28, fontWeight: 500, letterSpacing: -.4, lineHeight: 1.1 }}>
            Nothing actionable today. Skip ahead — the agent already filtered.
          </h2>
          <div style={{ fontSize: 13, color: 'var(--tx-2)', marginTop: 6 }}>
            Scanned 152 tickers. 10 reached final review. None met the conviction bar — the day is balanced and the LLM flagged thin evidence on all three potential trades.
          </div>
        </div>
        <button onClick={onAdvance} style={{
          fontFamily: 'inherit', fontSize: 13, fontWeight: 500, letterSpacing: '.04em',
          padding: '11px 18px', border: '1px solid var(--amber)',
          background: 'var(--amber)', color: '#1a0f00',
          cursor: 'pointer', textTransform: 'uppercase', borderRadius: 3,
          boxShadow: '0 0 18px rgba(255,184,69,.35)',
        }}>Skip to Portfolio →</button>
      </div>

      <div style={{
        border: '1px solid var(--bd)', borderRadius: 4, background: 'var(--panel)',
        padding: '32px 28px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 1,
      }}>
        {[
          { ticker: 'AAPL', col: 'var(--amber)', tag: 'LLM DEMOTED', reason: 'reviewer cited thin earnings revision evidence; conviction landed at 0.51 vs 0.62 bar' },
          { ticker: 'GOOG', col: 'var(--amber)', tag: 'LLM DEMOTED', reason: 'AI-spend narrative not yet confirmed by Q-on-Q numbers; revisit after May print' },
          { ticker: 'TSLA', col: 'var(--red)',   tag: 'POLICY BLOCK',  reason: 'concentration cap — TSLA exposure already at 18% of 25% cap; adding here would breach' },
        ].map((r, i) => (
          <div key={r.ticker} style={{ padding: '0 22px', borderRight: i < 2 ? '1px solid var(--bd)' : 'none' }}>
            <div className="mono" style={{ fontSize: 22, fontWeight: 500, color: 'var(--tx-2)', letterSpacing: -.4 }}>{r.ticker}</div>
            <div style={{ fontSize: 10, letterSpacing: '.14em', color: r.col, marginTop: 4, fontWeight: 600 }}>{r.tag}</div>
            <div style={{ fontSize: 12, color: 'var(--tx-3)', marginTop: 10, lineHeight: 1.5 }}>{r.reason}</div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 24, padding: '14px 18px', border: '1px dashed var(--bd-2)',
        fontSize: 12, color: 'var(--tx-3)', lineHeight: 1.55 }}>
        <span style={{ color: 'var(--cyan)', fontWeight: 600, letterSpacing: '.1em', textTransform: 'uppercase', marginRight: 8 }}>Agent note ›</span>
        This is the expected shape of a low-conviction day. The cluster reads BALANCED, breadth is mid-range, and the funnel didn't surface anything beyond the bar. Portfolio review and risk monitoring still proceed normally.
      </div>
    </div>
  );
}

// ───────────────────────── phase 1: candidates ─────────────────────────

function CandidatesPhase({ decisions, setDecisions, onAdvance, onOpenTicker, onOpenAudit }) {
  const [expanded, setExpanded] = useState(null);

  const list = useMemo(() => {
    // Sort by final conviction descending
    return [...D.candidates].sort((a, b) => b.finalConviction - a.finalConviction);
  }, []);

  const decided = Object.keys(decisions).length;
  const approved = Object.values(decisions).filter(d => d === 'approve').length;
  const actionable = list.filter(c => c.status === 'approved').length;
  const allApproved = approved >= actionable;
  const noneApproved = approved === 0;

  // BLUF headline adapts to state
  const headline = noneApproved
    ? `${actionable} trades ready. Approve what you want to ship today.`
    : allApproved
      ? `All ${actionable} ready candidates approved. Advance to portfolio check.`
      : `${approved} of ${actionable} approved. Keep going or advance.`;
  const subline = noneApproved
    ? `Cycle ${D.cycle.id} scanned ${D.funnel.universe} tickers. 10 cleared deterministic + LLM review — only the top 3 are actionable.`
    : `${decided} decisions logged this cycle · the agent has the audit trail.`;

  const decide = (t, v) => setDecisions(prev => ({ ...prev, [t]: v }));

  const statusChip = (c) => {
    if (decisions[c.ticker] === 'approve') return { t: 'YOU APPROVED', col: 'var(--green)' };
    if (decisions[c.ticker] === 'defer') return { t: 'DEFERRED', col: 'var(--tx-3)' };
    if (decisions[c.ticker] === 'reject') return { t: 'YOU REJECTED', col: 'var(--red)' };
    if (c.status === 'approved') return { t: 'READY', col: 'var(--amber)' };
    if (c.status === 'demoted') return { t: 'LLM DEMOTED', col: 'var(--amber)' };
    if (c.status === 'blocked') return { t: 'BLOCKED', col: 'var(--red)' };
    return { t: 'BELOW THRESHOLD', col: 'var(--tx-3)' };
  };

  return (
    <div style={{ padding: '20px 24px 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--amber)' }}>
            ▸ Phase 01 · Pre-flight check
          </div>
          <h2 style={{ margin: '4px 0 0', fontSize: 28, fontWeight: 500, letterSpacing: -.4, lineHeight: 1.1 }}>
            {headline}
          </h2>
          <div style={{ fontSize: 13, color: 'var(--tx-2)', marginTop: 6 }}>
            {subline}
          </div>
        </div>
        <button
          data-tour="advance"
          onClick={onAdvance}
          disabled={approved === 0}
          style={{
            fontFamily: 'inherit', fontSize: 13, fontWeight: 500, letterSpacing: '.04em',
            padding: '11px 18px', border: '1px solid',
            borderColor: approved > 0 ? 'var(--amber)' : 'var(--bd)',
            background: approved > 0 ? 'var(--amber)' : 'transparent',
            color: approved > 0 ? '#1a0f00' : 'var(--tx-3)',
            cursor: approved > 0 ? 'pointer' : 'not-allowed',
            textTransform: 'uppercase', borderRadius: 3,
            boxShadow: approved > 0 ? '0 0 18px rgba(255,184,69,.35)' : 'none',
          }}>
          Advance to Portfolio →
        </button>
      </div>

      <div data-tour="candidates" style={{
        border: '1px solid var(--bd)', borderRadius: 4, overflow: 'hidden',
        background: 'var(--panel)',
      }}>
        {/* header row */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '36px 1fr 110px 1fr 1fr 130px 200px',
          gap: 0, padding: '8px 14px',
          background: '#0a1320', borderBottom: '1px solid var(--bd)',
          fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)',
        }}>
          <div>#</div>
          <div>Ticker · sector</div>
          <div style={{ textAlign: 'center' }}>Conviction</div>
          <div>Why</div>
          <div>Risk</div>
          <div>Status</div>
          <div style={{ textAlign: 'right' }}>Decision</div>
        </div>

        {list.map((c, i) => {
          const chip = statusChip(c);
          const isOpen = expanded === c.ticker;
          const actionable = c.status === 'approved';
          const tourFirst = i === 0;
          return (
            <React.Fragment key={c.ticker}>
              <div
                data-tour={tourFirst ? 'firstticker' : undefined}
                onClick={() => setExpanded(isOpen ? null : c.ticker)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '36px 1fr 110px 1fr 1fr 130px 200px',
                  gap: 0, padding: '14px 14px',
                  borderBottom: '1px solid var(--bd)',
                  background: isOpen ? '#0f1c2f' : actionable ? '#0d172580' : 'transparent',
                  cursor: 'pointer',
                  alignItems: 'center',
                  transition: 'background .15s',
                }}>
                <div className="mono" style={{ color: 'var(--tx-3)', fontSize: 11 }}>
                  {String(i + 1).padStart(2, '0')}
                </div>
                <div>
                  <div className="mono" style={{ fontSize: 16, fontWeight: 500, color: 'var(--tx)', cursor: 'pointer' }}
                    onClick={(e) => { e.stopPropagation(); onOpenTicker(c.ticker); }}
                    title={`Open ${c.ticker} deep-dive`}>
                    {c.ticker}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--tx-3)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    {c.sector}
                    {(c.status === 'demoted' || c.status === 'blocked' || c.status === 'rejected') && (
                      <a onClick={(e) => { e.stopPropagation(); onOpenAudit(c.ticker); }}
                        style={{ color: 'var(--cyan)', cursor: 'pointer', textDecoration: 'underline', fontSize: 10 }}>
                        audit ›
                      </a>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                  <ConvictionDial value={c.finalConviction} size={56} />
                  <div className="mono" style={{
                    fontSize: 20, fontWeight: 500, lineHeight: 1, letterSpacing: -.5,
                    color: c.finalConviction >= 0.62 ? 'var(--green)' : c.finalConviction >= 0.40 ? 'var(--amber)' : 'var(--red)',
                  }}>
                    {c.finalConviction.toFixed(2)}
                  </div>
                </div>
                <div style={{ fontSize: 12, color: 'var(--tx-2)', lineHeight: 1.45 }}>
                  {c.evidence[0]?.text || <span style={{ color: 'var(--tx-3)' }}>—</span>}
                </div>
                <div style={{ fontSize: 12, color: c.concerns.length ? 'var(--amber)' : 'var(--tx-3)', lineHeight: 1.45 }}>
                  {c.concerns[0] || <span style={{ color: 'var(--tx-3)' }}>none flagged</span>}
                </div>
                <div>
                  <span style={{
                    fontSize: 10, letterSpacing: '.1em',
                    padding: '3px 7px', borderRadius: 2,
                    color: chip.col, border: `1px solid ${chip.col}`,
                    background: 'rgba(0,0,0,.3)',
                  }}>{chip.t}</span>
                </div>
                <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }} onClick={e => e.stopPropagation()}>
                  {actionable ? (
                    <>
                      <DecisionBtn label="Approve" tone="approve" active={decisions[c.ticker] === 'approve'}
                        onClick={() => decide(c.ticker, 'approve')}
                        dataTour={tourFirst ? 'approvebtn' : undefined} />
                      <DecisionBtn label="Defer" tone="defer" active={decisions[c.ticker] === 'defer'}
                        onClick={() => decide(c.ticker, 'defer')} />
                      <DecisionBtn label="Reject" tone="reject" active={decisions[c.ticker] === 'reject'}
                        onClick={() => decide(c.ticker, 'reject')} />
                    </>
                  ) : (
                    <span style={{ fontSize: 11, color: 'var(--tx-3)', alignSelf: 'center', textAlign: 'right' }}>
                      not actionable
                    </span>
                  )}
                </div>
              </div>
              {isOpen && (
                <ExpandedCandidate c={c} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      <div style={{ marginTop: 12, fontSize: 11, color: 'var(--tx-3)', display: 'flex', gap: 18 }}>
        <span><b style={{ color: 'var(--tx-2)' }}>{decided}</b> of {list.length} decisions made</span>
        <span>· evidence pack: SEC EDGAR · Alpaca · paid email tier · sector ETFs</span>
        <span>· LLM gpt-5.4-mini · prompt v2.1</span>
      </div>
    </div>
  );
}

function DecisionBtn({ label, tone, active, onClick, dataTour }) {
  const palette = {
    approve: { bd: 'var(--green)', bg: 'rgba(95,228,157,.18)', tx: 'var(--green)' },
    defer:   { bd: 'var(--tx-3)', bg: 'rgba(151,167,188,.12)', tx: 'var(--tx-2)' },
    reject:  { bd: 'var(--red)', bg: 'rgba(255,104,104,.18)', tx: 'var(--red)' },
  }[tone];
  return (
    <button
      data-tour={dataTour}
      onClick={onClick}
      style={{
        fontFamily: 'inherit', fontSize: 11, letterSpacing: '.06em', textTransform: 'uppercase',
        padding: '6px 10px', borderRadius: 3, cursor: 'pointer',
        border: `1px solid ${active ? palette.bd : 'var(--bd-2)'}`,
        background: active ? palette.bg : 'transparent',
        color: active ? palette.tx : 'var(--tx-2)',
        transition: 'all .12s',
        fontWeight: 500,
      }}>
      {label}
    </button>
  );
}

function ExpandedCandidate({ c }) {
  return (
    <div style={{
      padding: '18px 22px 20px', borderBottom: '1px solid var(--bd)',
      background: '#0a1626', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 24,
    }}>
      <div>
        <div style={{ fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)', marginBottom: 8 }}>
          Evidence · why it's here
        </div>
        {c.evidence.map((e, i) => (
          <div key={i} style={{ marginBottom: 10, paddingLeft: 12, borderLeft: `2px solid ${e.tier === 'confirmed' ? 'var(--green)' : 'var(--amber)'}` }}>
            <div style={{ fontSize: 11, color: e.tier === 'confirmed' ? 'var(--green)' : 'var(--amber)', textTransform: 'uppercase', letterSpacing: '.08em' }}>
              {e.tier} · {e.source}
            </div>
            <div style={{ fontSize: 12, color: 'var(--tx-2)', marginTop: 2 }}>{e.text}</div>
          </div>
        ))}
      </div>

      <div>
        <div style={{ fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)', marginBottom: 8 }}>
          LLM rationale · gpt-5.4-mini
        </div>
        <div style={{
          fontSize: 12, color: 'var(--tx-2)', lineHeight: 1.6,
          padding: 12, background: 'rgba(90,215,240,.05)', border: '1px solid rgba(90,215,240,.15)',
          borderRadius: 4,
        }}>
          {c.llmRationale}
        </div>
        {c.concerns.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--amber)', marginBottom: 6 }}>
              Watch list
            </div>
            {c.concerns.map((co, i) => (
              <div key={i} style={{ fontSize: 12, color: 'var(--tx-2)', marginBottom: 4, paddingLeft: 12, position: 'relative' }}>
                <span style={{ position: 'absolute', left: 0, color: 'var(--amber)' }}>!</span>{co}
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <div style={{ fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)', marginBottom: 8 }}>
          If approved · paper order preview
        </div>
        {c.status === 'approved' ? (
          <div style={{ background: 'rgba(0,0,0,.3)', border: '1px solid var(--bd)', borderRadius: 4, padding: 14 }}>
            <PreviewRow label="Side" val={<span style={{ color: 'var(--green)', fontWeight: 600 }}>BUY · {c.direction.toUpperCase()}</span>} />
            <PreviewRow label="Quantity" val={`${c.qty} sh`} />
            <PreviewRow label="Limit" val={`$${c.price.toFixed(2)}`} />
            <PreviewRow label="Notional" val={`$${c.notional.toLocaleString()}`} />
            <PreviewRow label="Stop" val={<span style={{ color: 'var(--red)' }}>{c.stopPct}%</span>} />
            <PreviewRow label="Target" val={<span style={{ color: 'var(--green)' }}>+{c.targetPct}%</span>} />
            <PreviewRow label="Earnings" val={`${c.earningsDays} days out`} last />
          </div>
        ) : (
          <div style={{
            padding: 14, fontSize: 12, color: 'var(--tx-2)',
            border: '1px solid var(--bd)', borderRadius: 4,
            background: 'rgba(0,0,0,.2)',
          }}>
            {c.blocker ? <><span style={{ color: 'var(--red)' }}>●</span> {c.blocker}</> : 'Not actionable this cycle.'}
          </div>
        )}
      </div>
    </div>
  );
}

function PreviewRow({ label, val, last }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', fontSize: 12,
      padding: '5px 0', borderBottom: last ? 'none' : '1px dashed var(--bd)',
    }}>
      <span style={{ color: 'var(--tx-3)' }}>{label}</span>
      <span className="mono" style={{ color: 'var(--tx)' }}>{val}</span>
    </div>
  );
}

// ───────────────────────── phase 2: portfolio ─────────────────────────

function PortfolioPhase({ exits, setExits, onAdvance, onBack }) {
  const closeCandidates = D.positions.filter(p => p.status !== 'hold');
  const allDecided = closeCandidates.every(p => exits[p.ticker]);
  return (
    <div style={{ padding: '20px 24px 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--amber)' }}>
            ▸ Phase 02 · Portfolio check
          </div>
          <h2 style={{ margin: '4px 0 0', fontSize: 22, fontWeight: 500, letterSpacing: -.2 }}>
            1 close candidate · 2 to review · 2 holding aligned.
          </h2>
          <div style={{ fontSize: 13, color: 'var(--tx-2)', marginTop: 4 }}>
            Acknowledge exits before clearance. The agent monitors — you decide.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onBack} style={btnSecondary}>← Back</button>
          <button onClick={onAdvance} disabled={!allDecided} style={{
            ...btnPrimary,
            background: allDecided ? 'var(--amber)' : 'transparent',
            color: allDecided ? '#1a0f00' : 'var(--tx-3)',
            cursor: allDecided ? 'pointer' : 'not-allowed',
            borderColor: allDecided ? 'var(--amber)' : 'var(--bd)',
            boxShadow: allDecided ? '0 0 18px rgba(255,184,69,.35)' : 'none',
          }}>Advance to Clearance →</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <div style={{
          background: 'var(--panel)', border: '1px solid var(--bd)', borderRadius: 4,
        }}>
          <div style={{
            padding: '8px 14px', borderBottom: '1px solid var(--bd)',
            fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)',
            background: '#0a1320',
          }}>5 open positions · status by current setup</div>

          {D.positions.map(p => {
            const pl = ((p.current - p.entry) / p.entry) * 100;
            const stopDist = ((p.current - p.stop) / p.current) * 100;
            const palette = {
              hold:   { c: 'var(--green)', t: 'HOLD' },
              review: { c: 'var(--amber)', t: 'REVIEW' },
              close:  { c: 'var(--red)',   t: 'CLOSE CANDIDATE' },
            }[p.status];
            return (
              <div key={p.ticker} style={{
                padding: '14px 14px',
                borderBottom: '1px solid var(--bd)',
                display: 'grid',
                gridTemplateColumns: '90px 110px 110px 110px 1fr 130px',
                gap: 12, alignItems: 'center',
              }}>
                <div>
                  <div className="mono" style={{ fontSize: 15, fontWeight: 500 }}>{p.ticker}</div>
                  <div style={{ fontSize: 10, color: 'var(--tx-3)' }}>{p.daysHeld}d held</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '.06em' }}>P/L</div>
                  <div className="mono" style={{ fontSize: 14, color: pl >= 0 ? 'var(--green)' : 'var(--red)' }}>
                    {pl >= 0 ? '+' : ''}{pl.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '.06em' }}>Stop dist</div>
                  <div className="mono" style={{ fontSize: 14, color: stopDist < 5 ? 'var(--amber)' : 'var(--tx-2)' }}>
                    -{stopDist.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '.06em' }}>Setup</div>
                  <span style={{
                    fontSize: 10, color: palette.c, padding: '2px 7px', border: `1px solid ${palette.c}`,
                    borderRadius: 2, letterSpacing: '.08em',
                  }}>{palette.t}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--tx-2)', lineHeight: 1.4 }}>
                  {p.thesis}
                </div>
                <div style={{ textAlign: 'right' }}>
                  {p.status === 'hold' ? (
                    <span style={{ fontSize: 11, color: 'var(--tx-3)' }}>auto-aligned</span>
                  ) : exits[p.ticker] ? (
                    <span style={{
                      fontSize: 10, letterSpacing: '.08em', textTransform: 'uppercase',
                      color: exits[p.ticker] === 'close' ? 'var(--red)' : 'var(--green)',
                      padding: '4px 8px', border: `1px solid ${exits[p.ticker] === 'close' ? 'var(--red)' : 'var(--green)'}`,
                      borderRadius: 2,
                    }}>{exits[p.ticker] === 'close' ? 'WILL CLOSE' : 'KEEP'}</span>
                  ) : (
                    <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                      <button style={tinyBtn('var(--red)')} onClick={() => setExits(prev => ({...prev, [p.ticker]: 'close'}))}>Close</button>
                      <button style={tinyBtn('var(--tx-3)')} onClick={() => setExits(prev => ({...prev, [p.ticker]: 'keep'}))}>Keep</button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div style={{
          background: 'var(--panel)', border: '1px solid var(--bd)', borderRadius: 4,
          padding: 16,
        }}>
          <div style={{ fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)', marginBottom: 12 }}>
            Capacity check
          </div>
          <CapBar label="Gross exposure" cur={67} post={84} cap={100} unit="%" />
          <CapBar label="Sector · Technology" cur={22} post={30} cap={30} unit="%" warn />
          <CapBar label="Sector · Cons. Disc." cur={4} post={11} cap={30} unit="%" />
          <CapBar label="Sector · Health Care" cur={5} post={9} cap={30} unit="%" />
          <CapBar label="Cash reserve" cur={33} post={18} cap={10} unit="%" floor />
          <div style={{
            marginTop: 14, padding: 12, fontSize: 12, lineHeight: 1.5,
            background: 'rgba(255,184,69,.06)', border: '1px solid rgba(255,184,69,.2)',
            color: 'var(--amber)', borderRadius: 4,
          }}>
            <b>Heads up.</b> Approving all 3 takes Tech to its 30% cap. No more Tech entries this week.
          </div>
        </div>
      </div>
    </div>
  );
}

function CapBar({ label, cur, post, cap, unit, warn, floor }) {
  const pct = Math.min(100, (post / cap) * 100);
  const curPct = Math.min(100, (cur / cap) * 100);
  return (
    <div style={{ marginBottom: 11 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
        <span style={{ color: 'var(--tx-2)' }}>{label}</span>
        <span className="mono" style={{ color: 'var(--tx)' }}>
          {cur}{unit} <span style={{ color: 'var(--tx-3)' }}>→</span> {post}{unit}
          <span style={{ color: 'var(--tx-3)', marginLeft: 4 }}>/ {cap}{unit}</span>
        </span>
      </div>
      <div style={{
        position: 'relative', height: 4, background: '#06101e', borderRadius: 1, marginTop: 5,
        overflow: 'hidden',
      }}>
        <div style={{ position: 'absolute', inset: 0, width: `${curPct}%`, background: 'var(--tx-3)' }} />
        <div style={{
          position: 'absolute', inset: 0, width: `${pct}%`,
          background: warn || pct >= 95 ? 'var(--amber)' : 'var(--green)',
          mixBlendMode: 'screen',
        }} />
      </div>
    </div>
  );
}

const btnPrimary = {
  fontFamily: 'inherit', fontSize: 13, fontWeight: 500, letterSpacing: '.04em',
  padding: '11px 18px', border: '1px solid var(--amber)',
  background: 'var(--amber)', color: '#1a0f00',
  cursor: 'pointer', textTransform: 'uppercase', borderRadius: 3,
};
const btnSecondary = {
  fontFamily: 'inherit', fontSize: 13, fontWeight: 500, letterSpacing: '.04em',
  padding: '11px 18px', border: '1px solid var(--bd-2)',
  background: 'transparent', color: 'var(--tx-2)',
  cursor: 'pointer', textTransform: 'uppercase', borderRadius: 3,
};
const tinyBtn = c => ({
  fontFamily: 'inherit', fontSize: 10, letterSpacing: '.08em', textTransform: 'uppercase',
  padding: '5px 9px', borderRadius: 2, border: `1px solid ${c}`,
  background: 'transparent', color: c, cursor: 'pointer',
});

// ───────────────────────── phase 3: clearance ─────────────────────────

function ClearancePhase({ decisions, exits, onSubmit, onBack }) {
  const approved = D.candidates.filter(c => decisions[c.ticker] === 'approve');
  const exitsToClose = Object.entries(exits).filter(([_, v]) => v === 'close').map(([k]) => k);
  const [gateOpen, setGateOpen] = useState(false);
  const [phrase, setPhrase] = useState('');
  const requiredPhrase = 'submit paper orders';
  const phraseOk = phrase.trim().toLowerCase() === requiredPhrase;
  const totalNotional = approved.reduce((s, c) => s + c.notional, 0);
  const canSubmit = gateOpen && phraseOk && approved.length > 0;

  return (
    <div style={{ padding: '20px 24px 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--amber)' }}>
            ▸ Phase 03 · Clearance for departure
          </div>
          <h2 style={{ margin: '4px 0 0', fontSize: 22, fontWeight: 500, letterSpacing: -.2 }}>
            {approved.length} paper {approved.length === 1 ? 'order' : 'orders'} staged · ${totalNotional.toLocaleString()} notional.
          </h2>
          <div style={{ fontSize: 13, color: 'var(--tx-2)', marginTop: 4 }}>
            Open the gate, type the confirmation phrase, then submit. Live trading is disabled.
          </div>
        </div>
        <button onClick={onBack} style={btnSecondary}>← Back</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
        {/* manifest */}
        <div style={{ background: 'var(--panel)', border: '1px solid var(--bd)', borderRadius: 4 }}>
          <div style={{
            padding: '8px 14px', borderBottom: '1px solid var(--bd)', background: '#0a1320',
            fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--tx-3)',
            display: 'flex', justifyContent: 'space-between',
          }}>
            <span>Order manifest</span><span>OCO bracket · DAY · paper</span>
          </div>

          {exitsToClose.length > 0 && (
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--bd)', background: 'rgba(255,104,104,.06)' }}>
              <div style={{ fontSize: 10, color: 'var(--red)', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 6 }}>
                Exits first
              </div>
              {exitsToClose.map(t => {
                const p = D.positions.find(x => x.ticker === t);
                return (
                  <div key={t} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 12 }}>
                    <span className="mono" style={{ color: 'var(--tx)' }}>SELL · {t}</span>
                    <span style={{ color: 'var(--tx-2)' }}>{p.thesis}</span>
                  </div>
                );
              })}
            </div>
          )}

          {approved.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--tx-3)', fontSize: 13 }}>
              No candidates approved. Go back to Phase 01 to stage orders.
            </div>
          ) : approved.map(c => (
            <div key={c.ticker} style={{
              padding: '14px 14px', borderBottom: '1px solid var(--bd)',
              display: 'grid', gridTemplateColumns: '90px 1fr 1fr 1fr 1fr',
              gap: 12, alignItems: 'center',
            }}>
              <div>
                <div className="mono" style={{ fontSize: 16, fontWeight: 500 }}>{c.ticker}</div>
                <div style={{ fontSize: 10, color: 'var(--green)' }}>BUY · LONG</div>
              </div>
              <div><MetaSm l="Qty" v={`${c.qty} sh`} /></div>
              <div><MetaSm l="Limit" v={`$${c.price.toFixed(2)}`} /></div>
              <div><MetaSm l="Notional" v={`$${c.notional.toLocaleString()}`} /></div>
              <div style={{ display: 'flex', gap: 14, justifyContent: 'flex-end' }}>
                <MetaSm l="Stop" v={`${c.stopPct}%`} c="var(--red)" />
                <MetaSm l="Target" v={`+${c.targetPct}%`} c="var(--green)" />
              </div>
            </div>
          ))}
        </div>

        {/* gate */}
        <div style={{
          background: 'linear-gradient(180deg, #110a04 0%, #0a1018 100%)',
          border: '1px solid var(--amber-d)', borderRadius: 4,
          padding: 18,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
            <div style={{
              width: 36, height: 36, borderRadius: '50%',
              background: gateOpen ? 'var(--green)' : 'var(--red)',
              boxShadow: `0 0 24px ${gateOpen ? 'var(--green)' : 'var(--red)'}`,
              border: '3px solid #0a1018',
              transition: 'all .3s',
            }} />
            <div>
              <div style={{ fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--tx-3)' }}>
                Submit gate
              </div>
              <div style={{ fontSize: 16, fontWeight: 500, color: gateOpen ? 'var(--green)' : 'var(--red)', letterSpacing: '.02em' }}>
                {gateOpen ? 'OPEN' : 'CLOSED'}
              </div>
            </div>
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
            background: 'rgba(0,0,0,.25)', border: '1px solid var(--bd)', borderRadius: 3, marginBottom: 12, cursor: 'pointer' }}>
            <input type="checkbox" checked={gateOpen} onChange={e => setGateOpen(e.target.checked)}
              style={{ accentColor: 'var(--amber)', width: 14, height: 14 }} />
            <span style={{ fontSize: 13, color: 'var(--tx)' }}>I want to open the submit gate</span>
          </label>

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--tx-3)', marginBottom: 6 }}>
              Type to confirm
            </div>
            <input
              value={phrase}
              onChange={e => setPhrase(e.target.value)}
              placeholder={requiredPhrase}
              disabled={!gateOpen}
              className="mono"
              style={{
                width: '100%', padding: '10px 12px',
                background: '#03070d', border: `1px solid ${phraseOk ? 'var(--green)' : 'var(--bd-2)'}`,
                color: 'var(--tx)', fontSize: 13, fontFamily: 'var(--mono)', borderRadius: 3,
                outline: 'none',
              }}
            />
          </div>

          <button
            disabled={!canSubmit}
            onClick={onSubmit}
            style={{
              width: '100%', padding: '14px',
              fontFamily: 'inherit', fontSize: 13, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase',
              border: '1px solid', borderColor: canSubmit ? 'var(--green)' : 'var(--bd)',
              background: canSubmit ? 'var(--green)' : 'transparent',
              color: canSubmit ? '#03150b' : 'var(--tx-3)',
              cursor: canSubmit ? 'pointer' : 'not-allowed',
              borderRadius: 3,
              boxShadow: canSubmit ? '0 0 24px rgba(95,228,157,.4)' : 'none',
              transition: 'all .2s',
            }}>
            {canSubmit ? `▸ Submit ${approved.length} Paper Orders` : 'Locked'}
          </button>

          <div style={{ marginTop: 14, fontSize: 11, color: 'var(--tx-3)', lineHeight: 1.6 }}>
            Broker: Alpaca paper · BROKER_SUBMIT_ENABLED <span className="mono" style={{ color: 'var(--amber)' }}>true</span> ·
            SHORTS_ENABLED <span className="mono" style={{ color: 'var(--red)' }}>false</span> ·
            Bracket orders <span className="mono" style={{ color: 'var(--green)' }}>OCO enabled</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function MetaSm({ l, v, c }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.08em', textTransform: 'uppercase' }}>{l}</div>
      <div className="mono" style={{ fontSize: 13, color: c || 'var(--tx)' }}>{v}</div>
    </div>
  );
}

// ───────────────────────── phase 4: cleared ─────────────────────────

function ClearedPhase({ decisions, onReset }) {
  const approved = D.candidates.filter(c => decisions[c.ticker] === 'approve');
  const totalNotional = approved.reduce((s, c) => s + c.notional, 0);
  return (
    <div style={{ padding: '32px 24px 28px', textAlign: 'center' }}>
      <div style={{ display: 'inline-block', position: 'relative', marginBottom: 18 }}>
        <div style={{
          width: 80, height: 80, borderRadius: '50%',
          border: '2px solid var(--green)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 36, color: 'var(--green)',
          boxShadow: '0 0 32px rgba(95,228,157,.4)',
        }}>✓</div>
      </div>
      <h2 style={{ margin: 0, fontSize: 24, fontWeight: 500 }}>
        {approved.length} paper {approved.length === 1 ? 'order' : 'orders'} submitted.
      </h2>
      <div style={{ fontSize: 13, color: 'var(--tx-2)', marginTop: 4 }}>
        Brackets attached. Portfolio will reflect fills as they land.
      </div>

      <div style={{
        marginTop: 24, display: 'inline-flex', gap: 1, background: 'var(--bd)',
        border: '1px solid var(--bd)', borderRadius: 4, overflow: 'hidden',
      }}>
        {approved.map(c => (
          <div key={c.ticker} style={{
            padding: '14px 22px', background: 'var(--panel)', textAlign: 'left', minWidth: 160,
          }}>
            <div className="mono" style={{ fontSize: 15, fontWeight: 500 }}>{c.ticker}</div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--green)' }}>BUY {c.qty} @ ${c.price.toFixed(2)}</div>
            <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3)', marginTop: 4 }}>
              order-id ALP-{Math.floor(Math.random() * 90000 + 10000)}
            </div>
          </div>
        ))}
      </div>

      <div style={{
        marginTop: 24, fontSize: 12, color: 'var(--tx-3)', maxWidth: 520, margin: '24px auto 0',
        lineHeight: 1.6,
      }}>
        Total notional: <span className="mono" style={{ color: 'var(--tx-2)' }}>${totalNotional.toLocaleString()}</span> ·
        Next cycle in <span className="mono" style={{ color: 'var(--tx-2)' }}>{D.cycle.nextIn}</span> ·
        Continuous monitor active.
      </div>

      <button onClick={onReset} style={{ ...btnSecondary, marginTop: 22 }}>Start over</button>
    </div>
  );
}

// ───────────────────────── topbar + shell ─────────────────────────

function TopBar({ phase, onOpenPanel }) {
  const { mm, ss } = window.useCockpitCountdown(13 * 60 + 14);
  return (
    <div data-tour="topbar" style={{
      display: 'flex', alignItems: 'center', gap: 18,
      padding: '10px 20px',
      background: '#06101e', borderBottom: '1px solid var(--bd)',
      fontSize: 12, color: 'var(--tx-2)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 22, height: 22, position: 'relative' }}>
          <svg viewBox="0 0 24 24" width="22" height="22">
            <circle cx="12" cy="12" r="9" fill="none" stroke="var(--amber)" strokeWidth="1.5" />
            <path d="M 12 3 L 12 21 M 3 12 L 21 12" stroke="var(--amber)" strokeWidth="1" opacity=".6" />
            <path d="M 12 8 L 16 12 L 12 16 L 8 12 Z" fill="var(--amber)" />
          </svg>
        </div>
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--tx)', letterSpacing: '.04em' }}>
          AGENCY · COCKPIT
        </span>
        <span style={{ fontSize: 11, color: 'var(--tx-3)' }}>v2.1</span>
      </div>
      <div style={{ flex: 1, display: 'flex', justifyContent: 'center', gap: 22, alignItems: 'center' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center' }}><StatusLight state="live" size={6} /> <span style={{ marginLeft: 6 }}>6 of 7 engines live</span></span>
        <span style={{ color: 'var(--tx-3)' }}>·</span>
        <span className="mono" style={{ color: 'var(--tx)' }}>cycle {D.cycle.id}</span>
        <span style={{ color: 'var(--tx-3)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          next in <span className="mono cockpit-pulse" style={{ color: 'var(--amber)', fontWeight: 500, fontSize: 13 }}>{mm}:{ss}</span>
        </span>
      </div>
      <span style={{
        fontSize: 10, letterSpacing: '.18em', padding: '4px 10px',
        background: 'rgba(255,184,69,.15)', color: 'var(--amber)',
        border: '1px solid var(--amber-d)', borderRadius: 2,
      }}>{D.cycle.mode}</span>
    </div>
  );
}

function InstrumentsNav({ onOpen }) {
  const items = [
    { key: 'universe', t: 'Universe',  s: '150/152' },
    { key: 'signals',  t: 'Signals',   s: '12 live' },
    { key: 'audit',    t: 'Audit',     s: 'NFLX trace' },
    { key: 'policy',   t: 'Policy',    s: '6 caps' },
    { key: 'monitor',  t: 'Monitor',   s: 'live stream' },
  ];
  return (
    <div data-tour="instruments" style={{
      display: 'flex', gap: 0, padding: '0 24px',
      background: '#080f1a', borderBottom: '1px solid var(--bd)',
      alignItems: 'stretch',
    }}>
      <span style={{ fontSize: 10, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--tx-3)', alignSelf: 'center', marginRight: 18 }}>
        Instruments ›
      </span>
      {items.map(it => (
        <button key={it.key} onClick={() => onOpen(it.key)} style={{
          fontFamily: 'inherit', padding: '10px 16px', background: 'transparent',
          border: 'none', borderRight: '1px solid var(--bd)',
          color: 'var(--tx-2)', cursor: 'pointer', textAlign: 'left',
          display: 'flex', flexDirection: 'column', gap: 1,
          transition: 'background .12s, color .12s',
        }}
          onMouseEnter={(e) => { e.currentTarget.style.background = '#0e1a2c'; e.currentTarget.style.color = 'var(--amber)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--tx-2)'; }}
        >
          <span style={{ fontSize: 12, fontWeight: 500 }}>{it.t}</span>
          <span className="mono" style={{ fontSize: 10, color: 'var(--tx-3)' }}>{it.s}</span>
        </button>
      ))}
    </div>
  );
}

// ───────────────────────── root ─────────────────────────

function VariationA({ density = 'full', scenario = 'normal' } = {}) {
  const initialPhase = scenario === 'submitted' ? 'submitted' : 'candidates';
  const initialDecisions = scenario === 'submitted'
    ? { NVDA: 'approve', HD: 'approve', UNH: 'approve' }
    : { NVDA: 'approve', HD: 'approve' };
  const [phase, setPhase] = useState(initialPhase);
  const [decisions, setDecisions] = useState(initialDecisions);
  const [exits, setExits] = useState({ XOM: 'close' });
  const [openPanel, setOpenPanel] = useState(null); // 'universe' | 'signals' | 'ticker' | 'audit' | 'policy' | 'monitor'
  const [panelTicker, setPanelTicker] = useState('NVDA');

  const approvedCount = Object.values(decisions).filter(d => d === 'approve').length;
  const decisionsCount = Object.keys(decisions).length;

  const reset = () => {
    setPhase('candidates');
    setDecisions({});
    setExits({});
  };

  const openTicker = (t) => { setPanelTicker(t); setOpenPanel('ticker'); };
  const openAudit  = (t) => { setPanelTicker(t); setOpenPanel('audit'); };

  // Nav-bar opens: the Audit instrument has no row context, so default it
  // to a ticker that actually has a recorded lifecycle trace.
  const handleNavOpen = (key) => {
    if (key === 'audit') {
      const traced = Object.keys(D.auditLifecycle || {});
      if (traced.length) setPanelTicker(traced[0]);
    }
    setOpenPanel(key);
  };

  const wrapperClass = `vA${density === 'calm' ? ' calm' : ''}`;

  // ─── scenario short-circuits ────────────────────────────────────
  if (scenario === 'outage') {
    return (
      <div className={wrapperClass} style={{ width: 1440, minHeight: 1000, position: 'relative' }} data-screen-label="A · Engine Outage">
        <TopBar phase={phase} />
        <OutageStateA />
      </div>
    );
  }

  return (
    <div className={wrapperClass} style={{ width: 1440, minHeight: 1000, position: 'relative' }} data-screen-label="A · Pre-Flight Cockpit">
      <TopBar phase={phase} />
      <InstrumentCluster approvedCount={approvedCount} />
      <EngineStrip />
      <InstrumentsNav onOpen={handleNavOpen} />
      <PhaseRail phase={phase} decisionsCount={decisionsCount} approvedCount={approvedCount} />

      {scenario === 'no-actionable' && phase === 'candidates' ? (
        <NoActionableStateA onAdvance={() => setPhase('portfolio')} />
      ) : (
        <>
          {phase === 'candidates' && (
            <CandidatesPhase decisions={decisions} setDecisions={setDecisions}
              onAdvance={() => setPhase('portfolio')}
              onOpenTicker={openTicker} onOpenAudit={openAudit} />
          )}
          {phase === 'portfolio' && (
            <PortfolioPhase exits={exits} setExits={setExits}
              onAdvance={() => setPhase('clearance')}
              onBack={() => setPhase('candidates')} />
          )}
          {phase === 'clearance' && (
            <ClearancePhase decisions={decisions} exits={exits}
              onSubmit={() => setPhase('submitted')}
              onBack={() => setPhase('portfolio')} />
          )}
          {phase === 'submitted' && (
            <ClearedPhase decisions={decisions} onReset={reset} />
          )}
        </>
      )}

      {/* instrument overlays */}
      <CockpitOverlay open={openPanel === 'universe'} onClose={() => setOpenPanel(null)}
        badge="UNIVERSE" title="Universe · data sources" sub="point-in-time membership + source freshness">
        <PanelUniverse />
      </CockpitOverlay>
      <CockpitOverlay open={openPanel === 'signals'} onClose={() => setOpenPanel(null)}
        badge="SIGNALS" title="Signals · evidence log" sub="confirmed lanes count toward breadth; inferred is context only">
        <PanelSignals />
      </CockpitOverlay>
      <CockpitOverlay open={openPanel === 'ticker'} onClose={() => setOpenPanel(null)}
        badge="TICKER" title={`${panelTicker} · deep dive`} sub="factor breakdown, evidence pack, policy gates">
        <PanelTickerDetail ticker={panelTicker} />
      </CockpitOverlay>
      <CockpitOverlay open={openPanel === 'audit'} onClose={() => setOpenPanel(null)}
        badge="AUDIT" title={`${panelTicker} · decision trace`} sub="every state transition recorded with reason">
        <PanelAudit ticker={panelTicker} />
      </CockpitOverlay>
      <CockpitOverlay open={openPanel === 'policy'} onClose={() => setOpenPanel(null)}
        badge="POLICY" title="Portfolio policy" sub="caps, thresholds, and operational flags" width={1080}>
        <PanelPolicy />
      </CockpitOverlay>
      <CockpitOverlay open={openPanel === 'monitor'} onClose={() => setOpenPanel(null)}
        badge="MONITOR" title="Continuous monitor" sub="between-cycle events · live stream">
        <PanelMonitor />
      </CockpitOverlay>
    </div>
  );
}

window.VariationA = VariationA;
