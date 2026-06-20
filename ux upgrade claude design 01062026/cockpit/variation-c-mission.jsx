// Variation C — MISSION CONTROL
// Three columns visible at once: CANDIDATES · PORTFOLIO · CLEARANCE.
// Approving on the left flies items into the right-column manifest.
// NASA-console aesthetic — amber on black, dense telemetry strip, status grid.

const { useState: useStateC, useMemo: useMemoC, useEffect: useEffectC, useRef: useRefC } = React;
const DC2 = window.COCKPIT_DATA;

// shared shell + panel components
const WhyMarkC = window.WhyMark;
const CockpitTipC = window.CockpitTip;
const CockpitOverlayC = window.CockpitOverlay;
const PanelUniverseC = window.PanelUniverse;
const PanelSignalsC = window.PanelSignals;
const PanelTickerDetailC = window.PanelTickerDetail;
const PanelAuditC = window.PanelAudit;
const PanelPolicyC = window.PanelPolicy;
const PanelMonitorC = window.PanelMonitor;

// ───────────────────────── primitives ─────────────────────────

function MCBadge({ children, color = 'var(--pri)', filled }) {
  return (
    <span style={{
      fontSize: 9, letterSpacing: '.16em', textTransform: 'uppercase',
      padding: '3px 7px',
      color: filled ? '#0a0e15' : color,
      background: filled ? color : 'transparent',
      border: `1px solid ${color}`,
      fontWeight: 500,
      whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

function MCColumn({ title, sub, idx, active, n, children, head, dimmed }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', minHeight: 0,
      borderLeft: idx > 0 ? '1px solid var(--bd)' : 'none',
      background: active ? '#0a0f17' : 'var(--bg)',
      transition: 'background .2s, opacity .3s, filter .3s',
      opacity: dimmed ? 0.42 : 1,
      pointerEvents: dimmed ? 'none' : 'auto',
      filter: dimmed ? 'saturate(0.55)' : 'none',
      position: 'relative',
    }}>
      <div style={{
        padding: '14px 18px 12px', borderBottom: `1px solid ${active ? 'var(--pri-d)' : 'var(--bd)'}`,
        background: active ? '#0e131c' : 'var(--panel)',
        position: 'relative',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="mono" style={{
            fontSize: 11, color: active ? 'var(--pri)' : 'var(--tx-3)',
            letterSpacing: '.18em', fontWeight: 600,
          }}>STAGE/{String(idx + 1).padStart(2, '0')}</span>
          <span style={{ fontSize: 13, fontWeight: 500, letterSpacing: '.06em', color: active ? 'var(--tx)' : 'var(--tx-2)' }}>
            {title}
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.04em' }}>
            {sub}
          </span>
        </div>
        {head}
        {active && (
          <div style={{
            position: 'absolute', left: 0, right: 0, bottom: -1, height: 2,
            background: 'var(--pri)', boxShadow: '0 0 12px var(--pri)',
          }} />
        )}
      </div>
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {children}
      </div>
    </div>
  );
}

// ───────────────────────── telemetry strip ─────────────────────────

function TelemetryStrip({ stage, decisions, exits, onOpenPanel }) {
  const acct = DC2.account;
  const approvedCount = Object.values(decisions).filter(d => d === 'approve').length;
  const exitCount = Object.values(exits).filter(v => v === 'close').length;
  const { mm, ss } = window.useCockpitCountdown(13 * 60 + 14);

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'auto 1fr auto auto',
      padding: '12px 20px',
      background: '#05080d', borderBottom: '1px solid var(--bd-2)',
      alignItems: 'center', gap: 24,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <CrosshairMark />
        <div>
          <div style={{ fontSize: 12, color: 'var(--tx)', fontWeight: 600, letterSpacing: '.04em' }}>
            AGENCY · MISSION CTRL
          </div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.06em' }}>
            t-{DC2.cycle.id} · next-<span className="cockpit-pulse" style={{ color: 'var(--pri)' }}>{mm}:{ss}</span> · {new Date().toISOString().split('T')[0]}
          </div>
        </div>
      </div>

      <div data-calm-hide="telem-mid" style={{ display: 'flex', gap: 22, justifyContent: 'center', flexWrap: 'wrap' }}>
        <Telem label="SPY 20d"   v="+2.4%" col="var(--pos)" />
        <Telem label="VIX"        v="14.8" />
        <Telem label="Breadth"    v="62%" col="var(--pos)" />
        <Telem label="Gross"      v={`${acct.grossExposure}% → ${acct.grossPostTrade}%`} col="var(--warn)"
          tip={`Account exposure: ${acct.grossExposure}% currently, will be ${acct.grossPostTrade}% if all approved orders fill. Cap ${acct.grossCap}%.`} />
        <Telem label="Cash"       v={`${acct.cashAvailable}%`}
          tip={`Uninvested cash. Floor ${acct.cashCap}% — policy blocks any order that breaches.`} />
        <Telem label="Open ord."  v={`${acct.openOrders}/${acct.openOrdersCap}`} />
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        <Telem label="Approved" v={approvedCount} col="var(--pos)" big />
        <Telem label="To exit"  v={exitCount} col={exitCount ? 'var(--neg)' : 'var(--tx-2)'} big />
      </div>

      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <PanelNavBtn onClick={() => onOpenPanel('universe')} title="Universe · sources">U</PanelNavBtn>
        <PanelNavBtn onClick={() => onOpenPanel('signals')}  title="Signals · log">S</PanelNavBtn>
        <PanelNavBtn onClick={() => onOpenPanel('audit')}    title="Audit · trace">A</PanelNavBtn>
        <PanelNavBtn onClick={() => onOpenPanel('policy')}   title="Policy editor">P</PanelNavBtn>
        <PanelNavBtn onClick={() => onOpenPanel('monitor')}  title="Monitor stream">M</PanelNavBtn>
        <span style={{
          fontSize: 10, letterSpacing: '.18em', padding: '4px 10px', marginLeft: 6,
          background: 'rgba(255,139,61,.15)', color: 'var(--pri)',
          border: '1px solid var(--pri-d)',
        }}>{DC2.cycle.mode}</span>
      </div>
    </div>
  );
}

function PanelNavBtn({ onClick, title, children }) {
  return (
    <button onClick={onClick} title={title} style={{
      fontFamily: 'inherit', fontSize: 11, fontWeight: 600, letterSpacing: '.04em',
      width: 26, height: 26, padding: 0, cursor: 'pointer',
      border: '1px solid var(--bd-2)', background: 'transparent',
      color: 'var(--tx-2)', borderRadius: 2,
      transition: 'all .12s',
    }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,139,61,.15)'; e.currentTarget.style.color = 'var(--pri)'; e.currentTarget.style.borderColor = 'var(--pri-d)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--tx-2)'; e.currentTarget.style.borderColor = 'var(--bd-2)'; }}
    >{children}</button>
  );
}

function CrosshairMark() {
  return (
    <svg viewBox="0 0 30 30" width="28" height="28">
      <circle cx="15" cy="15" r="11" fill="none" stroke="var(--pri)" strokeWidth="1.2" />
      <circle cx="15" cy="15" r="4"  fill="none" stroke="var(--pri)" strokeWidth="1" />
      <path d="M 15 2 L 15 8 M 15 22 L 15 28 M 2 15 L 8 15 M 22 15 L 28 15" stroke="var(--pri)" strokeWidth="1" />
      <circle cx="15" cy="15" r="1.5" fill="var(--pri)" />
    </svg>
  );
}

function Telem({ label, v, col = 'var(--tx)', big, tip }) {
  return (
    <div style={{
      padding: big ? '4px 12px' : 0,
      background: big ? 'rgba(255,139,61,.06)' : 'transparent',
      border: big ? '1px solid var(--bd)' : 'none',
      borderRadius: big ? 2 : 0,
    }}>
      <div style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--tx-3)', textTransform: 'uppercase', display: 'inline-flex', alignItems: 'center' }}>
        {label}{tip && <WhyMarkC tip={tip} />}
      </div>
      <div className="mono" style={{ fontSize: big ? 18 : 13, color: col, fontWeight: 500 }}>{v}</div>
    </div>
  );
}

