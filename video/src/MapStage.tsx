// One map for the map scenes, so the camera flies instead of cutting: the morning from the hub
// (chapter 01), the stretch of the Ronda Litoral where one ping becomes a decision (chapter 04), and
// the city under the end card. Times of day are illustrative; places, roads and routes are real.

import type { CSSProperties, ReactNode } from 'react'
import { AbsoluteFill } from 'remotion'
import { CityMap, DATA, PING_TRACKS, VanMarker, along, camAt, lerpCam, screen, toKm, type MapProps } from './CityMap'
import { Chip, Clock, DevChip } from './Chrome'
import { Icon } from './Icon'
import { beat, line, scene } from './timeline'
import { C, clamp01, display, ease, easeOut, fade, hhmm, mono, pop, sp, text } from './theme'

const HUB = camAt(2.1365, 41.3395, 150)
const CITY = camAt(2.117, 41.381, 56)
const INCIDENTS = camAt(2.1795, 41.3895, 138)
const PING_VIEW = camAt(2.1975, 41.3905, 185)
const CLOSE_VIEW = camAt(2.125, 41.383, 60)
const PANEL = 330 // how far right the map moves when a panel sits on the left

type Stage = MapProps & { clockLabel: string; clockOpacity: number }

const at = (s: Stage, lon: number, lat: number) => screen(s, ...toKm(lon, lat))

function stage(f: number): Stage | null {
  const incidents = scene('incidents')
  const cascade = scene('cascade')
  const ping = scene('ping')
  const close = scene('close')
  const base = { f, clockLabel: 'Weekday morning · illustrative', clockOpacity: 1 }

  if (f < incidents.start) {
    // 07:30 on "Half past seven"; the vans leave on "Thirty"; on "By eleven" the morning runs to 11:00.
    const leave = beat('open-1', 'thirty')
    const eleven = beat('open-2', 'eleven') + 14
    const run = line('open-2').at - 4
    const clock =
      f < leave ? 450 : f < run ? 450 + 38 * ease((f - leave) / (run - leave)) : 488 + (660 - 488) * ease((f - run) / (eleven - run))
    return {
      ...base,
      cam: lerpCam(HUB, CITY, ease((f - 20) / (leave - 4))),
      clock: Math.min(clock, 660) + Math.max(0, f - eleven) * 0.03,
      vans: fade(f - leave + 4, 8),
      trails: 1,
      zoneLabels: fade(f - leave - 10, 20),
      hubLabel: fade(f - 12, 12),
      arterialLabels: fade(f - leave - 20, 20),
      arterials: { litoral: 0.3, dalt: 0.62 },
      clockOpacity: fade(f - 6, 10),
    }
  }
  if (f < cascade.end + 8) {
    const t = f - incidents.start
    const clock = 660.5 + (f - incidents.start) * 0.03
    const toCascade = ease((f - cascade.start + 6) / 22)
    return {
      ...base,
      cam: lerpCam(CITY, INCIDENTS, ease(t / 24)),
      offsetX: PANEL * toCascade,
      clock,
      vans: 1,
      trails: 1 - 0.6 * ease(t / 24),
      zoneLabels: 1 - ease(t / 16),
      hubLabel: 1 - ease(t / 16),
      arterialLabels: ease((t - 16) / 12),
      arterials: { litoral: 0.47, dalt: 0.55, granvia: 0.62, diagonal: 0.64 },
      jam: fade(f - beat('incidents-0', 'ronda') + 2, 8),
      dim: 0.35 * toCascade,
    }
  }
  if (f >= ping.start && f < ping.end + 8) {
    const t = f - ping.start
    const k = ease(t / 40)
    return {
      ...base,
      cam: lerpCam(camAt(2.18, 41.386, 90), PING_VIEW, k),
      offsetX: PANEL * k,
      offsetY: -10 * k,
      clock: 664,
      vans: 0,
      arterialLabels: fade(t - 30, 12),
      arterials: { litoral: 0.43 },
      crawl: fade(f - beat('ping-1', 'joined'), 10),
      planned: easeOut((f - line('ping-3').at + 4) / 26),
      replanned: easeOut((f - beat('ping-4', 're-orders')) / 40),
      reorder: fade(f - beat('ping-4', 'fourteen'), 30),
      focusVan: 1,
    }
  }
  if (f >= close.start) {
    return { ...base, cam: CLOSE_VIEW, clock: 700 + (f - close.start) * 0.05, vans: 1, trails: 0.5, dim: 0.78, clockOpacity: 0 }
  }
  return null
}

