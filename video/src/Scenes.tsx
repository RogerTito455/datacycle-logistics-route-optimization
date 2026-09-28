// The scenes that are not the map: the KPI, the platform and its pipeline, the comparison, the
// lineage, where the data comes from, the smoke test and the end card.

import type { CSSProperties, ReactNode } from 'react'
import { AbsoluteFill } from 'remotion'
import { CityMap, camAt } from './CityMap'
import { DevChip } from './Chrome'
import { Icon, Mark, Wordmark } from './Icon'
import { beat, line, lineEnd, scene } from './timeline'
import { C, DISPLAY, clamp01, display, ease, easeOut, fade, mono, pop, sp, text } from './theme'

/** An opaque scene: fades in at its start, out after its end while the next arrives. */
function Overlay({ id, f, children, style }: { id: string; f: number; children: ReactNode; style?: CSSProperties }) {
  const s = scene(id)
  if (f < s.start || f >= s.end + 8) return null
  const opacity = Math.min(fade(f - s.start, 8), 1 - fade(f - s.end, 8))
  return <AbsoluteFill style={{ background: C.ground, opacity, ...style }}>{children}</AbsoluteFill>
}

const Grid = ({ f }: { f: number }) => (
  <AbsoluteFill
    style={{
      backgroundImage: `linear-gradient(rgba(36,48,43,0.55) 1px, transparent 1px), linear-gradient(90deg, rgba(36,48,43,0.55) 1px, transparent 1px)`,
      backgroundSize: '64px 64px',
      backgroundPosition: `${-(f * 0.25) % 64}px ${-(f * 0.12) % 64}px`,
    }}
  />
)

function Panel({ children, style, accent }: { children: ReactNode; style?: CSSProperties; accent?: string }) {
  return <div style={{ background: C.panel, border: `1px solid ${accent ?? C.line}`, borderRadius: 14, padding: '18px 22px', boxSizing: 'border-box', ...style }}>{children}</div>
}

const typed = (s: string, t: number, perFrame = 1.4) => s.slice(0, Math.max(0, Math.floor(t * perFrame)))

const Caption = ({ children, color = C.orange }: { children: ReactNode; color?: string }) => <div style={{ ...mono(18, 600, color), letterSpacing: 1.5, textTransform: 'uppercase' }}>{children}</div>

// ── 02 · One number ──────────────────────────────────────────────────────────

const ROUTE_X0 = 250
const ROUTE_X1 = 1670
const ROUTE_Y = 430

export function Kpi({ f }: { f: number }) {
  const s = scene('kpi')
  const title = beat('kpi-0', 'one')
  const named = beat('kpi-0', 'average')
  const from = beat('kpi-1', 'moment')
  const last = beat('kpi-1', 'last')
  const six = beat('kpi-2', 'six')
  const target = beat('kpi-2', 'target')
  const draw = easeOut((f - from + 4) / (last - from + 10))
  const van = ease((f - from) / (last - from + 14))
  const stops = 12
  return (
    <Overlay id="kpi" f={f}>
      <Grid f={f} />
      <div style={{ position: 'absolute', left: 90, top: 140 }}>
        <div style={pop(f - s.start - 4)}>
          <Caption>The one number the company measures</Caption>
        </div>
        <div style={{ ...display(96), marginTop: 12, ...pop(f - title) }}>Average delivery time per route</div>
        <div style={{ height: 5, marginTop: 14, borderRadius: 3, background: C.orange, width: `${ease((f - named) / 18) * 100}%` }} />
      </div>

      {/* One route, from the hub to its last stop. */}
      <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0 }}>
        <line x1={ROUTE_X0} y1={ROUTE_Y} x2={ROUTE_X1} y2={ROUTE_Y} stroke={C.line} strokeWidth={6} strokeLinecap="round" opacity={fade(f - named - 6, 10)} />
        {draw > 0.002 && <line x1={ROUTE_X0} y1={ROUTE_Y} x2={ROUTE_X0 + (ROUTE_X1 - ROUTE_X0) * draw} y2={ROUTE_Y} stroke={C.orange} strokeWidth={6} strokeLinecap="round" />}
        {Array.from({ length: stops }, (_, i) => {
          const x = ROUTE_X0 + ((ROUTE_X1 - ROUTE_X0) * (i + 1)) / (stops + 1)
          const done = van >= (i + 1) / (stops + 1)
          return <circle key={i} cx={x} cy={ROUTE_Y} r={9} fill={done ? C.ink : C.ground} stroke={done ? C.ink : C.muted} strokeWidth={2.5} opacity={fade(f - named - 6 - i, 6)} />
        })}
      </svg>
      <div style={{ position: 'absolute', left: ROUTE_X0 - 26, top: ROUTE_Y - 26, opacity: fade(f - named - 6, 8) }}>
        <div style={{ width: 52, height: 52, borderRadius: 12, background: C.panel, border: `2px solid ${C.orange}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Mark size={30} stroke={4} />
        </div>
      </div>
      <div style={{ position: 'absolute', left: ROUTE_X1 - 26, top: ROUTE_Y - 26, opacity: fade(f - named - 18, 8) }}>
        <div style={{ width: 52, height: 52, borderRadius: 26, background: C.panel, border: `2px solid ${C.ink}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="parcel" size={28} color={C.ink} />
        </div>
      </div>
      {f >= from - 10 && (
        <div style={{ position: 'absolute', left: ROUTE_X0 + (ROUTE_X1 - ROUTE_X0) * van - 24, top: ROUTE_Y - 78, opacity: fade(f - from + 6, 6) * (1 - fade(f - last - 20, 8)) }}>
          <Icon name="van" size={48} color={C.ink} />
        </div>
      )}
      <div style={{ position: 'absolute', left: ROUTE_X0 - 30, top: ROUTE_Y + 44, ...pop(f - from) }}>
        <div style={mono(24, 600, C.orange)}>departed_at</div>
        <div style={text(22, 500, C.muted)}>leaves the hub geofence</div>
      </div>
      <div style={{ position: 'absolute', right: 1920 - ROUTE_X1 - 30, top: ROUTE_Y + 44, textAlign: 'right', ...pop(f - last) }}>
        <div style={mono(24, 600, C.orange)}>delivered_at</div>
        <div style={text(22, 500, C.muted)}>last stop of the route</div>
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: ROUTE_Y + 124, textAlign: 'center', ...mono(22, 500, C.ink), ...pop(f - last - 12) }}>
        route_duration = delivered_at − departed_at <span style={{ color: C.muted }}>· averaged over the day's routes</span>
      </div>

      {/* The company's baseline and target: not results. */}
      <div style={{ position: 'absolute', left: 0, right: 0, top: 616, display: 'flex', justifyContent: 'center', gap: 36 }}>
        <div style={pop(f - six)}>
          <Panel style={{ width: 640, padding: '18px 30px' }}>
            <div style={mono(18, 600, C.muted)}>BASELINE · TODAY</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 18, whiteSpace: 'nowrap' }}>
              <span style={{ ...display(140), textTransform: 'none', lineHeight: 1 }}>6 h 01</span>
              <span style={mono(22, 500, C.muted)}>361 min</span>
            </div>
          </Panel>
        </div>
        <div style={pop(f - target)}>
          <Panel style={{ width: 640, padding: '18px 30px' }} accent={C.orange}>
            <div style={mono(18, 600, C.orange)}>TARGET</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 18, whiteSpace: 'nowrap' }}>
              <span style={{ ...display(140, C.orange), textTransform: 'none', lineHeight: 1 }}>5 h 30</span>
              <span style={mono(22, 500, C.muted)}>330 min · −31 min</span>
            </div>
          </Panel>
        </div>
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 852, textAlign: 'center', ...mono(17, 500, C.muted), opacity: fade(f - target - 10, 10) }}>
        The company's own baseline and target, from its profile. Not a result of this platform.
      </div>
    </Overlay>
  )
}

