// The map, drawn from src/data/map.json (OpenStreetMap roads and coast, OSRM routes) with a virtual
// camera in kilometres, so scenes can fly from the whole city to one stretch of the Ronda Litoral.
// Static geometry is turned into SVG paths once, in kilometres; the camera is one transform.

import company from './data/company.json'
import map from './data/map.json'
import { Icon, Mark } from './Icon'
import { C, MONO, SANS, clamp01 } from './theme'

type LonLat = number[]

// Kilometres east and south of the hub, the company's own coordinates.
const LON0 = company.hub.lon
const LAT0 = company.hub.lat
const KX = 111.32 * Math.cos((41.38 * Math.PI) / 180)
const KY = 110.57

export const toKm = (lon: number, lat: number): [number, number] => [(lon - LON0) * KX, (LAT0 - lat) * KY]

/** Where the camera looks (km from the hub) and how close (pixels per km). */
export type Camera = { x: number; y: number; z: number }

export const camAt = (lon: number, lat: number, z: number): Camera => {
  const [x, y] = toKm(lon, lat)
  return { x, y, z }
}

export const lerpCam = (a: Camera, b: Camera, k: number): Camera => ({
  x: a.x + (b.x - a.x) * k,
  y: a.y + (b.y - a.y) * k,
  z: a.z * Math.pow(b.z / a.z, k),
})

export const DATA = map

// ── Geometry, once ───────────────────────────────────────────────────────────