export function MapStage({ f }: { f: number }) {
  const s = stage(f)
  if (!s) return null
  return (
    <AbsoluteFill>
      <CityMap {...s} />
      {(s.dim ?? 0) > 0 && <AbsoluteFill style={{ background: C.ground, opacity: s.dim }} />}
      <Clock time={hhmm(s.clock)} label={s.clockLabel} opacity={s.clockOpacity} />
      <OpenOverlay f={f} />
      <IncidentsOverlay f={f} s={s} />
      <CascadeOverlay f={f} />
      <PingOverlay f={f} s={s} />
    </AbsoluteFill>
  )
}

/** Fades a scene's own overlay in at its start and out at its end. */
function During({ ids, f, children, out = 10 }: { ids: string[]; f: number; children: ReactNode; out?: number }) {
  const a = scene(ids[0]).start
  const b = scene(ids[ids.length - 1]).end
  if (f < a || f >= b) return null
  return <AbsoluteFill style={{ opacity: Math.min(fade(f - a, 8), fade(b - f, out)) }}>{children}</AbsoluteFill>
}

export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <div style={{ background: 'rgba(21,30,27,0.95)', border: `1px solid ${C.line}`, borderRadius: 14, padding: '18px 22px', boxShadow: '0 18px 50px rgba(0,0,0,0.45)', ...style }}>{children}</div>
}

function Pulse({ at: p, f, color, size = 60 }: { at: [number, number]; f: number; color: string; size?: number }) {
  return (
    <>
      {[0, 1, 2].map((i) => {
        const k = ((f + i * 12) % 36) / 36
        const r = size * (0.4 + k)
        return <div key={i} style={{ position: 'absolute', left: p[0] - r / 2, top: p[1] - r / 2, width: r, height: r, borderRadius: '50%', border: `3px solid ${color}`, opacity: 1 - k }} />
      })}
    </>
  )
}

// ── 01 · The morning plan ────────────────────────────────────────────────────