// ── 03 · The platform ────────────────────────────────────────────────────────

export function Brand({ f }: { f: number }) {
  const s = scene('brand')
  const t = f - s.start
  const k = sp(t - 4, 16, 140)
  return (
    <Overlay id="brand" f={f}>
      <Grid f={f} />
      <AbsoluteFill style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', paddingBottom: 90 }}>
        <div style={{ opacity: clamp01(k * 1.5), transform: `scale(${0.8 + 0.2 * Math.min(1.02, k)})` }}>
          <Mark size={170} stroke={3.2} />
        </div>
        <div style={{ ...display(150), marginTop: 26, ...pop(t - 10) }}>
          <Wordmark size={150} />
        </div>
        <div style={{ ...mono(30, 500, C.muted), marginTop: 18, ...pop(t - 22) }}>{typed('The data platform behind the number, end to end.', t - 26, 1.8)}</div>
      </AbsoluteFill>
    </Overlay>
  )
}

const STAGES = ['Generation', 'Ingestion', 'Storage', 'Processing', 'Analysis', 'Action', 'Archiving']
const COL_W = 236
const COL_GAP = 20
const colX = (i: number) => 74 + i * (COL_W + COL_GAP)
const CARD_W = 222
const cardX = (i: number) => colX(i) + (COL_W - CARD_W) / 2
const STREAM_Y = 250
const BATCH_Y = [446, 536, 626]
const MAIN_Y = 400
const STORE = { top: 250, bottom: 600 }

function StageCard({ x, y, w = CARD_W, h, icon, title, sub, at, f, color = C.ink, accent, children }: { x: number; y: number; w?: number; h: number; icon: string; title: string; sub: string; at: number; f: number; color?: string; accent?: string; children?: ReactNode }) {
  if (f < at - 1) return null
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: w, height: h, ...pop(f - at) }}>
      <div style={{ height: '100%', boxSizing: 'border-box', borderRadius: 12, background: C.panel, border: `1.5px solid ${accent ?? C.line}`, padding: '12px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon name={icon} size={22} color={color} />
          <span style={text(25, 600)}>{title}</span>
        </div>
        <div style={{ ...mono(14, 500, C.muted), marginTop: 6, lineHeight: 1.35 }}>{sub}</div>
        {children}
      </div>
    </div>
  )
}