// ───────────────────────── stage 1: candidates ─────────────────────────

function CandidatesColumn({ decisions, setDecisions, active, dimmed, onFocus, selectedTicker, setSelected, onApprovalFly, onOpenTicker, onOpenAudit }) {
  const list = useMemoC(() => [...DC2.candidates].sort((a, b) => b.finalConviction - a.finalConviction), []);
  const sel = list.find(c => c.ticker === selectedTicker) || list[0];

  const approvedCount = Object.values(decisions).filter(d => d === 'approve').length;
  const actionableCount = list.filter(c => c.status === 'approved').length;

  const handleDecide = (t, v, e) => {
    setDecisions(prev => ({ ...prev, [t]: v }));
    if (v === 'approve' && e) {
      onApprovalFly(t, e.currentTarget);
    }
  };

  return (
    <MCColumn idx={0} title="Candidates" active={active} dimmed={dimmed}
      sub={`${approvedCount}/${actionableCount} cleared`}
      head={
        <div style={{ marginTop: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
          <FunnelCrumbs />
        </div>
      }>
      <div style={{ flex: 1, display: 'grid', gridTemplateRows: 'minmax(0, 320px) 1fr', minHeight: 0 }}>
        {/* list */}
        <div style={{ overflow: 'auto' }}>
          {list.map((c, i) => {
            const isSel = c.ticker === sel?.ticker;
            const decision = decisions[c.ticker];
            const actionable = c.status === 'approved';
            const tone = decision === 'approve' ? 'var(--pos)' :
                         decision === 'reject' ? 'var(--neg)' :
                         decision === 'defer' ? 'var(--warn)' :
                         !actionable ? 'var(--tx-3)' : 'var(--pri)';
            return (
              <div key={c.ticker}
                onClick={() => { setSelected(c.ticker); onFocus(); }}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '22px 60px 56px 1fr auto',
                  gap: 10, padding: '9px 14px', alignItems: 'center',
                  background: isSel ? 'rgba(255,139,61,.08)' : 'transparent',
                  borderLeft: `3px solid ${isSel ? 'var(--pri)' : 'transparent'}`,
                  borderBottom: '1px solid var(--bd)',
                  cursor: 'pointer',
                  transition: 'background .12s',
                }}>
                <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3)' }}>
                  {String(i + 1).padStart(2, '0')}
                </div>
                <div className="mono" onClick={(e) => { e.stopPropagation(); onOpenTicker(c.ticker); }}
                  style={{ fontSize: 13, fontWeight: 500, color: 'var(--tx)', cursor: 'pointer' }}
                  title="Open deep-dive">
                  {c.ticker}
                </div>
                <ConvictionBar value={c.finalConviction} />
                <div style={{ overflow: 'hidden' }}>
                  <div style={{ fontSize: 11, color: 'var(--tx-2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {c.evidence[0]?.text || c.blocker || '—'}
                  </div>
                </div>
                <div>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
                    background: tone, boxShadow: `0 0 6px ${tone}`,
                  }} />
                </div>
              </div>
            );
          })}
        </div>

        {/* detail */}
        <div style={{
          borderTop: '2px solid var(--pri-d)',
          background: '#070b13', padding: 14, overflow: 'auto',
        }}>
          {sel && <CandidateDetailC c={sel} decision={decisions[sel.ticker]}
            onDecide={(v, e) => handleDecide(sel.ticker, v, e)}
            onOpenTicker={onOpenTicker} onOpenAudit={onOpenAudit} />}
        </div>
      </div>
    </MCColumn>
  );
}

function FunnelCrumbs() {
  const F = DC2.funnel;
  const steps = [
    { l: 'Universe',  v: F.universeReady },
    { l: 'Fund.',     v: F.fundamentalsPass },
    { l: 'Signals',   v: F.signals },
    { l: 'Det.',      v: F.deterministic },
    { l: 'LLM',       v: F.llmAgree },
    { l: 'Final',     v: F.final },
  ];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap', overflow: 'hidden' }}>
      {steps.map((s, i) => (
        <React.Fragment key={s.l}>
          <span style={{
            fontSize: 10, color: i === steps.length - 1 ? 'var(--pri)' : 'var(--tx-3)',
            fontWeight: i === steps.length - 1 ? 600 : 400,
          }}>
            {s.l}<span className="mono" style={{ marginLeft: 4, color: 'var(--tx-2)' }}>{s.v}</span>
          </span>
          {i < steps.length - 1 && <span style={{ color: 'var(--tx-3)', fontSize: 9 }}>›</span>}
        </React.Fragment>
      ))}
    </div>
  );
}