const km = (line: LonLat[]) => line.map(([lon, lat]) => toKm(lon, lat))
const d = (pts: [number, number][], close = false) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(3)} ${y.toFixed(3)}`).join('') + (close ? 'Z' : '')
const many = (lines: LonLat[][]) => lines.map((l) => d(km(l))).join('')

const SEA = d(km(map.sea), true) + map.islands.map((r) => d(km(r), true)).join('')
const RIVERS = many([...map.rivers.llobregat, ...map.rivers.besos])
const ROADS = { streets: many(map.roads.streets), minor: many(map.roads.minor), primary: many(map.roads.primary), major: many(map.roads.major) }
export const ARTERIALS = Object.fromEntries(map.arterials.map((a) => [a.id, a]))

/** A polyline in km with its running length, so things can travel along it. */
export type Track = { pts: [number, number][]; cum: number[]; length: number }
export const track = (line: LonLat[]): Track => {
  const pts = km(line)
  const cum = [0]
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
  return { pts, cum, length: cum[cum.length - 1] }
}

/** The point `k` (0–1) of the way along a track, and the direction it faces there. */
export function along(t: Track, k: number): { at: [number, number]; angle: number } {
  const target = clamp01(k) * t.length
  let i = 1
  while (i < t.cum.length - 1 && t.cum[i] < target) i++
  const seg = t.cum[i] - t.cum[i - 1] || 1e-9
  const u = clamp01((target - t.cum[i - 1]) / seg)
  const [ax, ay] = t.pts[i - 1]
  const [bx, by] = t.pts[i]
  return { at: [ax + (bx - ax) * u, ay + (by - ay) * u], angle: Math.atan2(by - ay, bx - ax) }
}

/** The first `k` of a track, as a path. */
export function partial(t: Track, k: number): string {
  if (k <= 0) return ''
  const target = clamp01(k) * t.length
  const out: [number, number][] = [t.pts[0]]
  for (let i = 1; i < t.pts.length; i++) {
    if (t.cum[i] <= target) out.push(t.pts[i])
    else {
      out.push(along(t, k).at)
      break
    }
  }
  return d(out)
}

// ── The fleet: thirty vans on their morning routes ───────────────────────────

export const FIRST_DEPARTURE = 7 * 60 + 30
export const VANS = map.vans.map((v) => ({ ...v, outTrack: track(v.out.line), loopTrack: track(v.loop.line) }))

// A van drives out at the road's own speed, then works its zone: round its loop slowly, since most of
// a route is spent stopped at doors (about 72 stops of about 3 minutes, company.json).
const WORK = 7

/** Where a van is at a time of day (minutes after midnight), and how far along its drive out. */
export function vanAt(v: (typeof VANS)[number], clock: number): { at: [number, number]; angle: number; out: number; moving: boolean } {
  const t = clock - FIRST_DEPARTURE - v.departMin
  if (t <= 0) return { ...along(v.outTrack, 0), out: 0, moving: false }
  if (t < v.out.minutes) {
    const k = t / v.out.minutes
    return { ...along(v.outTrack, k), out: k, moving: true }
  }
  const lap = v.loop.minutes * WORK
  const k = ((t - v.out.minutes) / lap) % 1
  return { ...along(v.loopTrack, k), out: 1, moving: true }
}

// ── The picture ──────────────────────────────────────────────────────────────

export type MapProps = {
  cam: Camera
  /** Shift the picture on screen, to leave room for a panel. */
  offsetX?: number
  offsetY?: number
  /** Time of day in minutes after midnight: where the vans are. */
  clock: number
  f: number
  /** 0–1 each. */
  vans?: number
  trails?: number
  zoneLabels?: number
  hubLabel?: number
  arterialLabels?: number
  /** Which arterials are named, and where along each the name sits (0–1). */
  arterials?: Record<string, number>
  /** The Ronda Litoral by Glòries, jammed. */
  jam?: number
  /** Chapter 04: the stretch V-07 has crawled, the plan made at dawn, and the re-plan. */
  crawl?: number
  planned?: number
  replanned?: number
  /** 0 shows the stops in the old order, 1 in the new one. */
  reorder?: number
  focusVan?: number
  /** Darken the whole map, for a panel over it. */
  dim?: number
}

export const W = 1920
export const H = 1080

export function screen(p: { cam: Camera; offsetX?: number; offsetY?: number }, x: number, y: number): [number, number] {
  return [(x - p.cam.x) * p.cam.z + W / 2 + (p.offsetX ?? 0), (y - p.cam.y) * p.cam.z + H / 2 + (p.offsetY ?? 0)]
}

const PING = map.ping
export const PING_TRACKS = { crawl: track(PING.crawl), jam: track(PING.jam), planned: track(PING.planned.line), replanned: track(PING.replanned.line) }
const JAM = track(map.incidents.jam)

export function CityMap(p: MapProps) {
  const { cam } = p
  const tx = W / 2 + (p.offsetX ?? 0) - cam.x * cam.z
  const ty = H / 2 + (p.offsetY ?? 0) - cam.y * cam.z
  const at = (x: number, y: number) => screen(p, x, y)
  const onScreen = ([x, y]: [number, number], pad = 60) => x > -pad && x < W + pad && y > -pad && y < H + pad
  const streets = clamp01((cam.z - 110) / 90)
  const vans = clamp01(p.vans ?? 0)
  const trails = clamp01(p.trails ?? 0)
  const hub = at(0, 0)
  const vanR = Math.max(4.5, Math.min(7, cam.z * 0.07))

  return (
    <svg width={W} height={H} style={{ position: 'absolute', inset: 0 }}>
      <rect width={W} height={H} fill={C.ground} />
      <g transform={`translate(${tx.toFixed(2)} ${ty.toFixed(2)}) scale(${cam.z.toFixed(4)})`}>
        <path d={SEA} fill={C.sea} fillRule="evenodd" stroke="#1F3236" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
        <path d={RIVERS} fill="none" stroke={C.blue} strokeOpacity={0.32} strokeWidth={Math.max(2, cam.z * 0.02)} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {streets > 0 && <path d={ROADS.streets} fill="none" stroke={C.road} strokeOpacity={streets} strokeWidth={1.3} strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
        <path d={ROADS.minor} fill="none" stroke={C.road} strokeWidth={cam.z > 150 ? 2 : 1.1} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        <path d={ROADS.primary} fill="none" stroke={C.roadMajor} strokeWidth={cam.z > 150 ? 3 : 1.6} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        <path d={ROADS.major} fill="none" stroke="#35463F" strokeWidth={cam.z > 150 ? 4.5 : 2.4} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />

        {/* The routes driven so far this morning, faint: the fixed order, laid on the city. */}
        {trails > 0 &&
          VANS.map((v) => {
            const pos = vanAt(v, p.clock)
            return <path key={v.id} d={partial(v.outTrack, pos.out)} fill="none" stroke={C.ink} strokeOpacity={0.22 * trails} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          })}

        {(p.jam ?? 0) > 0 && (
          <g opacity={clamp01(p.jam ?? 0)}>
            <path d={d(JAM.pts)} fill="none" stroke={C.red} strokeOpacity={0.25} strokeWidth={cam.z > 150 ? 22 : 14} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            <path d={d(JAM.pts)} fill="none" stroke={C.red} strokeWidth={cam.z > 150 ? 7 : 5} strokeLinecap="round" strokeDasharray={cam.z > 150 ? undefined : '1 0'} vectorEffect="non-scaling-stroke" />
          </g>
        )}

        {(p.crawl ?? 0) > 0 && (
          <g opacity={clamp01(p.crawl ?? 0)}>
            <path d={d(PING_TRACKS.jam.pts)} fill="none" stroke={C.red} strokeOpacity={0.22} strokeWidth={26} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            <path d={d(PING_TRACKS.jam.pts)} fill="none" stroke={C.red} strokeOpacity={0.55} strokeWidth={8} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            <path d={d(PING_TRACKS.crawl.pts)} fill="none" stroke={C.red} strokeWidth={9} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          </g>
        )}

        {(p.planned ?? 0) > 0 && (
          <path d={partial(PING_TRACKS.planned, p.planned ?? 0)} fill="none" stroke={C.muted} strokeOpacity={0.9 - 0.45 * clamp01(p.reorder ?? 0)} strokeWidth={3} strokeDasharray="8 8" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        )}
        {(p.replanned ?? 0) > 0 && (
          <>
            <path d={partial(PING_TRACKS.replanned, p.replanned ?? 0)} fill="none" stroke={C.orange} strokeOpacity={0.25} strokeWidth={14} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            <path d={partial(PING_TRACKS.replanned, p.replanned ?? 0)} fill="none" stroke={C.orange} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          </>
        )}
      </g>

      {/* Arterials: the names the story uses. */}
      {(p.arterialLabels ?? 0) > 0 &&
        Object.entries(p.arterials ?? {}).map(([id, k]) => {
          const a = ARTERIALS[id]
          const { at: point, angle } = along(TRACKS[id], k)
          const s = at(...point)
          // Keep names clear of the header, the subtitles and a panel on the left.
          if (s[0] < ((p.offsetX ?? 0) > 0 ? 720 : 60) || s[0] > W - 120 || s[1] < 150 || s[1] > 860) return null
          // Written along the road, the right way up, just off it.
          let deg = (angle * 180) / Math.PI
          if (deg > 90) deg -= 180
          if (deg < -90) deg += 180
          return (
            <g key={id} opacity={p.arterialLabels} transform={`translate(${s[0].toFixed(1)} ${s[1].toFixed(1)}) rotate(${deg.toFixed(1)}) translate(0 -12)`}>
              <text x={0} y={0} textAnchor="middle" style={{ fontFamily: MONO, fontSize: 17, fontWeight: 500, letterSpacing: 0.5 }} fill={C.muted} stroke={C.ground} strokeWidth={5} paintOrder="stroke">
                {a.name}
                {a.ref ? ` ${a.ref}` : ''}
              </text>
            </g>
          )
        })}

      {/* Zones: the company's fourteen, at their real centres. */}
      {(p.zoneLabels ?? 0) > 0 &&
        map.zones.map((z) => {
          const s = at(...toKm(z.lon, z.lat))
          if (!onScreen(s)) return null
          return (
            <g key={z.id} opacity={p.zoneLabels} transform={`translate(${s[0].toFixed(1)} ${s[1].toFixed(1)})`}>
              <circle r={22} fill="none" stroke={C.muted} strokeOpacity={0.35} strokeWidth={1.2} strokeDasharray="3 4" />
              <text
                x={ZONE_LABEL[z.id] === 'left' ? -30 : ZONE_LABEL[z.id] === 'right' ? 30 : 0}
                y={ZONE_LABEL[z.id] ? 6 : -30}
                textAnchor={ZONE_LABEL[z.id] === 'left' ? 'end' : ZONE_LABEL[z.id] === 'right' ? 'start' : 'middle'}
                style={{ fontFamily: SANS, fontSize: 17, fontWeight: 600 }}
                fill={C.muted}
                stroke={C.ground}
                strokeWidth={5}
                paintOrder="stroke"
              >
                <tspan style={{ fontFamily: MONO, fontWeight: 500 }} fill={C.faint}>
                  {z.id}{' '}
                </tspan>
                {z.name.replace(' de Llobregat', '')}
              </text>
            </g>
          )
        })}

      {/* The hub in the Zona Franca. */}
      <g transform={`translate(${hub[0].toFixed(1)} ${hub[1].toFixed(1)})`}>
        <rect x={-19} y={-19} width={38} height={38} rx={8} fill={C.panel} stroke={C.orange} strokeWidth={2} />
        <g transform="translate(-13 -14)">
          <Mark size={26} stroke={4} />
        </g>
        {(p.hubLabel ?? 0) > 0 && (
          <g opacity={p.hubLabel}>
            <text x={30} y={-4} style={{ fontFamily: SANS, fontSize: 21, fontWeight: 700 }} fill={C.ink} stroke={C.ground} strokeWidth={5} paintOrder="stroke">
              Hub · Zona Franca
            </text>
            <text x={30} y={20} style={{ fontFamily: MONO, fontSize: 15, fontWeight: 500 }} fill={C.muted} stroke={C.ground} strokeWidth={5} paintOrder="stroke">
              36 docks · 30 vans
            </text>
          </g>
        )}
      </g>

      {/* The vans: simulated positions on the real roads. */}
      {vans > 0 &&
        VANS.map((v) => {
          const pos = vanAt(v, p.clock)
          if (!pos.moving) return null
          const s = at(...pos.at)
          if (!onScreen(s)) return null
          return (
            <g key={v.id} opacity={vans} transform={`translate(${s[0].toFixed(1)} ${s[1].toFixed(1)})`}>
              <circle r={vanR + 4} fill={C.ink} opacity={0.12} />
              <circle r={vanR} fill={C.ink} stroke={C.ground} strokeWidth={2} />
            </g>
          )
        })}
    </svg>
  )
}

const TRACKS = Object.fromEntries(map.arterials.map((a) => [a.id, track(a.line)]))

// Zone names that would sit on a neighbour go beside their ring instead of above it.
const ZONE_LABEL: Record<string, 'left' | 'right'> = { Z05: 'left', Z04: 'left', Z02: 'right', Z01: 'right', Z10: 'left' }

/** A van seen close: a rounded marker with a heading notch, and its id. */
export function VanMarker({ x, y, angle, label, color = C.ink, scale = 1 }: { x: number; y: number; angle: number; label?: string; color?: string; scale?: number }) {
  return (
    <g transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${scale})`}>
      <g transform={`rotate(${((angle * 180) / Math.PI).toFixed(1)})`}>
        <path d="M 22 0 L 12 -8 L 12 8 Z" fill={color} />
      </g>
      <circle r={17} fill={C.panel} stroke={color} strokeWidth={3} />
      <g transform="translate(-11 -11)">
        <Icon name="van" size={22} color={color} stroke={2.2} />
      </g>
      {label && (
        <text x={0} y={-28} textAnchor="middle" style={{ fontFamily: MONO, fontSize: 20, fontWeight: 700 }} fill={color} stroke={C.ground} strokeWidth={5} paintOrder="stroke">
          {label}
        </text>
      )}
    </g>
  )
}