export function Pipeline({ f }: { f: number }) {
  const s = scene('pipeline')
  const B = {
    gps: beat('pipeline-0', 'position'),
    stream: beat('pipeline-0', 'five'),
    traffic: beat('pipeline-1', 'roads'),
    weather: beat('pipeline-1', 'weather'),
    fast: line('pipeline-2').at,
    redpanda: beat('pipeline-2', 'redpanda'),
    slow: beat('pipeline-2', 'slow'),
    batches: beat('pipeline-2', 'batches'),
    both: line('pipeline-3').at,
    tsdb: beat('pipeline-3', 'timescaledb'),
    raw: beat('pipeline-3', 'raw'),
    dbt: beat('pipeline-3', 'dbt'),
    kpi: beat('pipeline-3', 'kpi'),
    dagster: beat('pipeline-4', 'dagster'),
    grafana: beat('pipeline-4', 'grafana'),
    live: beat('pipeline-4', 'live'),
  }
  const zoom = ease((f - B.live - 6) / 20)
  return (
    <Overlay id="pipeline" f={f}>
      <Grid f={f} />
      <AbsoluteFill style={{ opacity: 1 - zoom, transform: `scale(${1 - 0.06 * zoom})` }}>
        {/* The seven stages of the data lifecycle, left to right. */}
        {STAGES.map((name, i) => (
          <div key={name} style={{ position: 'absolute', left: colX(i), top: 140, width: COL_W, ...pop(f - s.start - 2 - i * 3) }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              <span style={mono(17, 600, C.orange)}>{String(i + 1).padStart(2, '0')}</span>
              <span style={text(24, 600, C.ink)}>{name}</span>
            </div>
            <div style={{ height: 1, background: C.line, marginTop: 10 }} />
          </div>
        ))}
        {STAGES.map((name, i) => (
          <div key={`col${name}`} style={{ position: 'absolute', left: colX(i), top: 196, width: COL_W, height: 560, borderRadius: 10, background: 'rgba(21,30,27,0.35)', opacity: fade(f - s.start - 2 - i * 3, 10) }} />
        ))}

        <Flows f={f} B={B} />

        {/* Generation */}
        <StageCard f={f} at={B.gps} x={cardX(0)} y={STREAM_Y} h={110} icon="signal" color={C.blue} title="GPS pings" sub="every van · every 5 s" accent="rgba(91,155,230,0.6)" />
        {f >= B.gps && (
          <div style={{ position: 'absolute', left: cardX(0), top: STREAM_Y + 118, ...pop(f - B.gps - 6) }}>
            <DevChip milestone="M2" size={13} />
          </div>
        )}
        <StageCard f={f} at={B.traffic} x={cardX(0)} y={BATCH_Y[0]} h={80} icon="road" title="Traffic" sub="Open Data BCN · 5 min" />
        <StageCard f={f} at={B.weather} x={cardX(0)} y={BATCH_Y[1]} h={80} icon="cloud" title="Weather" sub="Open-Meteo · hourly" />
        <StageCard f={f} at={B.weather + 12} x={cardX(0)} y={BATCH_Y[2]} h={80} icon="sparkle" title="Company" sub="AI-generated · daily" />

        {/* Ingestion */}
        <StageCard f={f} at={B.redpanda} x={cardX(1)} y={STREAM_Y} h={110} icon="stream" color={C.blue} title="Redpanda" sub="Kafka API · gps.pings" accent="rgba(91,155,230,0.6)" />
        <StageCard f={f} at={B.batches} x={cardX(1)} y={BATCH_Y[0] + 45} h={100} icon="batch" title="Loaders" sub="batches: every 5 min, hourly, nightly" />

        {/* Storage: raw first */}
        <StageCard f={f} at={B.tsdb} x={cardX(2)} y={STORE.top} h={STORE.bottom - STORE.top} icon="database" title="TimescaleDB" sub="PostgreSQL + time series">
          <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              ['bronze', 'raw', B.raw],
              ['silver', 'cleaned', B.dbt],
              ['gold', 'the KPI', B.kpi],
            ].map(([layer, what, t]) => (
              <div key={layer as string} style={{ padding: '8px 10px', borderRadius: 8, border: `1px solid ${f >= (t as number) ? C.muted : C.line}`, opacity: 0.35 + 0.65 * fade(f - (t as number), 8) }}>
                <div style={mono(15, 600, f >= (t as number) ? C.ink : C.muted)}>{layer as string}</div>
                <div style={mono(13.5, 500, C.muted)}>{what as string}</div>
              </div>
            ))}
            <div style={{ ...mono(13, 500, C.faint), marginTop: 4, opacity: fade(f - B.raw, 8) }}>raw files: RustFS (S3)</div>
          </div>
        </StageCard>

        {/* Processing, analysis, action, archiving */}
        <StageCard f={f} at={B.dbt} x={cardX(3)} y={MAIN_Y - 60} h={120} icon="layers" title="dbt" sub="bronze → silver → gold, tested models" />
        <StageCard f={f} at={B.kpi} x={cardX(4)} y={MAIN_Y - 60} h={120} icon="gauge" color={C.orange} title="KPI" sub="avg delivery time per route" accent="rgba(242,112,58,0.7)" />
        <StageCard f={f} at={B.grafana} x={cardX(4)} y={MAIN_Y + 90} h={100} icon="map" title="Grafana" sub="live dashboard" />
        <StageCard f={f} at={B.kpi + 12} x={cardX(5)} y={MAIN_Y - 60} h={120} icon="route" color={C.orange} title="Optimizer" sub="OR-Tools on OSRM road times" />
        {f >= B.kpi + 12 && (
          <div style={{ position: 'absolute', left: cardX(5), top: MAIN_Y + 68, ...pop(f - B.kpi - 18) }}>
            <DevChip milestone="M3" size={13} />
          </div>
        )}
        <StageCard f={f} at={B.kpi + 22} x={cardX(6)} y={MAIN_Y - 60} h={120} icon="archive" title="RustFS" sub="archive, with retention rules" />

        {/* What the two lanes are. */}
        <div style={{ position: 'absolute', left: colX(0) + 4, top: 736, display: 'flex', gap: 30, ...mono(15, 500, C.muted) }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 10, opacity: fade(f - B.fast, 8) }}>
            <svg width={40} height={10}>
              <line x1={2} y1={5} x2={38} y2={5} stroke={C.blue} strokeOpacity={0.4} strokeWidth={3} />
              <circle cx={12} cy={5} r={4} fill={C.blue} />
              <circle cx={28} cy={5} r={4} fill={C.blue} />
            </svg>
            <span style={{ color: C.blue }}>stream · fast signals</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 10, opacity: fade(f - B.slow, 8) }}>
            <svg width={40} height={10}>
              <line x1={2} y1={5} x2={38} y2={5} stroke={C.muted} strokeWidth={2} strokeDasharray="5 6" />
              <rect x={14} y={0} width={14} height={10} rx={2} fill={C.ink} opacity={0.8} />
            </svg>
            batch · slow signals
          </span>
        </div>

        {/* Dagster runs every step on schedule. */}
        {f >= B.dagster - 1 && (
          <div style={{ position: 'absolute', left: colX(1), top: 790, width: colX(6) + COL_W - colX(1), ...pop(f - B.dagster) }}>
            <div style={{ height: 58, borderRadius: 12, border: `1.5px dashed ${C.muted}`, background: C.panel, display: 'flex', alignItems: 'center', gap: 14, padding: '0 20px' }}>
              <Icon name="clock" size={24} color={C.ink} />
              <span style={text(25, 600)}>Dagster</span>
              <span style={mono(16, 500, C.muted)}>schedules and runs every step, with its run history</span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                {Array.from({ length: 14 }, (_, i) => (
                  <span key={i} style={{ width: 10, height: 22, borderRadius: 3, background: C.green, opacity: fade(f - B.dagster - 6 - i * 1.5, 4) * 0.85 }} />
                ))}
              </div>
            </div>
          </div>
        )}
      </AbsoluteFill>
      {zoom > 0 && <Dashboard f={f} k={zoom} at={B.live} />}
    </Overlay>
  )
}