function ConvictionBar({ value }) {
  const v = Math.max(0, Math.min(1, value));
  const animV = window.useAnimatedValue(v, 700, [value]);
  const color = v >= 0.62 ? 'var(--pos)' : v >= 0.40 ? 'var(--warn)' : 'var(--neg)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span className="mono" style={{ fontSize: 11, color, width: 28 }}>{value.toFixed(2)}</span>
      <div style={{
        position: 'relative', width: 14, height: 14,
        background: 'rgba(255,255,255,.05)', borderRadius: 1,
      }}>
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0,
          height: `${animV * 100}%`, background: color,
        }} />
      </div>
    </div>
  );
}

function CandidateDetailC({ c, decision, onDecide, onOpenTicker, onOpenAudit }) {
  const actionable = c.status === 'approved';
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600, letterSpacing: -.5, display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span onClick={() => onOpenTicker(c.ticker)} style={{ cursor: 'pointer' }} title="Open deep-dive">{c.ticker}</span>
            <span style={{ fontSize: 11, color: 'var(--tx-3)' }}>· {c.sector}</span>
            {(c.status === 'demoted' || c.status === 'blocked' || c.status === 'rejected') && (
              <a onClick={() => onOpenAudit(c.ticker)} style={{ color: 'var(--acc)', cursor: 'pointer', textDecoration: 'underline', fontSize: 10, letterSpacing: '.04em' }}>
                audit ›
              </a>
            )}
          </div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3)', marginTop: 2 }}>
            ${c.price.toFixed(2)} · earnings {c.earningsDays}d
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SidebySide d={c.detConviction} l={c.llmConviction} />
        </div>
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 10,
      }}>
        <DataChip l="Det. score" v={c.detConviction.toFixed(2)}
          c={c.detConviction >= 0.62 ? 'var(--pos)' : 'var(--warn)'} />
        <DataChip l="LLM score" v={c.llmConviction.toFixed(2)}
          c={c.llmConviction >= 0.62 ? 'var(--pos)' : 'var(--warn)'} />
      </div>

      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 9, color: 'var(--tx-3)', letterSpacing: '.16em', textTransform: 'uppercase', marginBottom: 4 }}>
          Evidence
        </div>
        {c.evidence.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--tx-3)' }}>None this cycle.</div>
        ) : c.evidence.map((e, i) => (
          <div key={i} style={{
            display: 'flex', gap: 8, fontSize: 11, color: 'var(--tx-2)',
            padding: '4px 0', borderBottom: '1px solid var(--bd)', alignItems: 'baseline',
          }}>
            <span style={{
              fontSize: 8, letterSpacing: '.1em',
              color: e.tier === 'confirmed' ? 'var(--pos)' : 'var(--warn)',
              padding: '1px 5px', border: `1px solid ${e.tier === 'confirmed' ? 'var(--pos)' : 'var(--warn)'}`,
              borderRadius: 1, flexShrink: 0,
            }}>{e.tier === 'confirmed' ? 'CONF' : 'INF'}</span>
            <span>{e.text}</span>
          </div>
        ))}
      </div>

      {c.concerns.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, color: 'var(--warn)', letterSpacing: '.16em', textTransform: 'uppercase', marginBottom: 4 }}>
            Risk flags
          </div>
          {c.concerns.map((co, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--tx-2)', padding: '2px 0' }}>
              <span style={{ color: 'var(--warn)', marginRight: 6 }}>▲</span>{co}
            </div>
          ))}
        </div>
      )}

      <div style={{
        padding: 10, fontSize: 11, color: 'var(--tx-2)',
        background: 'rgba(77,208,225,.06)', border: '1px solid rgba(77,208,225,.18)',
        lineHeight: 1.5, fontStyle: 'italic', marginBottom: 14,
      }}>
        <span style={{ color: 'var(--acc)', fontStyle: 'normal', letterSpacing: '.1em', fontSize: 9 }}>LLM ▸</span> {c.llmRationale}
      </div>

      {actionable ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4 }}>
          <MCDecisionBtn label="Reject" col="var(--neg)" active={decision === 'reject'} onClick={(e) => onDecide('reject', e)} />
          <MCDecisionBtn label="Defer"  col="var(--tx-3)"  active={decision === 'defer'}  onClick={(e) => onDecide('defer', e)} />
          <MCDecisionBtn label="Approve · stage" col="var(--pos)" active={decision === 'approve'} onClick={(e) => onDecide('approve', e)} primary />
        </div>
      ) : (
        <div style={{
          padding: 10, fontSize: 11, color: 'var(--tx-2)',
          background: 'rgba(255,100,100,.06)', border: '1px solid rgba(255,100,100,.18)',
        }}>
          <span style={{ color: 'var(--neg)', letterSpacing: '.1em', fontSize: 9 }}>NOT ACTIONABLE ▸</span> {c.blocker || `Below threshold (${c.finalConviction.toFixed(2)} < 0.56).`}
        </div>
      )}
    </div>
  );
}

function SidebySide({ d, l }) {
  const dot = (v) => v >= 0.62 ? 'var(--pos)' : v >= 0.40 ? 'var(--warn)' : 'var(--neg)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{ fontSize: 9, letterSpacing: '.1em', color: 'var(--tx-3)' }}>DET</span>
      <span style={{ width: 9, height: 9, borderRadius: '50%', background: dot(d), boxShadow: `0 0 6px ${dot(d)}` }} />
      <span style={{ fontSize: 9, letterSpacing: '.1em', color: 'var(--tx-3)', marginLeft: 4 }}>LLM</span>
      <span style={{ width: 9, height: 9, borderRadius: '50%', background: dot(l), boxShadow: `0 0 6px ${dot(l)}` }} />
    </div>
  );
}

function DataChip({ l, v, c = 'var(--tx)' }) {
  return (
    <div style={{
      padding: '6px 10px', background: 'rgba(255,255,255,.02)',
      border: '1px solid var(--bd)', borderRadius: 2,
    }}>
      <div style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--tx-3)', textTransform: 'uppercase' }}>{l}</div>
      <div className="mono" style={{ fontSize: 16, color: c, marginTop: 2 }}>{v}</div>
    </div>
  );
}