function OpenOverlay({ f }: { f: number }) {
  const figures: [number, string, string][] = [
    [beat('open-1', 'thirty'), '30', 'vans leave the hub'],
    [beat('open-1', 'seventy'), '~70', 'stops each'],
    [beat('open-1', 'fixed'), '1', 'fixed order per van'],
  ]
  const wrong = beat('open-2', 'wrong')
  return (
    <During ids={['open']} f={f}>
      <div style={{ position: 'absolute', left: 48, top: 146, ...pop(f - 10) }}>
        <div style={display(76)}>Zona Franca</div>
        <div style={{ ...mono(18, 500, C.muted), marginTop: 8 }}>Llobregat Express hub · Barcelona · 07:30</div>
      </div>
      <div style={{ position: 'absolute', left: 48, top: 290, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {figures.map(([t, figure, label]) => (
          <div key={label} style={pop(f - t)}>
            <Card style={{ padding: '12px 22px', width: 420, display: 'flex', alignItems: 'baseline', gap: 14 }}>
              <span style={{ ...mono(46, 600, C.ink), minWidth: 92 }}>{figure}</span>
              <span style={text(22, 500, C.muted)}>{label}</span>
            </Card>
          </div>
        ))}
      </div>
      {f >= wrong && (
        <div style={{ position: 'absolute', left: 48, top: 590, ...pop(f - wrong) }}>
          <Chip color={C.red} icon="x" size={19}>
            By 11:00 the order no longer fits the day
          </Chip>
        </div>
      )}
    </During>
  )
}

const INCIDENT_CARDS = (s: Stage): { word: string; icon: string; color: string; title: string; detail: string; anchor: [number, number]; offset: [number, number] }[] => {
  const I = DATA.incidents
  const jamMid = I.jam[Math.floor(I.jam.length * 0.55)]
  return [
    { word: 'car', icon: 'car', color: C.amber, title: 'A car in the loading bay', detail: 'DUM bay · C/ Roger de Llúria, 102', anchor: at(s, I.bay.lon, I.bay.lat), offset: [-500, -46] },
    { word: 'ronda', icon: 'jam', color: C.red, title: 'Ronda Litoral jams', detail: 'B-10 by Glòries · stop and go', anchor: at(s, jamMid[0], jamMid[1]), offset: [60, 40] },
    { word: 'rain', icon: 'rain', color: C.blue, title: 'It starts to rain', detail: 'every leg slows down', anchor: [0, 0], offset: [0, 0] },
    { word: 'nobody', icon: 'door', color: C.amber, title: 'Nobody at the door', detail: 'El Raval · C/ de l’Hospital', anchor: at(s, I.raval.lon, I.raval.lat), offset: [-500, 20] },
  ]
}

function IncidentsOverlay({ f, s }: { f: number; s: Stage }) {
  const cards = INCIDENT_CARDS(s)
  const cascade = scene('cascade')
  const fadeOut = 1 - 0.55 * ease((f - cascade.start) / 20)
  const rainAt = beat('incidents-0', 'rain')
  const glories = at(s, DATA.incidents.glories[0], DATA.incidents.glories[1])
  return (
    <During ids={['incidents', 'cascade']} f={f}>
      {f >= rainAt && <Rain f={f - rainAt} />}
      <div style={{ position: 'absolute', left: glories[0] - 7, top: glories[1] - 7, width: 14, height: 14, borderRadius: 7, background: C.ground, border: `2.5px solid ${C.muted}`, opacity: fade(f - beat('incidents-0', 'ronda'), 8) }} />
      <div style={{ position: 'absolute', left: glories[0] + 14, top: glories[1] - 16, ...text(22, 600, C.ink), opacity: fade(f - beat('incidents-0', 'ronda'), 8), textShadow: `0 0 6px ${C.ground}, 0 0 6px ${C.ground}` }}>Glòries</div>
      {cards.map((c, i) => {
        const t = beat('incidents-0', c.word)
        if (f < t - 2) return null
        const isRain = c.icon === 'rain'
        const box: [number, number] = isRain ? [48, 150] : [c.anchor[0] + c.offset[0], c.anchor[1] + c.offset[1]]
        return (
          <div key={i} style={{ opacity: fadeOut }}>
            {!isRain && f - t < 40 && <Pulse at={c.anchor} f={f - t} color={c.color} size={70} />}
            {!isRain && (
              <div style={{ position: 'absolute', left: c.anchor[0] - 9, top: c.anchor[1] - 9, width: 18, height: 18, borderRadius: 9, background: c.color, border: `3px solid ${C.ground}`, ...pop(f - t) }} />
            )}
            <div style={{ position: 'absolute', left: box[0], top: box[1], ...pop(f - t) }}>
              <Card style={{ padding: '12px 18px', display: 'flex', alignItems: 'center', gap: 14, width: 450, borderColor: c.color }}>
                <div style={{ width: 46, height: 46, borderRadius: 23, border: `2px solid ${c.color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 'none' }}>
                  <Icon name={c.icon} size={26} color={c.color} />
                </div>
                <div>
                  <div style={text(24, 600)}>{c.title}</div>
                  <div style={mono(16, 500, C.muted)}>{c.detail}</div>
                </div>
              </Card>
            </div>
          </div>
        )
      })}
    </During>
  )
}

/** Rain over the whole map: short streaks falling on a slant, drawn in code. */
function Rain({ f }: { f: number }) {
  const k = fade(f, 16)
  const drops = Array.from({ length: 140 }, (_, i) => {
    const x = (i * 137.5) % 1980
    const speed = 26 + (i % 7) * 3
    const y = ((i * 89) % 1140) + f * speed
    return [((x - f * 6) % 1980 + 1980) % 1980, (y % 1140) - 60] as const
  })
  return (
    <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0, opacity: 0.55 * k }}>
      {drops.map(([x, y], i) => (
        <line key={i} x1={x} y1={y} x2={x - 6} y2={y + 26} stroke="#8FB3D6" strokeOpacity={0.35 + (i % 3) * 0.12} strokeWidth={1.5} strokeLinecap="round" />
      ))}
    </svg>
  )
}

// The route of one van in the Eixample, stops 31 to 38 of its 78 (company.json: Z02, 78 stops a route,
// 3 minutes a stop). The streets are real, the times illustrative: the car in the bay costs 9 minutes,
// the rain one or two more at every stop after it.
const STOPS: [number, string, string, number, number][] = [
  [31, 'C/ de Roger de Llúria', '10–12', 681, 9],
  [32, 'C/ d’Aragó', '10–12', 685, 10],
  [33, 'C/ de València', '10–12', 689, 12],
  [34, 'C/ de Pau Claris', '10–12', 693, 14],
  [35, 'C/ del Bruc', '10–12', 697, 16],
  [36, 'C/ de Girona', '10–12', 701, 18],
  [37, 'C/ de Mallorca', '10–12', 705, 20],
  [38, 'C/ de Casp', '12–14', 709, 22],
]

function CascadeOverlay({ f }: { f: number }) {
  const c = scene('cascade')
  const delay = beat('cascade-0', 'delay')
  const never = beat('cascade-0', 'never')
  return (
    <During ids={['cascade']} f={f} out={8}>
      <div style={{ position: 'absolute', left: 48, top: 140, width: 640, ...pop(f - c.start - 2) }}>
        <Card style={{ padding: '20px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Icon name="van" size={28} color={C.ink} />
            <span style={text(28, 700)}>V-03 · Eixample</span>
            <span style={{ ...mono(16, 500, C.muted), marginLeft: 'auto' }}>stops 31–38 of 78</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '44px 1fr 88px 92px 110px', columnGap: 10, marginTop: 16, ...mono(15, 500, C.faint) }}>
            <span>#</span>
            <span>address</span>
            <span>window</span>
            <span>plan</span>
            <span>now</span>
          </div>
          <div style={{ height: 1, background: C.line, margin: '8px 0 4px' }} />
          {STOPS.map(([n, street, win, eta, late], i) => {
            const t = f - delay - i * 5
            const moved = ease(t / 10)
            const now = eta + late * moved
            const end = win === '10–12' ? 720 : 840
            const isLate = t > 10 && now > end
            return (
              <div key={n} style={{ display: 'grid', gridTemplateColumns: '44px 1fr 88px 92px 110px', columnGap: 10, alignItems: 'center', padding: '7px 0', borderBottom: i < STOPS.length - 1 ? `1px solid ${C.line}` : undefined }}>
                <span style={mono(18, 600, C.muted)}>{n}</span>
                <span style={text(20, 500, C.ink)}>{street}</span>
                <span style={mono(17, 500, C.muted)}>{win}</span>
                <span style={{ ...mono(19, 500, t > 0 ? C.faint : C.ink), textDecoration: t > 4 ? 'line-through' : undefined }}>{hhmm(eta)}</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: fade(t, 6) }}>
                  <span style={{ ...mono(19, 600, isLate ? C.red : C.amber), transform: `translateX(${(1 - moved) * -14}px)` }}>{hhmm(now)}</span>
                  <span style={mono(14, 600, isLate ? C.red : C.amber)}>{isLate ? 'late' : `+${Math.round(late * moved)}`}</span>
                </span>
              </div>
            )
          })}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 16 }}>
            <span style={mono(16, 500, C.muted)}>Plan made at 06:30</span>
            {f >= never && (
              <div style={pop(f - never)}>
                <Chip color={C.red} icon="x" size={16}>
                  not updated since
                </Chip>
              </div>
            )}
          </div>
        </Card>
      </div>
    </During>
  )
}

// ── 04 · From a ping to a decision ───────────────────────────────────────────

const P = DATA.ping
const PING_JSON: [string, string][] = [
  ['vehicle_id', '"V-07"'],
  ['event_time', '"2026-10-06T11:04:35+02:00"'],
  ['lat', P.van.lat.toFixed(5)],
  ['lon', P.van.lon.toFixed(5)],
  ['speed_kmh', '6'],
  ['heading', String(P.van.heading)],
]

// Weekday × hour for the stretch, from the pattern the company profile names (Ronda Litoral, 07:30–09:30),
// drawn as the history would show it. Illustrative until route history lands at M2.
const HOURS = Array.from({ length: 16 }, (_, i) => 6 + i * 0.5)
const load = (day: number, h: number) => {
  const peak = Math.exp(-Math.pow((h - 8.5) / 1.1, 2))
  const late = 0.55 * Math.exp(-Math.pow((h - 11) / 0.9, 2))
  const friday = day === 4 ? 0.85 : 1
  return Math.min(1, (peak + late) * friday + 0.08 * ((day * 7 + h * 3) % 3))
}
const heat = (v: number) => (v > 0.72 ? C.red : v > 0.45 ? C.amber : v > 0.25 ? '#6B8F5E' : '#2E4A3C')

function PingOverlay({ f, s }: { f: number; s: Stage }) {
  const p = scene('ping')
  const pingAt = beat('ping-0', 'ping')
  const info = beat('ping-1', 'information')
  const know = beat('ping-2', 'knowledge')
  const act = line('ping-3').at
  const reorder = beat('ping-4', 'fourteen')
  const before = beat('ping-4', 'before')
  const van = at(s, P.van.lon, P.van.lat)
  // After "before it reaches the jam", V-07 takes the new route: off at the next exit.
  const go = easeOut((f - before) / 50) * 0.075
  const moving = along(PING_TRACKS.replanned, go)
  const vanNow = go > 0 ? screen(s, ...moving.at) : van
  const heading = go > 0 ? moving.angle : along(PING_TRACKS.replanned, 0.01).angle
  const crawlLabel = at(s, ...(P.crawl[Math.floor(P.crawl.length * 0.4)] as [number, number]))
  const oldPos = (i: number) => P.planned.order.indexOf(i) + 1
  const newPos = (i: number) => P.replanned.order.indexOf(i) + 1
  const glories = at(s, DATA.incidents.glories[0], DATA.incidents.glories[1])
  const steps: [string, number, string][] = [
    ['Data', pingAt - 6, C.blue],
    ['Information', info, C.ink],
    ['Knowledge', know, C.ink],
    ['Action', act, C.orange],
  ]
  return (
    <During ids={['ping']} f={f}>
      {/* Places on the map. */}
      <div style={{ position: 'absolute', left: glories[0] - 7, top: glories[1] - 7, width: 14, height: 14, borderRadius: 7, background: C.ground, border: `2.5px solid ${C.muted}`, opacity: fade(f - p.start - 30, 10) }} />
      <div style={{ position: 'absolute', left: glories[0] - 104, top: glories[1] - 16, ...text(22, 600, C.ink), opacity: fade(f - p.start - 30, 10), textShadow: `0 0 6px ${C.ground}, 0 0 6px ${C.ground}` }}>Glòries</div>
      {f >= info && (
        <div style={{ position: 'absolute', left: crawlLabel[0] + 26, top: crawlLabel[1] + 6, ...pop(f - info - 4) }}>
          <Chip color={C.red} icon="jam" size={18}>
            9 min at 6 km/h
          </Chip>
        </div>
      )}
      {/* The fourteen stops left, numbered in the order they will be served. */}
      <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0 }}>
        {P.stops.map((stop, i) => {
          const [x, y] = at(s, stop.lon, stop.lat)
          const shown = fade(f - act - 2 - i * 1.5, 6)
          if (shown <= 0) return null
          const flip = clamp01((f - reorder - newPos(i) * 2.2) / 6)
          const num = flip > 0.5 ? newPos(i) : oldPos(i)
          const k = sp(f - reorder - newPos(i) * 2.2, 12, 200)
          const r = 15 + 3 * Math.sin(Math.PI * clamp01(k))
          return (
            <g key={i} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`} opacity={shown}>
              <circle r={r} fill={flip > 0.5 ? C.orange : C.panel} stroke={flip > 0.5 ? C.ground : C.muted} strokeWidth={2} />
              <text y={5.5} textAnchor="middle" style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 15, fontWeight: 700 }} fill={flip > 0.5 ? C.ground : C.ink}>
                {num}
              </text>
            </g>
          )
        })}
        {f >= pingAt && f < pingAt + 40 && (
          <g transform={`translate(${van[0]} ${van[1]})`}>
            {[0, 1].map((i) => {
              const k = clamp01((f - pingAt - i * 10) / 26)
              return <circle key={i} r={20 + 70 * k} fill="none" stroke={C.blue} strokeWidth={3} opacity={(1 - k) * (k > 0 ? 1 : 0)} />
            })}
          </g>
        )}
        <VanMarker x={vanNow[0]} y={vanNow[1]} angle={heading} label="V-07" color={f >= before ? C.orange : C.ink} />
      </svg>

      {/* The DIKW ladder on the left. */}
      <div style={{ position: 'absolute', left: 48, top: 140, width: 600, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, ...pop(f - p.start - 10) }}>
          {steps.map(([name, t, color], i) => {
            const lit = f >= t
            return (
              <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ ...mono(16, 600, lit ? color : C.faint), padding: '4px 10px', borderRadius: 6, border: `1px solid ${lit ? color : C.line}`, background: lit ? 'rgba(21,30,27,0.95)' : 'transparent' }}>{name.toUpperCase()}</span>
                {i < 3 && <Icon name="arrow" size={16} color={C.faint} />}
              </div>
            )
          })}
        </div>
        {f >= pingAt - 6 && (
          <div style={pop(f - pingAt + 6)}>
            <Card style={{ padding: '14px 20px', borderColor: 'rgba(91,155,230,0.55)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, ...mono(15, 500, C.blue) }}>
                <Icon name="signal" size={18} color={C.blue} />
                topic gps.pings · one message
              </div>
              <div style={{ ...mono(18, 500, C.ink), marginTop: 10, lineHeight: 1.45 }}>
                {'{'}
                {PING_JSON.map(([k, v], i) => (
                  <div key={k} style={{ paddingLeft: 22, opacity: fade(f - pingAt - i * 2, 4) }}>
                    <span style={{ color: C.blue }}>"{k}"</span>: <span style={{ color: k === 'speed_kmh' && f >= info ? C.red : C.ink }}>{v}</span>
                    {i < PING_JSON.length - 1 ? ',' : ''}
                  </div>
                ))}
                {'}'}
              </div>
            </Card>
          </div>
        )}
        {f >= info && (
          <div style={pop(f - info)}>
            <Card style={{ padding: '12px 20px' }}>
              <div style={mono(15, 500, C.muted)}>+ joined to the road</div>
              <div style={{ ...text(22, 600), marginTop: 4 }}>
                Ronda Litoral, north-east · <span style={{ color: C.red }}>crawling for 9 min</span>
              </div>
            </Card>
          </div>
        )}
        {f >= know && (
          <div style={pop(f - know)}>
            <Card style={{ padding: '12px 20px' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span style={mono(15, 500, C.muted)}>+ against the history · this stretch</span>
                <span style={{ ...mono(13, 500, C.faint), marginLeft: 'auto' }}>illustrative</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: `40px repeat(${HOURS.length}, 1fr)`, gap: 3, marginTop: 10, alignItems: 'center' }}>
                {['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].map((day, d) => [
                  <span key={day} style={mono(13, 500, C.muted)}>
                    {day}
                  </span>,
                  ...HOURS.map((h, j) => {
                    const now = d === 1 && h === 11
                    return <span key={`${day}${h}`} style={{ height: 15, borderRadius: 2, background: heat(load(d, h)), opacity: fade(f - know - j * 0.8 - d, 5), outline: now ? `2px solid ${C.ink}` : undefined, outlineOffset: 1 }} />
                  }),
                ])}
                <span />
                {HOURS.map((h) => (
                  <span key={h} style={{ ...mono(12, 500, C.faint), textAlign: 'center', visibility: h % 2 === 0 ? 'visible' : 'hidden' }}>
                    {String(h).padStart(2, '0')}
                  </span>
                ))}
              </div>
              <div style={{ ...text(20, 600), marginTop: 8 }}>Jams on weekday mornings</div>
            </Card>
          </div>
        )}
        {f >= act && (
          <div style={pop(f - act)}>
            <Card style={{ padding: '12px 20px', borderColor: C.orange }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={mono(15, 500, C.orange)}>+ the optimizer · re-plan V-07</span>
                <span style={{ marginLeft: 'auto' }}>
                  <DevChip milestone="M3" size={13} />
                </span>
              </div>
              <div style={{ ...text(22, 600), marginTop: 4 }}>
                {f >= reorder ? 'Leave at the next exit; 14 stops re-ordered on real road times' : '14 stops left, in the order fixed at dawn'}
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* Legend for the two routes. */}
      {f >= act && (
        <div style={{ position: 'absolute', right: 48, top: 250, display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end', ...pop(f - act - 6) }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 10, ...mono(16, 500, C.muted) }}>
            <svg width={44} height={8}>
              <line x1={2} y1={4} x2={42} y2={4} stroke={C.muted} strokeWidth={3} strokeDasharray="7 6" />
            </svg>
            plan made at dawn
          </span>
          {f >= reorder - 10 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 10, ...mono(16, 500, C.orange), opacity: fade(f - reorder + 10, 8) }}>
              <svg width={44} height={8}>
                <line x1={2} y1={4} x2={42} y2={4} stroke={C.orange} strokeWidth={5} strokeLinecap="round" />
              </svg>
              re-planned at 11:04
            </span>
          )}
        </div>
      )}
    </During>
  )
}