type Beats = Record<string, number>

/** The lanes: GPS streams fast (blue particles), the rest arrives in slow batches (dashed pulses). */
function Flows({ f, B }: { f: number; B: Beats }) {
  const streamY = STREAM_Y + 55
  const batchY = BATCH_Y[0] + 95
  const x0 = cardX(0) + CARD_W
  const storeX = cardX(2)
  const streamLen = storeX - x0
  const streamOn = fade(f - B.stream, 8)
  const toStore = ease((f - B.both) / 16)
  // How far the stream has got: to the ingestion column, through Redpanda, then on to storage.
  const reach = cardX(1) - x0 + (f >= B.redpanda ? CARD_W : 0) + (storeX - cardX(1) - CARD_W) * toStore
  const mainOn = ease((f - B.dbt + 6) / 20)
  const batchOn = fade(f - B.batches, 8)
  return (
    <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0 }}>
      {/* Streaming lane */}
      {streamOn > 0 && (
        <g opacity={streamOn}>
          <line x1={x0} y1={streamY} x2={x0 + reach} y2={streamY} stroke={C.blue} strokeOpacity={0.35} strokeWidth={3} />
          {Array.from({ length: 14 }, (_, i) => {
            const x = (f * 9 + i * 34) % streamLen
            if (x > reach) return null
            return <circle key={i} cx={x0 + x} cy={streamY} r={4} fill={C.blue} />
          })}
        </g>
      )}
      {/* Batch lane: from the three sources into the loaders, then on to storage. */}
      {f >= B.traffic && (
        <g>
          {BATCH_Y.map((y, i) => {
            const on = fade(f - (i === 0 ? B.traffic : i === 1 ? B.weather : B.weather + 12), 8) * (f >= B.batches ? 1 : 0.5)
            const x1 = x0
            const y1 = y + 40
            const x2 = cardX(1)
            const d = `M ${x1} ${y1} C ${x1 + 24} ${y1}, ${x2 - 24} ${batchY}, ${x2} ${batchY}`
            return <path key={i} d={d} fill="none" stroke={C.muted} strokeOpacity={0.6 * on} strokeWidth={2} strokeDasharray="5 6" />
          })}
          {batchOn > 0 && (
            <>
              <line x1={cardX(1) + CARD_W} y1={batchY} x2={cardX(1) + CARD_W + (storeX - cardX(1) - CARD_W) * toStore} y2={batchY} stroke={C.muted} strokeOpacity={0.6} strokeWidth={2} strokeDasharray="5 6" />
              {[0, 1].map((i) => {
                const k = ((f - B.batches + i * 45) % 90) / 90
                const x = cardX(1) + CARD_W + (storeX - cardX(1) - CARD_W) * k
                return toStore > k ? <rect key={i} x={x - 8} y={batchY - 5} width={16} height={10} rx={2} fill={C.ink} opacity={0.8 * Math.sin(Math.PI * k)} /> : null
              })}
            </>
          )}
        </g>
      )}
      {/* The main line: storage, processing, the KPI, action, archive. */}
      {mainOn > 0 && (
        <g>
          <line x1={cardX(2) + CARD_W} y1={MAIN_Y} x2={cardX(2) + CARD_W + (cardX(6) - cardX(2) - CARD_W) * mainOn} y2={MAIN_Y} stroke={C.ink} strokeOpacity={0.3} strokeWidth={3} />
          {Array.from({ length: 10 }, (_, i) => {
            const span = cardX(6) - cardX(2) - CARD_W
            const x = (f * 3 + i * (span / 10)) % span
            return x < span * mainOn ? <circle key={i} cx={cardX(2) + CARD_W + x} cy={MAIN_Y} r={3.5} fill={C.ink} opacity={0.7} /> : null
          })}
          {f >= B.grafana && <line x1={cardX(4) + CARD_W / 2} y1={MAIN_Y + 60} x2={cardX(4) + CARD_W / 2} y2={MAIN_Y + 60 + 30 * fade(f - B.grafana, 8)} stroke={C.ink} strokeOpacity={0.3} strokeWidth={3} />}
        </g>
      )}
      {/* Dagster's reach: every stage but generation. */}
      {f >= B.dagster &&
        [1, 2, 3, 4, 5, 6].map((i) => {
          const k = ease((f - B.dagster - i * 2) / 12)
          const x = colX(i) + COL_W / 2
          const top = i === 2 ? STORE.bottom : i === 1 ? BATCH_Y[0] + 145 : i === 4 ? MAIN_Y + 190 : MAIN_Y + 60
          return <line key={i} x1={x} y1={790} x2={x} y2={790 - (790 - top) * k} stroke={C.muted} strokeOpacity={0.5} strokeWidth={1.5} strokeDasharray="3 5" />
        })}
    </svg>
  )
}