function MCDecisionBtn({ label, col, active, onClick, primary }) {
  return (
    <button onClick={(e) => onClick(e)} style={{
      fontFamily: 'inherit', fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase',
      padding: '9px 8px', cursor: 'pointer',
      border: `1px solid ${active ? col : 'var(--bd-2)'}`,
      background: active ? col : (primary ? 'rgba(91,224,160,.08)' : 'transparent'),
      color: active ? '#0a0e15' : col,
      fontWeight: primary ? 600 : 500,
      transition: 'all .12s',
    }}>{label}</button>
  );
}

// ───────────────────────── stage 2: portfolio ─────────────────────────

function PortfolioColumn({ exits, setExits, active, dimmed, onFocus }) {
  const acct = DC2.account;
  const closeCount = Object.values(exits).filter(v => v === 'close').length;
  return (
    <MCColumn idx={1} title="Portfolio" active={active} dimmed={dimmed}
      sub={`5 pos · ${closeCount} exit`}
      head={
        <div style={{ marginTop: 8, display: 'flex', gap: 12 }}>
          <MiniMeter label="Gross" cur={67} post={84} cap={100} />
          <MiniMeter label="Cash"  cur={33} post={18} cap={10} floor />
          <MiniMeter label="Tech"  cur={22} post={30} cap={30} warn />
        </div>
      }>
      <div style={{ flex: 1, overflow: 'auto' }} onClick={onFocus}>
        {DC2.positions.map(p => {
          const pl = ((p.current - p.entry) / p.entry) * 100;
          const stopDist = ((p.current - p.stop) / p.current) * 100;
          const palette = {
            hold:   { c: 'var(--pos)',  t: 'HOLD' },
            review: { c: 'var(--warn)', t: 'REVIEW' },
            close:  { c: 'var(--neg)',  t: 'CLOSE' },
          }[p.status];
          const decided = exits[p.ticker];
          return (
            <div key={p.ticker} style={{
              padding: '11px 14px', borderBottom: '1px solid var(--bd)',
              borderLeft: `3px solid ${palette.c}`,
              background: decided === 'close' ? 'rgba(255,100,100,.05)'
                       : decided === 'keep'  ? 'rgba(91,224,160,.04)'
                       : 'transparent',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="mono" style={{ fontSize: 13, fontWeight: 500 }}>{p.ticker}</span>
                  <MCBadge color={palette.c}>{palette.t}</MCBadge>
                </div>
                <div className="mono" style={{
                  fontSize: 13, color: pl >= 0 ? 'var(--pos)' : 'var(--neg)',
                }}>{pl >= 0 ? '+' : ''}{pl.toFixed(1)}%</div>
              </div>
              <div style={{ fontSize: 11, color: 'var(--tx-2)', lineHeight: 1.4, marginBottom: 8 }}>
                {p.thesis}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3)' }}>
                  {p.daysHeld}d · stop -{stopDist.toFixed(1)}%
                </div>
                {p.status === 'hold' ? (
                  <span style={{ fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.08em' }}>auto-aligned</span>
                ) : decided ? (
                  <button style={{
                    fontFamily: 'inherit', fontSize: 10, letterSpacing: '.08em',
                    border: `1px solid ${decided === 'close' ? 'var(--neg)' : 'var(--pos)'}`,
                    background: 'transparent',
                    color: decided === 'close' ? 'var(--neg)' : 'var(--pos)',
                    padding: '4px 9px', cursor: 'pointer',
                  }} onClick={() => setExits(prev => { const n = {...prev}; delete n[p.ticker]; return n; })}>
                    {decided === 'close' ? 'WILL CLOSE' : 'KEEP'} · UNDO
                  </button>
                ) : (
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button style={mcSmallBtn('var(--neg)')} onClick={() => setExits(prev => ({...prev, [p.ticker]: 'close'}))}>Close</button>
                    <button style={mcSmallBtn('var(--tx-2)')} onClick={() => setExits(prev => ({...prev, [p.ticker]: 'keep'}))}>Keep</button>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        <SectorRadar />
      </div>
    </MCColumn>
  );
}

const mcSmallBtn = (c) => ({
  fontFamily: 'inherit', fontSize: 10, letterSpacing: '.08em', textTransform: 'uppercase',
  padding: '4px 9px', cursor: 'pointer',
  border: `1px solid ${c}`,
  background: 'transparent', color: c,
});

function MiniMeter({ label, cur, post, cap, warn, floor }) {
  const pct = Math.min(100, (post / cap) * 100);
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 9, letterSpacing: '.12em', color: 'var(--tx-3)' }}>{label.toUpperCase()}</div>
      <div className="mono" style={{ fontSize: 11, color: 'var(--tx-2)' }}>
        {cur}<span style={{ color: 'var(--tx-3)' }}> → </span>
        <span style={{ color: warn || (floor ? post <= cap : pct >= 95) ? 'var(--warn)' : 'var(--tx)' }}>{post}</span>
      </div>
      <div style={{ height: 3, background: 'rgba(255,255,255,.05)', marginTop: 3, position: 'relative' }}>
        <div style={{
          position: 'absolute', inset: 0, width: `${pct}%`,
          background: warn || pct >= 95 ? 'var(--warn)' : 'var(--pos)',
        }} />
      </div>
    </div>
  );
}

function SectorRadar() {
  return (
    <div style={{
      padding: 14, borderTop: '1px solid var(--bd)',
      background: '#070b13',
    }}>
      <div style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--tx-3)', marginBottom: 8 }}>
        SECTOR HEATMAP · 4 TAILWIND · 2 PRESSURE
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 2 }}>
        {DC2.sectors.map(s => {
          const col = s.state === 'tailwind' ? 'var(--pos)'
                    : s.state === 'pressure' ? 'var(--neg)'
                    : s.state === 'neutral'  ? 'var(--tx-3)'
                    : 'var(--bd-2)';
          return (
            <div key={s.name} style={{
              padding: '5px 8px',
              borderLeft: `2px solid ${col}`,
              background: `${col === 'var(--pos)' ? 'rgba(91,224,160,.04)'
                          : col === 'var(--neg)' ? 'rgba(255,100,100,.04)'
                          : 'rgba(255,255,255,.02)'}`,
            }}>
              <div style={{ fontSize: 10, color: 'var(--tx)' }}>{s.name}</div>
              <div className="mono" style={{ fontSize: 9, color: 'var(--tx-3)' }}>{s.detail}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ───────────────────────── stage 3: clearance ─────────────────────────

function ClearanceColumn({ decisions, exits, onSubmit, onFocus, active, submitted }) {
  const approved = DC2.candidates.filter(c => decisions[c.ticker] === 'approve');
  const exitsToClose = Object.entries(exits).filter(([, v]) => v === 'close').map(([k]) => k);
  const [gateOpen, setGateOpen] = useStateC(false);
  const [phrase, setPhrase] = useStateC('');
  const required = 'submit paper orders';
  const phraseOk = phrase.trim().toLowerCase() === required;
  const canSubmit = gateOpen && phraseOk && approved.length > 0 && !submitted;
  const total = approved.reduce((s, c) => s + c.notional, 0);

  return (
    <MCColumn idx={2} title="Clearance" active={active}
      sub={submitted ? 'submitted' : gateOpen ? 'gate · OPEN' : 'gate · CLOSED'}
      head={
        <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            width: 10, height: 10, borderRadius: '50%',
            background: submitted ? 'var(--pos)' : gateOpen ? 'var(--warn)' : 'var(--neg)',
            boxShadow: `0 0 8px ${submitted ? 'var(--pos)' : gateOpen ? 'var(--warn)' : 'var(--neg)'}`,
          }} />
          <span className="mono" style={{ fontSize: 11, color: 'var(--tx-2)' }}>
            {approved.length} orders · ${total.toLocaleString()}
          </span>
        </div>
      }>
      <div style={{ flex: 1, overflow: 'auto' }} onClick={onFocus}>
        {submitted ? (
          <SubmittedPane approved={approved} />
        ) : approved.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--tx-3)', fontSize: 12, lineHeight: 1.6 }}>
            <div style={{ fontSize: 28, marginBottom: 8, opacity: .3 }}>◉</div>
            No orders staged.<br />
            <span style={{ color: 'var(--tx-3)' }}>Approve a candidate to begin.</span>
          </div>
        ) : (
          <>
            {exitsToClose.length > 0 && (
              <div style={{ padding: '10px 14px', background: 'rgba(255,100,100,.06)', borderBottom: '1px solid var(--bd)' }}>
                <div style={{ fontSize: 9, color: 'var(--neg)', letterSpacing: '.14em', marginBottom: 5 }}>EXITS · FIRST</div>
                {exitsToClose.map(t => (
                  <div key={t} className="mono" style={{ fontSize: 11, color: 'var(--tx-2)', padding: '2px 0' }}>
                    <span style={{ color: 'var(--neg)' }}>▼ SELL</span> · {t}
                  </div>
                ))}
              </div>
            )}

            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--bd)' }}>
              <div style={{ fontSize: 9, color: 'var(--pos)', letterSpacing: '.14em', marginBottom: 5 }}>STAGED ORDERS · BUY</div>
              {approved.map(c => (
                <ManifestRow key={c.ticker} c={c} />
              ))}
            </div>

            <GatePanel
              gateOpen={gateOpen} setGateOpen={setGateOpen}
              phrase={phrase} setPhrase={setPhrase}
              required={required} phraseOk={phraseOk}
              canSubmit={canSubmit} onSubmit={onSubmit}
              total={total} count={approved.length}
            />
          </>
        )}
      </div>
    </MCColumn>
  );
}

function ManifestRow({ c }) {
  return (
    <div style={{
      padding: '8px 0', borderBottom: '1px dotted var(--bd)',
      display: 'grid', gridTemplateColumns: '60px 1fr auto', gap: 10, alignItems: 'baseline',
    }}>
      <div>
        <div className="mono" style={{ fontSize: 13, fontWeight: 500 }}>{c.ticker}</div>
      </div>
      <div className="mono" style={{ fontSize: 11, color: 'var(--tx-2)' }}>
        BUY {c.qty} @ ${c.price.toFixed(2)}
        <span style={{ color: 'var(--tx-3)', marginLeft: 6 }}>
          (S {c.stopPct}% / T +{c.targetPct}%)
        </span>
      </div>
      <div className="mono" style={{ fontSize: 11, color: 'var(--tx)' }}>
        ${c.notional.toLocaleString()}
      </div>
    </div>
  );
}

function GatePanel({ gateOpen, setGateOpen, phrase, setPhrase, required, phraseOk, canSubmit, onSubmit, total, count }) {
  return (
    <div style={{ padding: 14, borderTop: '2px solid var(--pri-d)', background: '#070b13' }}>
      <div style={{ fontSize: 9, color: 'var(--pri)', letterSpacing: '.16em', marginBottom: 10 }}>
        SUBMIT GATE · ARMED?
      </div>

      <label style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '9px 11px',
        background: 'rgba(0,0,0,.4)', border: `1px solid ${gateOpen ? 'var(--warn)' : 'var(--bd)'}`,
        cursor: 'pointer', marginBottom: 8,
      }}>
        <input type="checkbox" checked={gateOpen} onChange={e => setGateOpen(e.target.checked)}
          style={{ accentColor: 'var(--pri)' }} />
        <span style={{ fontSize: 11, color: 'var(--tx-2)' }}>OPEN GATE</span>
        <span style={{ marginLeft: 'auto', fontSize: 9, color: gateOpen ? 'var(--warn)' : 'var(--tx-3)', letterSpacing: '.14em' }}>
          {gateOpen ? '● ARMED' : '○ SAFE'}
        </span>
      </label>

      <input
        value={phrase}
        onChange={e => setPhrase(e.target.value)}
        placeholder={`type: ${required}`}
        disabled={!gateOpen}
        className="mono"
        style={{
          width: '100%', padding: '9px 11px',
          background: '#03070d', border: `1px solid ${phraseOk ? 'var(--pos)' : 'var(--bd-2)'}`,
          color: 'var(--tx)', fontSize: 11, fontFamily: 'var(--mono)',
          outline: 'none', marginBottom: 10,
        }}
      />

      <button
        disabled={!canSubmit}
        onClick={onSubmit}
        style={{
          width: '100%', padding: '14px 12px',
          fontFamily: 'inherit', fontSize: 12, fontWeight: 600, letterSpacing: '.14em', textTransform: 'uppercase',
          border: 'none',
          background: canSubmit ? 'var(--pos)' : '#1a2230',
          color: canSubmit ? '#03150b' : 'var(--tx-3)',
          cursor: canSubmit ? 'pointer' : 'not-allowed',
          boxShadow: canSubmit ? '0 0 18px rgba(91,224,160,.4)' : 'none',
          transition: 'all .15s',
        }}>
        {canSubmit ? `▸ TRANSMIT · ${count} ORDERS · $${(total/1000).toFixed(1)}K` : 'LOCKED'}
      </button>

      <div style={{
        marginTop: 12, padding: '8px 0', fontSize: 9, color: 'var(--tx-3)',
        lineHeight: 1.6, letterSpacing: '.04em', borderTop: '1px solid var(--bd)',
      }}>
        BROKER alpaca-paper · SUBMIT_ENABLED <span style={{ color: 'var(--warn)' }}>true</span><br />
        SHORTS <span style={{ color: 'var(--neg)' }}>false</span> · OCO BRACKET <span style={{ color: 'var(--pos)' }}>enabled</span><br />
        LIVE_TRADING <span style={{ color: 'var(--neg)' }}>disabled</span>
      </div>
    </div>
  );
}

function SubmittedPane({ approved }) {
  return (
    <div style={{ padding: 20 }}>
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <div style={{
          width: 48, height: 48, margin: '0 auto 12px', borderRadius: '50%',
          border: '2px solid var(--pos)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, color: 'var(--pos)',
          boxShadow: '0 0 20px rgba(91,224,160,.4)',
        }}>✓</div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--pos)', letterSpacing: '.1em' }}>
          ▸ TRANSMITTED
        </div>
        <div style={{ fontSize: 11, color: 'var(--tx-3)', marginTop: 4 }}>
          {approved.length} orders · brackets attached
        </div>
      </div>
      {approved.map(c => (
        <div key={c.ticker} style={{
          padding: '8px 10px', marginBottom: 4,
          background: 'rgba(91,224,160,.04)', border: '1px solid rgba(91,224,160,.18)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="mono" style={{ fontSize: 12, fontWeight: 500 }}>{c.ticker}</span>
            <span style={{ fontSize: 9, color: 'var(--pos)', letterSpacing: '.1em' }}>ACCEPTED</span>
          </div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3)', marginTop: 2 }}>
            ALP-{Math.floor(Math.random() * 90000 + 10000)} · BUY {c.qty} @ ${c.price.toFixed(2)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ───────────────────────── scenario states ─────────────────────────

function OutageStateC() {
  return (
    <div style={{ padding: '60px 60px 80px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 40, alignItems: 'start' }}>
      <div>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '5px 10px', border: '1px solid var(--neg)',
          background: 'rgba(255,100,100,.08)',
          fontSize: 10, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--neg)',
          marginBottom: 18,
        }}>● TELEMETRY DEGRADED · STAGES 1–3 OFFLINE</div>
        <h1 style={{ fontSize: 38, fontWeight: 500, letterSpacing: -.5, lineHeight: 1.1, margin: '0 0 14px' }}>
          Selection blocked.<br />
          <span style={{ color: 'var(--tx-2)' }}>Cycle C-14:32 will not produce candidates.</span>
        </h1>
        <p style={{ fontSize: 14, color: 'var(--tx-2)', lineHeight: 1.55, maxWidth: 540 }}>
          Two upstream engines are offline. The agent is in circuit-breaker — it won't surface stale candidates for you to approve. Auto-retry every 30s.
        </p>
        <div style={{ marginTop: 28, display: 'flex', gap: 12 }}>
          <div style={{
            padding: '10px 14px', border: '1px solid var(--warn)', color: 'var(--warn)',
            fontSize: 11, letterSpacing: '.14em', textTransform: 'uppercase',
          }}>retry · 0:24</div>
          <div style={{
            padding: '10px 14px', border: '1px solid var(--bd-2)', color: 'var(--tx-2)',
            fontSize: 11, letterSpacing: '.14em', textTransform: 'uppercase',
          }}>last good cycle · C-13:58</div>
        </div>
      </div>

      <div style={{ background: 'var(--panel)', border: '1px solid var(--bd)' }}>
        <div style={{
          padding: '10px 16px', borderBottom: '1px solid var(--bd-2)',
          fontSize: 10, color: 'var(--pri)', letterSpacing: '.18em', textTransform: 'uppercase',
        }}>ENGINE TELEMETRY</div>
        {[
          { name: 'MARKET_DATA',    state: 'down', detail: 'WS disconnected · 18m', code: 'CONN_LOST' },
          { name: 'FUNDAMENTALS',   state: 'down', detail: '503 upstream · circuit open', code: 'UPSTREAM_5XX' },
          { name: 'SIGNALS_ENGINE', state: 'stale', detail: 'awaiting MARKET_DATA', code: 'BLOCKED' },
          { name: 'LLM_REVIEWER',   state: 'live', detail: 'idle · no input', code: 'OK' },
          { name: 'POLICY',         state: 'live', detail: 'cached · 4m ago', code: 'OK' },
          { name: 'RISK_MONITOR',   state: 'live', detail: 'positions tracking · OK', code: 'OK' },
          { name: 'AUDIT_LOG',      state: 'live', detail: 'persisted', code: 'OK' },
        ].map(e => {
          const colorMap = { down: 'var(--neg)', stale: 'var(--warn)', live: 'var(--pos)' };
          const col = colorMap[e.state];
          return (
            <div key={e.name} style={{
              display: 'grid', gridTemplateColumns: '12px 1fr auto auto', gap: 12,
              padding: '11px 16px', borderBottom: '1px solid var(--bd)', alignItems: 'center',
            }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: col, boxShadow: e.state === 'down' ? `0 0 8px ${col}` : 'none' }} />
              <span className="mono" style={{ fontSize: 12, color: 'var(--tx)', letterSpacing: '.04em' }}>{e.name}</span>
              <span style={{ fontSize: 11, color: 'var(--tx-3)' }}>{e.detail}</span>
              <span className="mono" style={{ fontSize: 10, color: col, letterSpacing: '.1em' }}>{e.code}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function NoActionableStateC() {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1.15fr 1fr 1fr',
      minHeight: 880, background: 'var(--bg)',
    }}>
      {/* col 1: empty candidates */}
      <div style={{ borderRight: '1px solid var(--bd)', padding: '32px 26px', background: '#080c12' }}>
        <div style={{ fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.18em', fontWeight: 600 }}>STAGE/01 · CANDIDATES</div>
        <div style={{
          marginTop: 36, padding: 24,
          border: '1px dashed var(--bd-2)', background: 'rgba(255,210,77,.04)',
        }}>
          <div style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--warn)', textTransform: 'uppercase' }}>● NO ACTIONABLE</div>
          <div style={{ fontSize: 22, fontWeight: 500, marginTop: 10, letterSpacing: -.2, lineHeight: 1.2 }}>
            Funnel completed.<br />Bar not cleared.
          </div>
          <div style={{ fontSize: 12, color: 'var(--tx-3)', marginTop: 12, lineHeight: 1.55 }}>
            152 scanned · 10 to final · <span className="mono" style={{ color: 'var(--tx-2)' }}>0</span> above conviction bar (0.62).
          </div>
        </div>

        <div style={{ marginTop: 28 }}>
          <div style={{ fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.16em', marginBottom: 10 }}>BLOCKED AT FINAL</div>
          {[
            { t: 'AAPL', col: 'var(--warn)', tag: 'demoted · 0.51', reason: 'thin earnings-rev evidence' },
            { t: 'GOOG', col: 'var(--warn)', tag: 'demoted · 0.54', reason: 'AI-spend not yet in Q numbers' },
            { t: 'TSLA', col: 'var(--neg)',  tag: 'policy block',   reason: 'concentration cap · 18%/25%' },
          ].map((r, i) => (
            <div key={r.t} style={{
              display: 'grid', gridTemplateColumns: '60px 1fr', gap: 14,
              padding: '10px 0', borderTop: i ? '1px solid var(--bd)' : 'none',
            }}>
              <div className="mono" style={{ fontSize: 14, color: 'var(--tx-2)', fontWeight: 500 }}>{r.t}</div>
              <div>
                <div className="mono" style={{ fontSize: 10, color: r.col, letterSpacing: '.1em', textTransform: 'uppercase' }}>{r.tag}</div>
                <div style={{ fontSize: 11, color: 'var(--tx-3)', marginTop: 3 }}>{r.reason}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* col 2: portfolio (still active) */}
      <div style={{ borderRight: '1px solid var(--bd)', padding: '32px 26px' }}>
        <div style={{ fontSize: 10, color: 'var(--pri)', letterSpacing: '.18em', fontWeight: 600 }}>STAGE/02 · PORTFOLIO MONITOR</div>
        <div style={{ fontSize: 22, fontWeight: 500, marginTop: 10, letterSpacing: -.2 }}>
          Hold 5 positions.
        </div>
        <div style={{ fontSize: 12, color: 'var(--tx-3)', marginTop: 8, lineHeight: 1.5 }}>
          Nothing to add today. The agent still reviews existing positions for stop/take-profit drift.
        </div>
        <div style={{
          marginTop: 22, border: '1px solid var(--bd)', background: 'var(--panel)',
        }}>
          {[
            { t: 'NVDA', s: 'HOLD',   col: 'var(--pos)', d: 'thesis intact · +14% MTD' },
            { t: 'META', s: 'HOLD',   col: 'var(--pos)', d: 'no action · within band' },
            { t: 'UNH',  s: 'REVIEW', col: 'var(--warn)', d: 'drift to stop · -2.1%' },
            { t: 'XOM',  s: 'CLOSE?', col: 'var(--neg)', d: 'thesis weakened · sector pressured' },
            { t: 'JPM',  s: 'HOLD',   col: 'var(--pos)', d: 'core position' },
          ].map((r, i) => (
            <div key={r.t} style={{
              display: 'grid', gridTemplateColumns: '60px auto 1fr', gap: 12,
              padding: '10px 14px', borderBottom: i < 4 ? '1px solid var(--bd)' : 'none', alignItems: 'center',
            }}>
              <span className="mono" style={{ fontSize: 13, fontWeight: 500 }}>{r.t}</span>
              <span style={{
                fontSize: 9, letterSpacing: '.14em', padding: '2px 6px',
                color: r.col, border: `1px solid ${r.col}`,
              }}>{r.s}</span>
              <span style={{ fontSize: 11, color: 'var(--tx-3)' }}>{r.d}</span>
            </div>
          ))}
        </div>
      </div>

      {/* col 3: clearance (idle) */}
      <div style={{ padding: '32px 26px' }}>
        <div style={{ fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.18em', fontWeight: 600 }}>STAGE/03 · CLEARANCE</div>
        <div style={{
          marginTop: 36, padding: 40, textAlign: 'center',
          border: '1px dashed var(--bd-2)',
        }}>
          <div style={{ fontSize: 26, color: 'var(--tx-3)', marginBottom: 10, opacity: .35 }}>◯</div>
          <div style={{ fontSize: 14, color: 'var(--tx-2)', fontWeight: 500 }}>Manifest empty.</div>
          <div style={{ fontSize: 12, color: 'var(--tx-3)', marginTop: 8, lineHeight: 1.5 }}>
            No orders staged this cycle. The clearance gate stays closed.
          </div>
        </div>
        <div style={{
          marginTop: 24, padding: '12px 14px',
          background: 'rgba(77,208,225,.06)', border: '1px solid var(--bd)',
          fontSize: 11, color: 'var(--tx-2)', lineHeight: 1.5,
        }}>
          <span style={{ color: 'var(--acc)', letterSpacing: '.1em', textTransform: 'uppercase', fontWeight: 600, marginRight: 8 }}>note ›</span>
          Low-conviction days are normal. The next cycle reruns the funnel at C-14:46.
        </div>
      </div>
    </div>
  );
}

// ───────────────────────── root ─────────────────────────

function VariationC({ density = 'full', scenario = 'normal' } = {}) {
  const [stage, setStage] = useStateC(0); // 0 candidates, 1 portfolio, 2 clearance
  const initialDecisions = scenario === 'submitted'
    ? { NVDA: 'approve', HD: 'approve', UNH: 'approve' }
    : { NVDA: 'approve', HD: 'approve' };
  const [decisions, setDecisions] = useStateC(initialDecisions);
  const [exits, setExits] = useStateC({ XOM: 'close' });
  const [selected, setSelected] = useStateC('NVDA');
  const [submitted, setSubmitted] = useStateC(scenario === 'submitted');
  const [openPanel, setOpenPanel] = useStateC(null);
  const [panelTicker, setPanelTicker] = useStateC('NVDA');
  const [chips, setChips] = useStateC([]);
  const rootRef = useRefC(null);

  const approvedCount = Object.values(decisions).filter(d => d === 'approve').length;
  const exitCount = Object.values(exits).filter(v => v === 'close').length;

  useEffectC(() => {
    if (approvedCount > 0 && stage === 0 && exitCount > 0) setStage(2);
    else if (approvedCount > 0 && stage === 0) setStage(1);
  }, [approvedCount, exitCount]);

  const openTicker = (t) => { setPanelTicker(t); setOpenPanel('ticker'); };
  const openAudit  = (t) => { setPanelTicker(t); setOpenPanel('audit'); };

  // Telemetry-strip opens: Audit has no row context here, so default it
  // to a ticker that actually has a recorded lifecycle trace.
  const handleNavOpen = (key) => {
    if (key === 'audit') {
      const traced = Object.keys(DC2.auditLifecycle || {});
      if (traced.length) setPanelTicker(traced[0]);
    }
    setOpenPanel(key);
  };

  // approve animation: spawn a flying chip from the click position
  // toward the clearance column (~right third of artboard, ~y=320)
  const onApprovalFly = (ticker, sourceEl) => {
    if (!rootRef.current || !sourceEl) return;
    const r = rootRef.current.getBoundingClientRect();
    const s = sourceEl.getBoundingClientRect();
    const startX = s.left - r.left + s.width / 2;
    const startY = s.top  - r.top  + s.height / 2;
    // target: top of clearance column (right-third), manifest area
    const endX = 1440 - 220;
    const endY = 280;
    const id = Date.now() + Math.random();
    setChips(prev => [...prev, { id, ticker, startX, startY, dx: endX - startX, dy: endY - startY }]);
    setTimeout(() => setChips(prev => prev.filter(c => c.id !== id)), 750);
  };

  return (
    <div className={`vC${density === 'calm' ? ' calm' : ''}`} ref={rootRef} style={{ width: 1440, minHeight: 1000, position: 'relative' }} data-screen-label="C · Mission Control">
      <TelemetryStrip stage={stage} decisions={decisions} exits={exits} onOpenPanel={handleNavOpen} />

      {scenario === 'outage' ? (
        <OutageStateC />
      ) : scenario === 'no-actionable' ? (
        <NoActionableStateC />
      ) : (
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1.15fr 1fr 1fr',
        minHeight: 920,
        background: 'var(--bg)',
      }}>
        <CandidatesColumn
          decisions={decisions} setDecisions={setDecisions}
          selectedTicker={selected} setSelected={setSelected}
          active={stage === 0 && !submitted}
          dimmed={submitted}
          onFocus={() => setStage(0)}
          onApprovalFly={onApprovalFly}
          onOpenTicker={openTicker}
          onOpenAudit={openAudit}
        />
        <PortfolioColumn
          exits={exits} setExits={setExits}
          active={stage === 1 && !submitted}
          dimmed={submitted}
          onFocus={() => setStage(1)}
        />
        <ClearanceColumn
          decisions={decisions} exits={exits}
          submitted={submitted}
          onSubmit={() => setSubmitted(true)}
          active={stage === 2 || submitted}
          onFocus={() => setStage(2)}
        />
      </div>
      )}

      {/* status footer */}
      <div data-calm-hide="footer-engines" className="grid-bg" style={{
        padding: '10px 20px',
        background: '#05080d',
        borderTop: '1px solid var(--bd)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        fontSize: 10, color: 'var(--tx-3)', letterSpacing: '.06em',
      }}>
        <div style={{ display: 'flex', gap: 18 }}>
          {DC2.engines.map(e => (
            <span key={e.name} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{
                width: 5, height: 5, borderRadius: '50%',
                background: e.state === 'live' ? 'var(--pos)' : 'var(--warn)',
              }} />
              <span className="mono" style={{ color: e.state === 'live' ? 'var(--tx-2)' : 'var(--warn)' }}>
                {e.name.toUpperCase().slice(0, 14)}
              </span>
            </span>
          ))}
        </div>
        <div className="mono">RUNTIME_OK · 6/7 ENGINES</div>
      </div>

      {/* flying approval chips */}
      {chips.map(ch => (
        <div key={ch.id} className="cockpit-flychip mono"
          style={{
            left: ch.startX, top: ch.startY,
            ['--fly-end']: `translate(${ch.dx}px, ${ch.dy}px)`,
            background: 'var(--pos)', color: '#0a0e15',
            fontSize: 11, fontWeight: 700, letterSpacing: '.06em',
            padding: '6px 10px', borderRadius: 2,
            boxShadow: '0 4px 18px rgba(91,224,160,.6), 0 0 0 1px var(--pos)',
          }}>
          ▸ {ch.ticker}
        </div>
      ))}

      {/* instrument overlays */}
      <CockpitOverlayC open={openPanel === 'universe'} onClose={() => setOpenPanel(null)}
        accent="var(--pri)" scope="vC" badge="UNIVERSE" title="Universe · data sources" sub="point-in-time membership + source freshness">
        <PanelUniverseC />
      </CockpitOverlayC>
      <CockpitOverlayC open={openPanel === 'signals'} onClose={() => setOpenPanel(null)}
        accent="var(--pri)" scope="vC" badge="SIGNALS" title="Signals · evidence log" sub="confirmed lanes count toward breadth; inferred is context only">
        <PanelSignalsC />
      </CockpitOverlayC>
      <CockpitOverlayC open={openPanel === 'ticker'} onClose={() => setOpenPanel(null)}
        accent="var(--pri)" scope="vC" badge="TICKER" title={`${panelTicker} · deep dive`} sub="factor breakdown, evidence pack, policy gates">
        <PanelTickerDetailC ticker={panelTicker} />
      </CockpitOverlayC>
      <CockpitOverlayC open={openPanel === 'audit'} onClose={() => setOpenPanel(null)}
        accent="var(--pri)" scope="vC" badge="AUDIT" title={`${panelTicker} · decision trace`} sub="every state transition recorded with reason">
        <PanelAuditC ticker={panelTicker} />
      </CockpitOverlayC>
      <CockpitOverlayC open={openPanel === 'policy'} onClose={() => setOpenPanel(null)}
        accent="var(--pri)" scope="vC" badge="POLICY" title="Portfolio policy" sub="caps, thresholds, and operational flags" width={1080}>
        <PanelPolicyC />
      </CockpitOverlayC>
      <CockpitOverlayC open={openPanel === 'monitor'} onClose={() => setOpenPanel(null)}
        accent="var(--pri)" scope="vC" badge="MONITOR" title="Continuous monitor" sub="between-cycle events · live stream">
        <PanelMonitorC />
      </CockpitOverlayC>
    </div>
  );
}

window.VariationC = VariationC;
