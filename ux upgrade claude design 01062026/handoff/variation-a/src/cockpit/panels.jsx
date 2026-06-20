// Cockpit instrument panels — Universe, Signals, Ticker detail,
// Audit trace, Policy editor, Monitor stream.
// Each renders inside <CockpitOverlay>. Theme-neutral; inherits CSS vars
// from the variation scope (.vA / .vC).

const DP = window.COCKPIT_DATA;

// ───────── shared bits ───────────────────────────────────────────

function PanelSectionH({ children, sub }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{
        fontSize: 10, letterSpacing: '.18em', textTransform: 'uppercase',
        color: 'var(--amber, var(--pri, #ffb845))', fontWeight: 500,
      }}>{children}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--tx-3, #62748d)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function PanelKV({ k, v, c }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between',
      padding: '6px 0', borderBottom: '1px dashed var(--bd, #1d2c40)',
      fontSize: 12,
    }}>
      <span style={{ color: 'var(--tx-3, #62748d)' }}>{k}</span>
      <span className="mono" style={{ color: c || 'var(--tx, #e6ecf3)' }}>{v}</span>
    </div>
  );
}

function PanelChip({ children, color = 'var(--amber, var(--pri, #ffb845))', filled }) {
  return (
    <span style={{
      fontSize: 9, letterSpacing: '.14em', textTransform: 'uppercase',
      padding: '3px 7px',
      color: filled ? '#0a0e15' : color,
      background: filled ? color : 'transparent',
      border: `1px solid ${color}`, fontWeight: 500,
    }}>{children}</span>
  );
}

// ───────── 1. UNIVERSE / DATA HEALTH ─────────────────────────────