/** The live KPI panel, drawn in the dashboard's style. The KPI and the live map arrive at M2. */
function Dashboard({ f, k, at }: { f: number; k: number; at: number }) {
  const from = { x: cardX(4), y: MAIN_Y + 90, w: CARD_W, h: 100 }
  const to = { x: 200, y: 150, w: 1520, h: 720 }
  const r = { x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k, w: from.w + (to.w - from.w) * k, h: from.h + (to.h - from.h) * k }
  const inner = fade(f - at - 20, 10)
  const stat = (label: string, value: ReactNode, note: string, delay: number, accent: string = C.ink) => (
    <div style={{ background: C.ground, border: `1px solid ${C.line}`, borderRadius: 8, padding: '14px 18px', opacity: fade(f - at - 22 - delay, 8) }}>
      <div style={mono(15, 500, C.muted)}>{label}</div>
      <div style={{ ...display(76, accent), textTransform: 'none', lineHeight: 1.05, marginTop: 6, whiteSpace: 'nowrap' }}>{value}</div>
      <div style={mono(14, 500, C.faint)}>{note}</div>
    </div>
  )
  return (
    <div style={{ position: 'absolute', left: r.x, top: r.y, width: r.w, height: r.h, borderRadius: 14, background: C.panel, border: `1.5px solid ${C.line}`, overflow: 'hidden', boxShadow: '0 30px 80px rgba(0,0,0,0.5)' }}>
      <div style={{ opacity: inner, padding: '16px 22px', height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Icon name="map" size={22} color={C.ink} />
          <span style={text(24, 600)}>Operations · live</span>
          <span style={mono(15, 500, C.muted)}>Grafana · refresh 5 s</span>
          <span style={{ marginLeft: 'auto' }}>
            <DevChip milestone="M2" size={14} />
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1.35fr 1fr 1fr', gap: 14 }}>
          {stat(
            'Avg delivery time per route',
            <span>
              6 h 01 <span style={{ fontSize: 34, color: C.orange }}>→ 5 h 30</span>
            </span>,
            'baseline → target · company profile',
            0,
          )}
          {stat('Vans on the road', '30', 'morning wave · simulated', 3)}
          {stat('GPS pings per second', '6', '30 vans, one ping every 5 s', 6, C.blue)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1.9fr 1fr', gap: 14, flex: 1, minHeight: 0 }}>
          <div style={{ position: 'relative', borderRadius: 8, border: `1px solid ${C.line}`, overflow: 'hidden', opacity: fade(f - at - 30, 8) }}>
            <div style={{ position: 'absolute', left: 0, top: 0, width: 1920, height: 1080, transform: 'scale(0.47)', transformOrigin: '0 0' }}>
              <CityMap cam={camAt(2.125, 41.382, 62)} clock={690 + (f - at) * 0.2} f={f} vans={1} trails={0.5} offsetY={-60} offsetX={-90} />
            </div>
            <div style={{ position: 'absolute', left: 12, top: 10, ...mono(14, 500, C.muted) }}>Fleet · positions every 5 s</div>
          </div>
          <div style={{ borderRadius: 8, border: `1px solid ${C.line}`, background: C.ground, padding: '14px 18px', opacity: fade(f - at - 34, 8) }}>
            <div style={mono(15, 500, C.muted)}>Freshness</div>
            {[
              ['gps.pings', 'every 5 s', C.blue],
              ['traffic_state', 'every 5 min', C.ink],
              ['weather', 'hourly', C.ink],
              ['orders', 'daily batch', C.ink],
              ['route_history', 'nightly', C.ink],
            ].map(([name, every, color]) => (
              <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14 }}>
                <span style={{ width: 10, height: 10, borderRadius: 5, background: C.green }} />
                <span style={mono(18, 500, color)}>{name}</span>
                <span style={{ ...mono(15, 500, C.muted), marginLeft: 'auto' }}>{every}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 05 · Why not a map app ───────────────────────────────────────────────────

const ROWS: [string, string, string, string, string, number?][] = [
  ['Scope', 'One trip: from one address to the next', 'The day of a whole fleet: 30 vans, 3,500 parcels', 'compare-0', 'fastest'],
  ['Who carries each parcel', 'Not its question', 'Assigns every parcel to a van', 'compare-1', 'which'],
  ['Delivery windows', 'Not something it knows', 'Keeps every stop inside its 2-hour window', 'compare-1', 'two-hour'],
  ['When a van runs late', 'Re-routes that one driver', 'Moves stops from a late van to an early one', 'compare-1', 'move'],
  ['Did it work?', 'No record of your routes', 'Measures every route, every day: the KPI', 'compare-2', 'yesterday'],
]

export function Compare({ f }: { f: number }) {
  const s = scene('compare')
  const head = beat('compare-0', 'navigation')
  const ours = beat('compare-3', 'fleet')
  const measure = beat('compare-3', 'measure')
  return (
    <Overlay id="compare" f={f}>
      <Grid f={f} />
      <div style={{ position: 'absolute', left: 90, top: 138, ...pop(f - s.start) }}>
        <Caption>Planning a fleet is not navigating a car</Caption>
      </div>
      <div style={{ position: 'absolute', left: 90, right: 90, top: 196 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr 1fr', columnGap: 22, rowGap: 12, alignItems: 'stretch' }}>
          <div />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 22px', ...pop(f - head) }}>
            <Icon name="route" size={28} color={C.muted} />
            <span style={text(28, 600, C.muted)}>A navigation app</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 22px', borderRadius: 12, background: 'rgba(242,112,58,0.12)', border: `1.5px solid ${C.orange}`, ...pop(f - head - 4) }}>
            <Mark size={28} stroke={4} />
            <span style={{ fontFamily: DISPLAY, fontWeight: 800, fontSize: 32, letterSpacing: 1, color: C.ink, fontVariationSettings: "'opsz' 72", lineHeight: 1 }}>
              LLOBREGAT <span style={{ color: C.orange }}>EXPRESS</span>
            </span>
            <span style={{ marginLeft: 'auto' }}>
              <DevChip milestone="M2/M3" size={13} />
            </span>
          </div>
          {ROWS.map(([what, app, us, id, word], i) => {
            const t = f - beat(id, word) + 2
            const lit = f >= ours
            return [
              <div key={`w${i}`} style={{ ...text(26, 600, C.ink), padding: '20px 0', ...pop(t) }}>{what}</div>,
              <div key={`a${i}`} style={{ ...text(26, 500, C.muted), padding: '18px 22px', borderRadius: 12, border: `1px solid ${C.line}`, display: 'flex', alignItems: 'center', ...pop(t) }}>
                {app}
              </div>,
              <div key={`o${i}`} style={{ ...text(26, 600, C.ink), padding: '18px 22px', borderRadius: 12, border: `1.5px solid ${lit || (i === 4 && f >= measure) ? C.orange : 'rgba(242,112,58,0.35)'}`, background: lit ? 'rgba(242,112,58,0.10)' : C.panel, display: 'flex', alignItems: 'center', gap: 12, ...pop(t + 4) }}>
                <Icon name="check" size={24} color={C.orange} stroke={2.6} />
                {us}
              </div>,
            ]
          })}
        </div>
      </div>
    </Overlay>
  )
}

// ── 06 · Built to be checked ─────────────────────────────────────────────────

const CHAIN: [string, string][] = [
  ['gps.pings', 'Redpanda topic'],
  ['bronze.gps_pings', 'bronze · raw'],
  ['stg_gps_pings', 'silver · staging'],
  ['int_route_legs', 'silver · joined'],
  ['fct_route_legs', 'gold · fact'],
  ['kpi_avg_delivery_time_per_route', 'gold · the KPI'],
  ['dashboard', 'Grafana'],
]

export function Lineage({ f }: { f: number }) {
  const s = scene('lineage')
  const source = beat('lineage-0', 'source')
  const owns = beat('lineage-0', 'owns')
  const arrived = beat('lineage-0', 'arrived')
  const t = f - s.start
  // The chain draws from the dashboard back to the source: every number traces back.
  const back = (i: number) => ease((f - line('lineage-0').at - (CHAIN.length - 1 - i) * 4) / 10)
  return (
    <Overlay id="lineage" f={f}>
      <Grid f={f} />
      <div style={{ position: 'absolute', left: 90, top: 138, ...pop(t) }}>
        <Caption>Lineage · from the KPI back to the ping</Caption>
      </div>
      <div style={{ position: 'absolute', left: 40, right: 40, top: 230, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', gap: 0 }}>
        {CHAIN.map(([name, layer], i) => (
          <div key={name} style={{ display: 'flex', alignItems: 'flex-start' }}>
            <div style={{ opacity: back(i), transform: `translateY(${(1 - back(i)) * 12}px)` }}>
              <div style={{ ...mono(14, 500, i === 5 ? C.orange : C.muted), marginBottom: 6, whiteSpace: 'nowrap' }}>{layer}</div>
              <div style={{ padding: '13px 14px', borderRadius: 10, background: C.panel, border: `1.5px solid ${i === 5 ? C.orange : i === 0 ? C.blue : C.line}`, ...mono(19, 600, C.ink), whiteSpace: 'nowrap' }}>{name}</div>
            </div>
            {i < CHAIN.length - 1 && (
              <div style={{ width: 30, height: 46, marginTop: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: back(i + 1) }}>
                <Icon name="arrow" size={20} color={C.muted} />
              </div>
            )}
          </div>
        ))}
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 392, textAlign: 'center', ...mono(18, 500, C.muted), opacity: fade(f - source - 6, 10) }}>
        On every table and file, the same three metadata elements:
      </div>
      <div style={{ position: 'absolute', left: 130, right: 130, top: 446, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 28 }}>
        {(
          [
            [source, 'Where it came from', [['source', 'gps-simulator · OSM roads (ODbL)']]],
            [arrived, 'When it happened, and when it arrived', [['event_time', '2026-10-06 11:04:35'], ['ingested_at', '2026-10-06 11:04:36']]],
            [owns, 'Who owns it, in which shape', [['owner', 'ingestion'], ['schema_version', '1']]],
          ] as [number, string, [string, string][]][]
        ).map(([at, title, fields]) => (
          <div key={title} style={pop(f - at)}>
            <Panel style={{ height: 262, padding: '22px 26px' }}>
              <div style={text(28, 600)}>{title}</div>
              <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
                {fields.map(([k, v]) => (
                  <div key={k}>
                    <div style={mono(20, 600, C.orange)}>{k}</div>
                    <div style={mono(21, 500, C.ink)}>{v}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        ))}
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 750, textAlign: 'center', ...mono(18, 500, C.muted), opacity: fade(f - arrived - 10, 10) }}>
        dbt writes them on every model; Dagster shows them on every asset.
      </div>
    </Overlay>
  )
}

export function Origins({ f }: { f: number }) {
  const s = scene('origins')
  const items0 = [beat('origins-0', 'traffic'), beat('origins-0', 'weather'), beat('origins-0', 'roads')]
  const ai = beat('origins-1', 'company')
  const prompt = beat('origins-1', 'prompt')
  const checked = beat('origins-1', 'checked')
  // The three origins are set out at the start; the simulated one fills in once the voice is done.
  const sim = s.start + 22
  const simItems = lineEnd('origins-1') - 24
  const col = (at: number, color: string, icon: string, title: string, children: ReactNode, extra?: ReactNode) => (
    <div style={pop(f - at)}>
      <Panel style={{ height: 470, borderColor: color, padding: '26px 28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 52, height: 52, borderRadius: 26, border: `2px solid ${color}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name={icon} size={28} color={color} />
          </div>
          <span style={{ ...display(40, C.ink), whiteSpace: 'nowrap' }}>{title}</span>
        </div>
        <div style={{ marginTop: 30, display: 'flex', flexDirection: 'column', gap: 24 }}>{children}</div>
        {extra}
      </Panel>
    </div>
  )
  const item = (at: number, head: string, sub: string, color = C.ink) => (
    <div style={{ opacity: fade(f - at, 8), transform: `translateX(${(1 - fade(f - at, 8)) * -10}px)` }}>
      <div style={text(28, 600, color)}>{head}</div>
      <div style={mono(17, 500, C.muted)}>{sub}</div>
    </div>
  )
  return (
    <Overlay id="origins" f={f}>
      <Grid f={f} />
      <div style={{ position: 'absolute', left: 90, top: 138, ...pop(f - s.start) }}>
        <Caption>Where every dataset comes from</Caption>
      </div>
      <div style={{ position: 'absolute', left: 90, right: 90, top: 214, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 28 }}>
        {col(
          s.start + 6,
          C.green,
          'globe',
          'Real open data',
          <>
            {item(items0[0], 'Traffic state', 'Open Data BCN · CC BY 4.0 · every 5 min')}
            {item(items0[1], 'Weather', 'Open-Meteo · CC BY 4.0 · hourly')}
            {item(items0[2], 'Roads', 'OpenStreetMap · ODbL · via OSRM')}
          </>,
        )}
        {col(
          s.start + 14,
          C.ink,
          'sparkle',
          'Generated with AI',
          <>
            {item(ai + 4, 'The company', 'profile, fleet, drivers, orders, history')}
            {item(prompt, 'Every prompt published', 'prompts/001-company-profile.md, …')}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, opacity: fade(f - checked, 8) }}>
              <Icon name="check" size={26} color={C.green} stroke={2.6} />
              <div>
                <div style={text(28, 600)}>Checked against the real map</div>
                <div style={mono(17, 500, C.muted)}>validate_company.py · OSM, OSRM</div>
              </div>
            </div>
          </>,
        )}
        {col(
          sim,
          C.amber,
          'van',
          'Simulated on real roads',
          <>
            {item(simItems, 'GPS pings', 'each van along its OSRM route')}
            {item(simItems + 8, 'Telemetry and deliveries', 'door sensors, scans, battery')}
            {item(simItems + 16, 'Slowed by the real traffic', 'the live Open Data BCN state')}
          </>,
          <div style={{ marginTop: 26, opacity: fade(f - simItems - 20, 8) }}>
            <DevChip milestone="M2" size={14} />
          </div>,
        )}
      </div>
    </Overlay>
  )
}

const SMOKE: [string, string][] = [
  ['redpanda', 'healthy, topics: gps.pings vehicle.telemetry, round trip ok'],
  ['redpanda-console', 'HTTP 200'],
  ['timescaledb', 'schemas 4/4 · dagster db 1'],
  ['rustfs', 'buckets: archive bronze'],
  ['grafana', 'datasource OK, dashboard provisioned'],
  ['dagster', "webserver up, code location 'llobregat' loaded"],
  ['osrm', 'real road route: 10.9 km, 18 min'],
]
const URLS: [string, string][] = [
  ['Grafana', 'http://localhost:3000'],
  ['Dagster', 'http://localhost:3001'],
  ['Redpanda Console', 'http://localhost:8080'],
  ['RustFS console', 'http://localhost:9001'],
  ['OSRM', 'http://localhost:5000'],
]

export function Smoke({ f }: { f: number }) {
  const s = scene('smoke')
  const up = beat('smoke-0', 'one')
  const memory = beat('smoke-0', 'two')
  const tested = beat('smoke-0', 'tested')
  const scratch = beat('smoke-0', 'scratch')
  const upDone = up + 18
  const smokeAt = tested - 4
  const smokeDone = smokeAt + 14
  const passed = smokeDone + SMOKE.length * 5 + 4
  const row = (children: ReactNode, at: number, key: string) => (
    <div key={key} style={{ opacity: f >= at ? 1 : 0, whiteSpace: 'pre' }}>
      {children}
    </div>
  )
  return (
    <Overlay id="smoke" f={f}>
      <Grid f={f} />
      <div style={{ position: 'absolute', left: 90, top: 138, ...pop(f - s.start) }}>
        <Caption>One command, then the proof</Caption>
      </div>
      <div style={{ position: 'absolute', left: 90, top: 196, width: 1180, ...pop(f - s.start - 4) }}>
        <div style={{ borderRadius: 14, border: `1px solid ${C.line}`, background: '#0A100E', overflow: 'hidden', boxShadow: '0 30px 80px rgba(0,0,0,0.45)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', background: C.panel, borderBottom: `1px solid ${C.line}` }}>
            {[C.faint, C.faint, C.faint].map((c, i) => (
              <span key={i} style={{ width: 12, height: 12, borderRadius: 6, background: c }} />
            ))}
            <span style={{ ...mono(15, 500, C.muted), marginLeft: 12 }}>datacycle-logistics-route-optimization · bash</span>
          </div>
          <div style={{ padding: '18px 24px 22px', ...mono(19, 500, C.ink), lineHeight: 1.55, height: 612, boxSizing: 'border-box' }}>
            <div>
              <span style={{ color: C.green }}>$</span> {typed('make up', f - up + 2, 0.7)}
              {f < upDone && f >= up - 2 && <span style={{ opacity: Math.floor(f / 8) % 2 }}>_</span>}
            </div>
            {row(<span style={{ color: C.muted }}>[+] Running 9/9 · every service healthy</span>, upDone, 'run')}
            {URLS.map(([name, url], i) =>
              row(
                <span>
                  {'  '}
                  {name.padEnd(18, ' ')}
                  <span style={{ color: C.blue }}>{url}</span>
                </span>,
                upDone + 3 + i * 2,
                name,
              ),
            )}
            {f >= smokeAt - 2 && (
              <div>
                <span style={{ color: C.green }}>$</span> {typed('make smoke', f - smokeAt, 0.8)}
              </div>
            )}
            {row(<span style={{ color: C.muted }}>Llobregat Express · smoke test</span>, smokeDone, 'title')}
            {SMOKE.map(([name, detail], i) =>
              row(
                <span>
                  {'  '}
                  <span style={{ color: C.green, fontWeight: 700 }}>PASS</span>
                  {'  '}
                  {name.padEnd(18, ' ')}
                  <span style={{ color: C.muted }}>{detail}</span>
                </span>,
                smokeDone + 4 + i * 5,
                name,
              ),
            )}
            {f >= passed && (
              <div style={{ marginTop: 6, ...pop(f - passed), transformOrigin: 'left center' }}>
                <span style={{ padding: '4px 12px', borderRadius: 6, background: 'rgba(76,183,130,0.14)', border: `1px solid ${C.green}`, color: C.green, fontWeight: 700 }}>
                  7 passed, 0 failed
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
      <div style={{ position: 'absolute', left: 1320, right: 90, top: 196, display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={pop(f - up)}>
          <Panel>
            <div style={mono(16, 500, C.muted)}>make up</div>
            <div style={{ ...display(64), marginTop: 6 }}>9 services</div>
            <div style={text(21, 500, C.muted)}>one command, on any machine with Docker</div>
          </Panel>
        </div>
        <div style={pop(f - memory)}>
          <Panel>
            <div style={mono(16, 500, C.muted)}>memory, all running</div>
            <div style={{ ...display(64), marginTop: 6 }}>1.8 GB</div>
            <div style={text(21, 500, C.muted)}>measured 28 Sep 2026, idle</div>
          </Panel>
        </div>
        <div style={pop(f - scratch)}>
          <Panel accent={C.green}>
            <div style={mono(16, 500, C.green)}>CI · every pull request</div>
            <div style={{ ...text(26, 600), marginTop: 8 }}>Boots the whole stack from scratch, then runs the smoke test</div>
          </Panel>
        </div>
      </div>
    </Overlay>
  )
}

// ── Close ────────────────────────────────────────────────────────────────────

export function Close({ f }: { f: number }) {
  const s = scene('close')
  if (f < s.start) return null
  const t = f - s.start
  const tag = lineEnd('close-0') - 10
  return (
    <AbsoluteFill style={{ opacity: fade(t, 10) }}>
      <AbsoluteFill style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', paddingBottom: 110 }}>
        <div style={pop(t - 2)}>
          <Mark size={150} stroke={3.2} />
        </div>
        <div style={{ ...display(132), marginTop: 26, ...pop(t - 8) }}>
          <Wordmark size={132} />
        </div>
        <div style={{ ...mono(32, 500, C.ink), marginTop: 18, ...pop(f - tag) }}>Plans the fleet, not the trip.</div>
        <div style={{ display: 'flex', gap: 44, marginTop: 54, ...text(26, 500, C.ink), ...pop(f - tag - 30) }}>
          {[
            ['Roger', '@RogerTito455'],
            ['Zehao', '@zyin-08'],
            ['Izan', '@izaantorrico'],
          ].map(([name, handle]) => (
            <span key={name}>
              {name} <span style={mono(21, 500, C.muted)}>· {handle}</span>
            </span>
          ))}
        </div>
        <div style={{ ...mono(20, 500, C.muted), marginTop: 14, ...pop(f - tag - 38) }}>Datacycle · Unit 1 · DAW2 2026–27</div>
        <div style={{ ...mono(20, 500, C.orange), marginTop: 10, ...pop(f - tag - 44) }}>github.com/RogerTito455/datacycle-logistics-route-optimization</div>
      </AbsoluteFill>
    </AbsoluteFill>
  )
}