window.PanelUniverse = function() {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 18 }}>
        <UStat l="Universe" big="152" sub="SP100 + QQQ · PIT membership" />
        <UStat l="Ready" big="150" col="var(--green, var(--pos, #5fe49d))" sub="cleared upstream" />
        <UStat l="Blocked" big="2" col="var(--red, var(--neg, #ff6868))" sub="missing CIK / no filings" />
        <UStat l="Refreshed" big="14:30" sub="this cycle, UTC" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 16 }}>
        <div>
          <PanelSectionH sub="last pull · freshness · coverage">Data sources · 9 connected</PanelSectionH>
          <div style={{ border: '1px solid var(--bd, #1d2c40)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 90px 90px 90px',
              gap: 0, padding: '8px 12px', background: 'rgba(0,0,0,.3)',
              fontSize: 9, letterSpacing: '.14em', color: 'var(--tx-3, #62748d)',
              textTransform: 'uppercase', borderBottom: '1px solid var(--bd, #1d2c40)',
            }}>
              <span>Source</span>
              <span>Tier</span>
              <span>State</span>
              <span style={{ textAlign: 'right' }}>Coverage</span>
            </div>
            {DP.sources.map(s => {
              const c = s.state === 'fresh' ? 'var(--green, var(--pos, #5fe49d))'
                      : s.state === 'partial' ? 'var(--amber, var(--warn, #ffb845))'
                      : 'var(--red, var(--neg, #ff6868))';
              return (
                <div key={s.name} style={{
                  display: 'grid', gridTemplateColumns: '1fr 90px 90px 90px',
                  gap: 0, padding: '10px 12px', alignItems: 'center',
                  borderBottom: '1px solid var(--bd, #1d2c40)', fontSize: 12,
                }}>
                  <div>
                    <div style={{ color: 'var(--tx, #e6ecf3)' }}>{s.name}</div>
                    {s.note && <div style={{ fontSize: 10, color: 'var(--tx-3, #62748d)', marginTop: 2 }}>{s.note}</div>}
                  </div>
                  <div><PanelChip color="var(--tx-3, #62748d)">{s.tier}</PanelChip></div>
                  <div>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: c, textTransform: 'uppercase', letterSpacing: '.08em' }}>
                      <span style={{ width: 7, height: 7, borderRadius: '50%', background: c, boxShadow: `0 0 6px ${c}` }} />
                      {s.state}
                    </span>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3, #62748d)' }}>{s.lastPull.split(' ')[1]}</div>
                  </div>
                  <div style={{ textAlign: 'right' }} className="mono">
                    <span style={{ color: 'var(--tx, #e6ecf3)' }}>{s.coverage}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <PanelSectionH sub="blocked from universe">Blocked tickers · 2</PanelSectionH>
          {DP.universeBlocked.map(b => (
            <div key={b.ticker} style={{
              padding: 12, marginBottom: 8,
              border: '1px solid var(--red, var(--neg, #ff6868))',
              background: 'rgba(255,104,104,.06)',
            }}>
              <div className="mono" style={{ fontSize: 15, fontWeight: 600 }}>{b.ticker}</div>
              <div style={{ fontSize: 12, color: 'var(--tx-2, #97a7bc)', marginTop: 4 }}>{b.reason}</div>
              <div style={{ fontSize: 11, color: 'var(--green, var(--pos, #5fe49d))', marginTop: 6 }}>
                → {b.action}
              </div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3, #62748d)', marginTop: 6 }}>
                last attempted {b.attempted}
              </div>
            </div>
          ))}

          <PanelSectionH sub="historical fidelity">PIT integrity</PanelSectionH>
          <div style={{
            padding: 12, border: '1px solid var(--green, var(--pos, #5fe49d))',
            background: 'rgba(95,228,157,.06)',
          }}>
            <div style={{ fontSize: 12, color: 'var(--green, var(--pos, #5fe49d))', fontWeight: 500 }}>
              ✓ Verified
            </div>
            <div style={{ fontSize: 11, color: 'var(--tx-2, #97a7bc)', marginTop: 4, lineHeight: 1.5 }}>
              Membership reconstructed point-in-time. AAPL added 2024-01-12. NFLX exited 2023-08-04 and is excluded for that period. Survivorship handled.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

function UStat({ l, big, sub, col }) {
  return (
    <div style={{
      padding: 12, border: '1px solid var(--bd, #1d2c40)',
      background: 'rgba(255,255,255,.02)',
    }}>
      <div style={{ fontSize: 9, letterSpacing: '.14em', color: 'var(--tx-3, #62748d)', textTransform: 'uppercase' }}>{l}</div>
      <div className="mono" style={{ fontSize: 24, fontWeight: 500, color: col || 'var(--tx, #e6ecf3)', marginTop: 4, letterSpacing: -.5 }}>
        {big}
      </div>
      <div style={{ fontSize: 11, color: 'var(--tx-3, #62748d)', marginTop: 2 }}>{sub}</div>
    </div>
  );
}

// ───────── 2. SIGNALS ────────────────────────────────────────────

window.PanelSignals = function() {
  const [filter, setFilter] = React.useState('all');
  const list = DP.signals.filter(s => filter === 'all' || s.tier === filter);
  const counts = {
    all: DP.signals.length,
    confirmed: DP.signals.filter(s => s.tier === 'confirmed').length,
    inferred: DP.signals.filter(s => s.tier === 'inferred').length,
    suppressed: DP.signals.filter(s => s.tier === 'suppressed').length,
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {['all', 'confirmed', 'inferred', 'suppressed'].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            fontFamily: 'inherit', fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase',
            padding: '7px 12px', cursor: 'pointer',
            border: '1px solid', borderColor: filter === f ? 'var(--amber, var(--pri, #ffb845))' : 'var(--bd, #1d2c40)',
            background: filter === f ? 'rgba(255,184,69,.1)' : 'transparent',
            color: filter === f ? 'var(--amber, var(--pri, #ffb845))' : 'var(--tx-2, #97a7bc)',
          }}>
            {f} · {counts[f]}
          </button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 18 }}>
        <SignalRules
          title="What we treat as evidence"
          rules={[
            { ok: true, t: 'Confirmed', d: 'Official filings (SEC), paid-sub email, sector ETFs — count toward breadth' },
            { ok: true, t: 'Inferred',   d: 'Bar-derived, options-flow, technical — context only · cannot pass alone' },
            { ok: false, t: 'Suppressed', d: 'Below relevance/quality floor (0.35) — logged for audit only' },
          ]}
        />
        <SignalRules
          title="Breadth requirement"
          rules={[
            { ok: true, t: 'Min 2 lanes', d: 'A candidate must have ≥ 2 confirmed evidence lanes' },
            { ok: true, t: 'Independent', d: 'Two news-of-same-event count as 1 lane (dedup)' },
            { ok: true, t: 'PIT-correct',  d: 'Signal must pre-date the cycle clock' },
          ]}
        />
      </div>

      <PanelSectionH sub={`${list.length} signals · click a row for full provenance`}>Signal log · this cycle</PanelSectionH>
      <div style={{ border: '1px solid var(--bd, #1d2c40)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '70px 1fr 1fr 90px 90px 2fr',
          gap: 0, padding: '8px 12px', background: 'rgba(0,0,0,.3)',
          fontSize: 9, letterSpacing: '.14em', color: 'var(--tx-3, #62748d)',
          textTransform: 'uppercase', borderBottom: '1px solid var(--bd, #1d2c40)',
        }}>
          <span>Ticker</span><span>Signal</span><span>Source</span>
          <span>Tier</span><span>Impact</span><span>Detail</span>
        </div>
        {list.map((s, i) => {
          const tierC = s.tier === 'confirmed' ? 'var(--green, var(--pos, #5fe49d))'
                      : s.tier === 'inferred' ? 'var(--amber, var(--warn, #ffb845))'
                      : 'var(--tx-3, #62748d)';
          return (
            <div key={i} style={{
              display: 'grid', gridTemplateColumns: '70px 1fr 1fr 90px 90px 2fr',
              gap: 0, padding: '10px 12px', alignItems: 'center',
              borderBottom: '1px solid var(--bd, #1d2c40)',
              fontSize: 12, opacity: s.tier === 'suppressed' ? .55 : 1,
            }}>
              <span className="mono" style={{ color: 'var(--tx, #e6ecf3)', fontWeight: 500 }}>{s.ticker}</span>
              <span style={{ color: 'var(--tx-2, #97a7bc)' }}>
                {s.negative && <span style={{ color: 'var(--red, var(--neg, #ff6868))', marginRight: 6 }}>▼</span>}
                {s.kind}
              </span>
              <span style={{ color: 'var(--tx-3, #62748d)', fontSize: 11 }}>{s.source}</span>
              <span><PanelChip color={tierC}>{s.tier}</PanelChip></span>
              <span className="mono" style={{
                fontSize: 11,
                color: s.impact === 'high' ? 'var(--tx, #e6ecf3)' : 'var(--tx-3, #62748d)',
              }}>{s.impact}</span>
              <span style={{ color: 'var(--tx-3, #62748d)', fontSize: 11 }}>{s.note}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

function SignalRules({ title, rules }) {
  return (
    <div style={{
      padding: 12, border: '1px solid var(--bd, #1d2c40)',
      background: 'rgba(255,255,255,.02)',
    }}>
      <div style={{ fontSize: 11, color: 'var(--tx, #e6ecf3)', fontWeight: 500, marginBottom: 8 }}>{title}</div>
      {rules.map((r, i) => (
        <div key={i} style={{ display: 'flex', gap: 10, padding: '5px 0', alignItems: 'flex-start' }}>
          <span style={{
            marginTop: 1, fontSize: 10, color: r.ok ? 'var(--green, var(--pos, #5fe49d))' : 'var(--tx-3, #62748d)',
          }}>{r.ok ? '✓' : '○'}</span>
          <div>
            <div style={{ fontSize: 12, color: 'var(--tx, #e6ecf3)' }}>{r.t}</div>
            <div style={{ fontSize: 11, color: 'var(--tx-3, #62748d)', lineHeight: 1.4 }}>{r.d}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ───────── 3. TICKER DETAIL ──────────────────────────────────────

window.PanelTickerDetail = function({ ticker = 'NVDA' }) {
  const c = DP.candidates.find(x => x.ticker === ticker) || DP.candidates[0];
  const v = c.finalConviction;
  const tierC = v >= 0.62 ? 'var(--green, var(--pos, #5fe49d))' : v >= 0.40 ? 'var(--amber, var(--warn, #ffb845))' : 'var(--red, var(--neg, #ff6868))';

  // Synthetic factor breakdown from the original mockup
  const factors = [
    { f: 'Profitability quality', v: 0.91, t: 0.50, pass: true },
    { f: 'Fundamental growth',     v: 0.88, t: 0.40, pass: true },
    { f: 'Valuation',              v: 0.32, t: 0.30, pass: true, warn: true },
    { f: 'Financial strength',     v: 0.79, t: 0.50, pass: true },
    { f: 'Cash efficiency',        v: 0.94, t: 0.50, pass: true },
    { f: 'Earnings stability',     v: 0.81, t: 0.50, pass: true },
  ];

  return (
    <div>
      {/* hero */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1.2fr', gap: 18, marginBottom: 18 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
            <span className="mono" style={{ fontSize: 48, fontWeight: 500, letterSpacing: -1.5, color: 'var(--tx, #e6ecf3)' }}>
              {c.ticker}
            </span>
            <div>
              <div style={{ fontSize: 14, color: 'var(--tx-2, #97a7bc)' }}>{c.name}</div>
              <div style={{ fontSize: 12, color: 'var(--tx-3, #62748d)' }}>{c.sector} · ${c.price.toFixed(2)}</div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 24, marginTop: 18 }}>
            <ScoreBlock l="Det." v={c.detConviction} threshold={0.56} />
            <ScoreBlock l="LLM" v={c.llmConviction} threshold={0.56} />
            <ScoreBlock l="Final" v={c.finalConviction} threshold={0.62} big />
          </div>
        </div>

        <div style={{ padding: 14, border: '1px solid var(--bd, #1d2c40)', background: 'rgba(0,0,0,.25)' }}>
          <PanelSectionH>If approved · order preview</PanelSectionH>
          {c.status === 'approved' ? (
            <>
              <PanelKV k="Side" v={<span style={{ color: 'var(--green, var(--pos, #5fe49d))' }}>BUY · {c.direction.toUpperCase()}</span>} />
              <PanelKV k="Qty" v={`${c.qty} sh`} />
              <PanelKV k="Limit" v={`$${c.price.toFixed(2)}`} />
              <PanelKV k="Notional" v={`$${c.notional.toLocaleString()}`} />
              <PanelKV k="Stop" v={`${c.stopPct}%`} c="var(--red, var(--neg, #ff6868))" />
              <PanelKV k="Target" v={`+${c.targetPct}%`} c="var(--green, var(--pos, #5fe49d))" />
              <PanelKV k="Earnings" v={`${c.earningsDays}d out`} />
              <PanelKV k="Bracket" v="OCO · DAY" />
            </>
          ) : (
            <div style={{ padding: 10, fontSize: 12, color: 'var(--tx-2, #97a7bc)', lineHeight: 1.5 }}>
              <span style={{ color: 'var(--red, var(--neg, #ff6868))' }}>● </span>{c.blocker || 'Not actionable.'}
            </div>
          )}
        </div>
      </div>

      {/* factors */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div>
          <PanelSectionH sub="SEC EDGAR · last filing 2026-04-30">Factor breakdown · fundamentals</PanelSectionH>
          <div style={{ border: '1px solid var(--bd, #1d2c40)' }}>
            {factors.map((f, i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '1fr 60px 60px 80px',
                gap: 8, padding: '8px 12px', alignItems: 'center',
                borderBottom: i < factors.length - 1 ? '1px solid var(--bd, #1d2c40)' : 'none',
                fontSize: 12,
              }}>
                <span style={{ color: 'var(--tx, #e6ecf3)' }}>{f.f}</span>
                <span className="mono" style={{ color: 'var(--tx-3, #62748d)', textAlign: 'right' }}>≥ {f.t.toFixed(2)}</span>
                <span className="mono" style={{ color: f.warn ? 'var(--amber, var(--warn, #ffb845))' : 'var(--tx, #e6ecf3)', textAlign: 'right' }}>
                  {f.v.toFixed(2)}
                </span>
                <span style={{ textAlign: 'right' }}>
                  <PanelChip color={f.warn ? 'var(--amber, var(--warn, #ffb845))' : 'var(--green, var(--pos, #5fe49d))'}>
                    {f.warn ? 'watch' : 'pass'}
                  </PanelChip>
                </span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <PanelSectionH sub="provenance + tier">Evidence pack</PanelSectionH>
          {c.evidence.map((e, i) => (
            <div key={i} style={{
              padding: 10, marginBottom: 8,
              borderLeft: `2px solid ${e.tier === 'confirmed' ? 'var(--green, var(--pos, #5fe49d))' : 'var(--amber, var(--warn, #ffb845))'}`,
              background: 'rgba(255,255,255,.02)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <span style={{
                  fontSize: 9, letterSpacing: '.14em',
                  color: e.tier === 'confirmed' ? 'var(--green, var(--pos, #5fe49d))' : 'var(--amber, var(--warn, #ffb845))',
                  textTransform: 'uppercase',
                }}>{e.tier}</span>
                <span style={{ fontSize: 11, color: 'var(--tx-3, #62748d)' }}>{e.source}</span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--tx, #e6ecf3)', marginTop: 4, lineHeight: 1.5 }}>
                {e.text}
              </div>
            </div>
          ))}

          <PanelSectionH>LLM rationale · gpt-5.4-mini · prompt v2.1</PanelSectionH>
          <div style={{
            padding: 12, fontSize: 12, color: 'var(--tx-2, #97a7bc)', lineHeight: 1.6,
            background: 'rgba(90,215,240,.05)', border: '1px solid rgba(90,215,240,.15)',
            fontStyle: 'italic',
          }}>
            "{c.llmRationale}"
          </div>
        </div>
      </div>

      {/* gates */}
      {c.gates.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <PanelSectionH sub="every gate evaluated">Policy gates</PanelSectionH>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {c.gates.map((g, i) => (
              <div key={i} style={{
                padding: '8px 12px',
                border: `1px solid ${g.ok ? (g.warn ? 'var(--amber, var(--warn, #ffb845))' : 'var(--green, var(--pos, #5fe49d))') : 'var(--red, var(--neg, #ff6868))'}`,
                background: g.ok ? 'rgba(95,228,157,.05)' : 'rgba(255,104,104,.05)',
                fontSize: 12, display: 'flex', justifyContent: 'space-between',
              }}>
                <span style={{ color: 'var(--tx-2, #97a7bc)' }}>
                  <span style={{ color: g.ok ? (g.warn ? 'var(--amber, var(--warn, #ffb845))' : 'var(--green, var(--pos, #5fe49d))') : 'var(--red, var(--neg, #ff6868))', marginRight: 5 }}>
                    {g.ok ? '✓' : '✕'}
                  </span>
                  {g.name}
                </span>
                <span className="mono" style={{ color: 'var(--tx, #e6ecf3)' }}>{g.val}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

function ScoreBlock({ l, v, threshold, big }) {
  const c = v >= threshold ? 'var(--green, var(--pos, #5fe49d))' : v >= threshold - 0.2 ? 'var(--amber, var(--warn, #ffb845))' : 'var(--red, var(--neg, #ff6868))';
  return (
    <div>
      <div style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--tx-3, #62748d)', textTransform: 'uppercase' }}>{l}</div>
      <div className="mono" style={{ fontSize: big ? 36 : 26, color: c, fontWeight: 500, lineHeight: 1, marginTop: 4, letterSpacing: -.5 }}>
        {v.toFixed(2)}
      </div>
      <div className="mono" style={{ fontSize: 10, color: 'var(--tx-3, #62748d)' }}>thr {threshold.toFixed(2)}</div>
    </div>
  );
}

// ───────── 4. AUDIT TRACE (NFLX lifecycle) ───────────────────────

window.PanelAudit = function({ ticker = 'NFLX' }) {
  const trace = DP.auditLifecycle[ticker];
  if (!trace) return (
    <div style={{
      padding: '48px 32px', textAlign: 'center',
      border: '1px dashed var(--bd, #1d2c40)', borderRadius: 3,
      background: 'rgba(255,255,255,.015)',
    }}>
      <div style={{
        width: 40, height: 40, margin: '0 auto 14px',
        borderRadius: '50%', border: '1px solid var(--bd-2, #2a3d57)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--tx-3, #62748d)', fontSize: 20,
      }}>—</div>
      <div className="mono" style={{ fontSize: 16, color: 'var(--tx, #e6ecf3)', fontWeight: 500 }}>{ticker}</div>
      <div style={{ fontSize: 13, color: 'var(--tx-2, #97a7bc)', marginTop: 6, lineHeight: 1.5, maxWidth: 380, marginInline: 'auto' }}>
        No lifecycle trace recorded this cycle. Traces are captured when a candidate changes state mid-cycle (promoted, demoted, blocked, or removed).
      </div>
      {Object.keys(DP.auditLifecycle || {}).length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--tx-3, #62748d)', marginTop: 14 }}>
          Available traces: <span className="mono" style={{ color: 'var(--amber, var(--pri, #ffb845))' }}>
            {Object.keys(DP.auditLifecycle).join(' · ')}
          </span>
        </div>
      )}
    </div>
  );

  return (
    <div>
      <div style={{
        padding: 16, marginBottom: 18,
        background: 'rgba(255,184,69,.06)',
        border: '1px solid var(--amber, var(--pri, #ffb845))',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
          <span className="mono" style={{ fontSize: 24, color: 'var(--tx, #e6ecf3)', fontWeight: 600, letterSpacing: -.5 }}>
            {ticker}
          </span>
          <PanelChip color="var(--amber, var(--pri, #ffb845))" filled>removed mid-cycle</PanelChip>
        </div>
        <div style={{ fontSize: 13, color: 'var(--tx, #e6ecf3)', fontWeight: 500, marginBottom: 4 }}>
          {trace.title}
        </div>
        <div style={{ fontSize: 12, color: 'var(--tx-2, #97a7bc)', lineHeight: 1.5 }}>
          {trace.summary}
        </div>
      </div>

      <PanelSectionH sub="every state transition recorded · click to drill in">Lifecycle trace</PanelSectionH>
      <div style={{ position: 'relative', paddingLeft: 24 }}>
        <div style={{
          position: 'absolute', left: 8, top: 4, bottom: 4, width: 1,
          background: 'var(--bd, #1d2c40)',
        }} />
        {trace.events.map((e, i) => (
          <div key={i} style={{ position: 'relative', paddingBottom: 14 }}>
            <div style={{
              position: 'absolute', left: -22, top: 6,
              width: 11, height: 11, borderRadius: '50%',
              background: e.critical ? 'var(--red, var(--neg, #ff6868))' : 'var(--tx-3, #62748d)',
              boxShadow: e.critical ? '0 0 10px var(--red, var(--neg, #ff6868))' : 'none',
              border: '2px solid var(--bg, #0a1018)',
            }} />
            <div style={{
              display: 'grid', gridTemplateColumns: '60px 1fr', gap: 14,
              padding: '6px 0', alignItems: 'baseline',
            }}>
              <span className="mono" style={{ fontSize: 12, color: e.critical ? 'var(--red, var(--neg, #ff6868))' : 'var(--tx-3, #62748d)' }}>
                {e.t}
              </span>
              <div>
                <div style={{ fontSize: 13, color: 'var(--tx, #e6ecf3)', fontWeight: e.critical ? 600 : 400 }}>
                  {e.state}
                </div>
                <div style={{ fontSize: 11, color: 'var(--tx-2, #97a7bc)', marginTop: 2, lineHeight: 1.5 }}>{e.note}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 18, padding: 12, background: 'rgba(0,0,0,.3)', border: '1px solid var(--bd, #1d2c40)' }}>
        <div style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--tx-3, #62748d)', textTransform: 'uppercase', marginBottom: 6 }}>
          Reproducibility
        </div>
        <div style={{ fontSize: 12, color: 'var(--tx-2, #97a7bc)', lineHeight: 1.5 }}>
          Cycle <span className="mono" style={{ color: 'var(--tx, #e6ecf3)' }}>{DP.cycle.id}</span> · evidence pack hash <span className="mono" style={{ color: 'var(--tx, #e6ecf3)' }}>sha256:b8e1…7a32</span> · all state transitions are deterministic given the same input pack.
        </div>
      </div>
    </div>
  );
};

// ───────── 5. POLICY EDITOR ──────────────────────────────────────

window.PanelPolicy = function() {
  const [pol, setPol] = React.useState(() => {
    const clone = JSON.parse(JSON.stringify(DP.policy));
    return clone;
  });

  const setGate = (key, v) => setPol(p => ({
    ...p,
    convictionGates: p.convictionGates.map(g => g.key === key ? { ...g, v } : g),
  }));
  const setCap = (key, v) => setPol(p => ({
    ...p,
    portfolioCaps: p.portfolioCaps.map(g => g.key === key ? { ...g, v } : g),
  }));
  const setFlag = (key, v) => setPol(p => ({
    ...p,
    flags: p.flags.map(f => f.key === key ? { ...f, v } : f),
  }));

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18 }}>
        <PolicyGroup title="Conviction gates" sub="how good must a candidate be">
          {pol.convictionGates.map(g => (
            <PolicyRow key={g.key} item={g} onChange={v => setGate(g.key, v)} />
          ))}
        </PolicyGroup>
        <PolicyGroup title="Portfolio caps" sub="hard limits the policy will not let you cross">
          {pol.portfolioCaps.map(g => (
            <PolicyRow key={g.key} item={g} onChange={v => setCap(g.key, v)} />
          ))}
        </PolicyGroup>
      </div>

      <PanelSectionH sub="runtime flags · changes require restart for some">Operational flags</PanelSectionH>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {pol.flags.map(f => (
          <div key={f.key} style={{
            padding: 10, border: `1px solid ${f.danger && f.v ? 'var(--red, var(--neg, #ff6868))' : 'var(--bd, #1d2c40)'}`,
            background: f.danger && f.v ? 'rgba(255,104,104,.04)' : 'rgba(255,255,255,.02)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            opacity: f.locked ? .6 : 1,
          }}>
            <div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--tx-3, #62748d)', letterSpacing: '.04em' }}>{f.key}</div>
              <div style={{ fontSize: 12, color: 'var(--tx, #e6ecf3)', marginTop: 2 }}>{f.label}</div>
            </div>
            <PolicyToggle on={f.v} disabled={f.locked} danger={f.danger}
              onClick={() => !f.locked && setFlag(f.key, !f.v)} />
          </div>
        ))}
      </div>

      <div style={{
        marginTop: 18, padding: 14,
        background: 'rgba(255,184,69,.06)', border: '1px solid var(--amber, var(--pri, #ffb845))',
        fontSize: 12, color: 'var(--tx-2, #97a7bc)', lineHeight: 1.5,
      }}>
        <span style={{ color: 'var(--amber, var(--pri, #ffb845))', fontWeight: 600, marginRight: 6 }}>HEADS UP</span>
        Policy changes apply next cycle. Lowering caps mid-cycle does <i>not</i> force-close existing positions — Portfolio Monitor will mark them <code style={{ color: 'var(--tx, #e6ecf3)' }}>review</code> instead.
      </div>
    </div>
  );
};

function PolicyGroup({ title, sub, children }) {
  return (
    <div>
      <PanelSectionH sub={sub}>{title}</PanelSectionH>
      <div style={{ border: '1px solid var(--bd, #1d2c40)', padding: '4px 12px', background: 'rgba(0,0,0,.2)' }}>
        {children}
      </div>
    </div>
  );
}

function PolicyRow({ item, onChange }) {
  return (
    <div style={{ padding: '10px 0', borderBottom: '1px solid var(--bd, #1d2c40)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: 'var(--tx-2, #97a7bc)' }}>{item.label}</span>
        <span className="mono" style={{ fontSize: 13, color: 'var(--tx, #e6ecf3)', fontWeight: 500 }}>
          {typeof item.v === 'number' && item.step < 1 ? item.v.toFixed(2) : item.v}{item.unit}
        </span>
      </div>
      <input type="range" min={item.min} max={item.max} step={item.step}
        value={item.v} onChange={e => onChange(Number(e.target.value))}
        style={{
          width: '100%', accentColor: 'var(--amber, var(--pri, #ffb845))',
          cursor: 'pointer',
        }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--tx-3, #62748d)' }} className="mono">
        <span>{item.min}{item.unit}</span><span>{item.max}{item.unit}</span>
      </div>
    </div>
  );
}

function PolicyToggle({ on, danger, disabled, onClick }) {
  const c = on ? (danger ? 'var(--red, var(--neg, #ff6868))' : 'var(--green, var(--pos, #5fe49d))') : 'var(--tx-3, #62748d)';
  return (
    <button onClick={onClick} disabled={disabled} style={{
      width: 44, height: 22, padding: 2, border: `1px solid ${c}`,
      background: on ? c : 'transparent',
      cursor: disabled ? 'not-allowed' : 'pointer',
      position: 'relative', borderRadius: 2,
    }}>
      <span style={{
        position: 'absolute', top: 2, left: on ? 22 : 2,
        width: 16, height: 14, background: on ? 'rgba(0,0,0,.6)' : c,
        transition: 'left .12s',
      }} />
    </button>
  );
}

// ───────── 6. MONITOR STREAM ─────────────────────────────────────

window.PanelMonitor = function() {
  const [sev, setSev] = React.useState('all');
  const events = DP.monitorEvents.filter(e => sev === 'all' || e.sev === sev);
  const counts = {
    all: DP.monitorEvents.length,
    info: DP.monitorEvents.filter(e => e.sev === 'info').length,
    warn: DP.monitorEvents.filter(e => e.sev === 'warn').length,
    block: DP.monitorEvents.filter(e => e.sev === 'block').length,
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, alignItems: 'center' }}>
        {['all', 'info', 'warn', 'block'].map(f => {
          const fc = f === 'info' ? 'var(--tx-2, #97a7bc)' : f === 'warn' ? 'var(--amber, var(--warn, #ffb845))' : f === 'block' ? 'var(--red, var(--neg, #ff6868))' : 'var(--tx-2, #97a7bc)';
          return (
            <button key={f} onClick={() => setSev(f)} style={{
              fontFamily: 'inherit', fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase',
              padding: '7px 12px', cursor: 'pointer',
              border: '1px solid', borderColor: sev === f ? fc : 'var(--bd, #1d2c40)',
              background: sev === f ? `${fc.replace(')', ', .12)').replace('var(', 'rgba(')}` : 'transparent',
              color: sev === f ? fc : 'var(--tx-3, #62748d)',
            }}>{f} · {counts[f]}</button>
          );
        })}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--tx-3, #62748d)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="cockpit-pulse" style={{
            width: 8, height: 8, borderRadius: '50%', background: 'var(--green, var(--pos, #5fe49d))',
            boxShadow: '0 0 6px var(--green, var(--pos, #5fe49d))',
          }} />
          live stream · {DP.cycle.nextIn} to next cycle
        </span>
      </div>

      <div style={{ border: '1px solid var(--bd, #1d2c40)' }}>
        {events.map((e, i) => {
          const sc = e.sev === 'warn' ? 'var(--amber, var(--warn, #ffb845))' : e.sev === 'block' ? 'var(--red, var(--neg, #ff6868))' : 'var(--tx-3, #62748d)';
          return (
            <div key={i} style={{
              padding: '10px 14px', borderBottom: i < events.length - 1 ? '1px solid var(--bd, #1d2c40)' : 'none',
              display: 'grid', gridTemplateColumns: '90px 10px 1fr 80px',
              gap: 14, alignItems: 'center',
              background: e.sev === 'block' ? 'rgba(255,104,104,.03)' : e.sev === 'warn' ? 'rgba(255,184,69,.03)' : 'transparent',
            }}>
              <span className="mono" style={{ fontSize: 11, color: 'var(--tx-3, #62748d)' }}>{e.t}</span>
              <span style={{
                width: 7, height: 7, borderRadius: '50%', background: sc, boxShadow: `0 0 5px ${sc}`,
              }} />
              <span style={{ fontSize: 12, color: 'var(--tx, #e6ecf3)' }}>{e.msg}</span>
              <span style={{ textAlign: 'right' }}>
                <PanelChip color={sc}>{e.topic}</PanelChip>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
