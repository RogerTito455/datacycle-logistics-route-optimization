// Builds src/data/map.json, everything the map scenes draw, so a render needs no network:
//
//   - the roads, the coastline and the rivers, from OpenStreetMap through the Overpass API (cached in
//     scripts/.cache/, which is git-ignored; delete a file there to fetch it again);
//   - every van's route, the four arterials and the re-plan of chapter 04, from the OSRM server of the
//     platform (http://localhost:5000, or OSRM_URL), on the real Catalonia road network;
//   - the loading bay of chapter 01, from Open Data BCN's loading and unloading areas (CC BY 4.0).
//
//   node scripts/map.ts
//
// The hub, the zones and the fleet come from src/data/company.json, a copy of the platform's seed.

import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const CACHE = join(ROOT, 'scripts/.cache')
const OUT = join(ROOT, 'src/data/map.json')
const OSRM = process.env.OSRM_URL ?? 'http://localhost:5000'
const OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
const UA = 'llobregat-express-video/1.0 (map build, run by hand)'

type LonLat = [number, number]
type Company = {
  hub: { lat: number; lon: number }
  zones: { id: string; name: string; lat: number; lon: number; share: number; stops_per_route: number }[]
}
const company: Company = JSON.parse(readFileSync(join(ROOT, 'src/data/company.json'), 'utf-8'))
const HUB: LonLat = [company.hub.lon, company.hub.lat]

// ── Geometry helpers ─────────────────────────────────────────────────────────

const LAT0 = 41.38
const KX = 111.32 * Math.cos((LAT0 * Math.PI) / 180)
const KY = 110.57
const km = ([lon, lat]: LonLat): [number, number] => [lon * KX, -lat * KY]
const dist = (a: LonLat, b: LonLat) => {
  const [ax, ay] = km(a)
  const [bx, by] = km(b)
  return Math.hypot(ax - bx, ay - by)
}
const round = (p: LonLat): LonLat => [Math.round(p[0] * 1e5) / 1e5, Math.round(p[1] * 1e5) / 1e5]

/** Douglas–Peucker in kilometres: drops the points a line can do without at this tolerance. */
function simplify(line: LonLat[], toleranceKm: number): LonLat[] {
  if (line.length < 3) return line
  // A closed ring has no chord to measure against: simplify its two halves.
  if (dist(line[0], line[line.length - 1]) < 1e-6) {
    const half = Math.floor(line.length / 2)
    return [...simplify(line.slice(0, half + 1), toleranceKm).slice(0, -1), ...simplify(line.slice(half), toleranceKm)]
  }
  const keep = new Uint8Array(line.length)
  keep[0] = keep[line.length - 1] = 1
  const stack: [number, number][] = [[0, line.length - 1]]
  const pts = line.map(km)
  while (stack.length) {
    const [a, b] = stack.pop()!
    const [ax, ay] = pts[a]
    const [bx, by] = pts[b]
    const len = Math.hypot(bx - ax, by - ay) || 1e-9
    let worst = -1
    let at = -1
    for (let i = a + 1; i < b; i++) {
      const [px, py] = pts[i]
      const d = Math.abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / len
      if (d > worst) {
        worst = d
        at = i
      }
    }
    if (worst > toleranceKm) {
      keep[at] = 1
      stack.push([a, at], [at, b])
    }
  }
  return line.filter((_, i) => keep[i])
}

const tidy = (line: LonLat[], toleranceKm: number) => simplify(line, toleranceKm).map(round)

/** A stretch of a line, from `fromKm` to `toKm` along it. */
function slice(line: LonLat[], fromKm: number, toKm: number): LonLat[] {
  const out: LonLat[] = []
  let walked = 0
  for (let i = 1; i < line.length; i++) {
    const d = dist(line[i - 1], line[i])
    const a = walked
    const b = walked + d
    const at = (k: number): LonLat => {
      const t = d ? (k - a) / d : 0
      return [line[i - 1][0] + (line[i][0] - line[i - 1][0]) * t, line[i - 1][1] + (line[i][1] - line[i - 1][1]) * t]
    }
    if (b >= fromKm && a <= toKm) {
      if (!out.length) out.push(at(Math.max(a, fromKm)))
      out.push(b <= toKm ? line[i] : at(toKm))
    }
    walked = b
  }
  return out
}

/** How far along `line` its point nearest to `p` is, in km. */
function along(line: LonLat[], p: LonLat): number {
  let best = Infinity
  let bestKm = 0
  let walked = 0
  for (let i = 0; i < line.length; i++) {
    const d = dist(line[i], p)
    if (d < best) {
      best = d
      bestKm = walked
    }
    if (i + 1 < line.length) walked += dist(line[i], line[i + 1])
  }
  return bestKm
}

function bearing(a: LonLat, b: LonLat): number {
  const [ax, ay] = km(a)
  const [bx, by] = km(b)
  return Math.round(((Math.atan2(bx - ax, -(by - ay)) * 180) / Math.PI + 360) % 360)
}

// ── Fetching, with a cache ───────────────────────────────────────────────────

mkdirSync(CACHE, { recursive: true })

async function cached<T>(name: string, fetcher: () => Promise<T>): Promise<T> {
  const file = join(CACHE, `${name}.json`)
  if (existsSync(file)) return JSON.parse(readFileSync(file, 'utf-8'))
  const value = await fetcher()
  writeFileSync(file, JSON.stringify(value))
  return value
}

type OverpassWay = { tags?: Record<string, string>; geometry: { lat: number; lon: number }[] }

/** Overpass is busy at times (HTTP 504): each mirror is tried in turn, three rounds, with a pause. */
async function overpass(name: string, query: string): Promise<OverpassWay[]> {
  const answer = await cached(name, async () => {
    for (let round = 0; round < 3; round++) {
      for (const url of OVERPASS) {
        const response = await fetch(url, { method: 'POST', headers: { 'user-agent': UA, 'content-type': 'application/x-www-form-urlencoded' }, body: `data=${encodeURIComponent(query)}`, signal: AbortSignal.timeout(150_000) }).catch((error: Error) => error)
        if (response instanceof Response && response.ok) return (await response.json()) as { elements: OverpassWay[] }
        console.log(`  overpass ${name}: ${response instanceof Response ? `HTTP ${response.status}` : response.message} from ${url}, trying again`)
        await new Promise((r) => setTimeout(r, 4000))
      }
    }
    throw new Error(`Overpass would not answer the ${name} query`)
  })
  return answer.elements.filter((e) => e.geometry)
}

const wayLine = (w: OverpassWay): LonLat[] => w.geometry.map((g) => [g.lon, g.lat])

type OsrmRoute = { distance: number; duration: number; geometry: { coordinates: LonLat[] }; legs: { duration: number; distance: number }[] }
type OsrmWaypoint = { location: LonLat; distance: number; waypoint_index?: number; trips_index?: number }

async function osrm(service: 'route' | 'trip' | 'nearest', points: LonLat[], params: Record<string, string> = {}) {
  const coords = points.map((p) => `${p[0].toFixed(6)},${p[1].toFixed(6)}`).join(';')
  const query = new URLSearchParams({ ...(service === 'nearest' ? {} : { overview: 'full', geometries: 'geojson' }), ...params })
  const url = `${OSRM}/${service}/v1/driving/${coords}${query.size ? `?${query}` : ''}`
  const key = createHash('sha1').update(url.replace(OSRM, '')).digest('hex').slice(0, 16)
  return cached(`osrm-${service}-${key}`, async () => {
    const response = await fetch(url)
    const body = (await response.json()) as { code: string; message?: string; routes?: OsrmRoute[]; trips?: OsrmRoute[]; waypoints: OsrmWaypoint[] }
    if (body.code !== 'Ok') throw new Error(`OSRM ${service}: ${body.code} ${body.message ?? ''}`)
    return body
  })
}

async function route(points: LonLat[], params: Record<string, string> = {}) {
  const body = await osrm('route', points, params)
  const r = body.routes![0]
  return { line: r.geometry.coordinates, duration: r.duration, distance: r.distance, legs: r.legs, waypoints: body.waypoints }
}

const snap = async (p: LonLat): Promise<LonLat> => round((await osrm('nearest', [p])).waypoints[0].location)

// ── The base map ─────────────────────────────────────────────────────────────

// The frame of every map scene: from Sant Boi and El Prat's beaches to Nou Barris and the Besòs.
const BBOX = { s: 41.27, w: 2.0, n: 41.47, e: 2.26 }

async function baseMap() {
  const roads = await overpass('roads', `[out:json][timeout:120];way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"](${BBOX.s},${BBOX.w},${BBOX.n},${BBOX.e});out geom;`)
  const classes: Record<string, LonLat[][]> = { major: [], primary: [], minor: [] }
  for (const w of roads) {
    const h = w.tags?.highway ?? ''
    const cls = h === 'motorway' || h === 'trunk' ? 'major' : h === 'primary' ? 'primary' : 'minor'
    const line = tidy(wayLine(w), cls === 'minor' ? 0.012 : 0.008)
    if (line.length >= 2) classes[cls].push(line)
  }
  // The street grid of Poblenou, where chapter 04 comes down to street level.
  const detail = await overpass('detail', `[out:json][timeout:120];way["highway"~"^(residential|unclassified|living_street|pedestrian)$"](41.372,2.168,41.412,2.216);out geom;`)
  const streets = detail.map((w) => tidy(wayLine(w), 0.004)).filter((l) => l.length >= 2)

  const coast = await overpass('coast', `[out:json][timeout:120];way["natural"="coastline"](41.22,1.95,41.50,2.30);out geom;`)
  // Coastline ways run with the land on their left; joined end to end they make one long shore
  // from the south-west to the north-east, plus a few closed rings (breakwaters and islands).
  let chains = coast.map(wayLine)
  for (let joined = true; joined; ) {
    joined = false
    for (const a of chains) {
      const b = chains.find((c) => c !== a && c.length && a.length && c[0][0] === a[a.length - 1][0] && c[0][1] === a[a.length - 1][1])
      if (b) {
        a.push(...b.slice(1))
        b.length = 0
        joined = true
      }
    }
    chains = chains.filter((c) => c.length)
  }
  const closed = (c: LonLat[]) => c[0][0] === c[c.length - 1][0] && c[0][1] === c[c.length - 1][1]
  const shore = chains.filter((c) => !closed(c)).sort((a, b) => b.length - a.length)[0]
  const first = shore[0]
  const last = shore[shore.length - 1]
  // The sea is on the shore's right: close it round the far south-east.
  const sea = tidy([...shore, [2.6, last[1]], [2.6, 40.9], [1.7, 40.9], [1.7, first[1]], first], 0.01)
  const islands = chains.filter(closed).map((c) => tidy(c, 0.008)).filter((c) => c.length > 3)

  const rivers = await overpass('rivers', `[out:json][timeout:120];way["waterway"="river"](41.25,1.98,41.47,2.26);out geom;`)
  const river = (name: string) => rivers.filter((w) => (w.tags?.name ?? '').includes(name)).map((w) => tidy(wayLine(w), 0.01))

  console.log(`roads ${Object.values(classes).map((l) => l.length).join('/')}, streets ${streets.length}, shore ${shore.length} points, islands ${islands.length}`)
  return { roads: { ...classes, streets }, sea, islands, rivers: { llobregat: river('Llobregat'), besos: river('Besòs') } }
}

// ── The arterials the story names ────────────────────────────────────────────

// Waypoints on each road, in one direction; OSRM draws the road between them.
const ARTERIALS: { id: string; name: string; ref?: string; via: LonLat[] }[] = [
  { id: 'litoral', name: 'Ronda Litoral', ref: 'B-10', via: [[2.1235, 41.3505], [2.1562, 41.3523], [2.1830, 41.3809], [2.2020, 41.3921], [2.2185, 41.4075], [2.2105, 41.4335]] },
  { id: 'dalt', name: 'Ronda de Dalt', ref: 'B-20', via: [[2.1005, 41.3770], [2.1180, 41.3930], [2.1300, 41.4060], [2.1485, 41.4205], [2.1700, 41.4380], [2.1905, 41.4475]] },
  { id: 'granvia', name: 'Gran Via', via: [[2.1080, 41.3565], [2.1305, 41.3660], [2.1490, 41.3752], [2.1690, 41.3890], [2.1870, 41.4030], [2.2090, 41.4190]] },
  { id: 'diagonal', name: 'Diagonal', via: [[2.1120, 41.3838], [2.1300, 41.3890], [2.1433, 41.3928], [2.1620, 41.3955], [2.1874, 41.4036], [2.2165, 41.4095]] },
]

async function arterials() {
  const out = []
  for (const a of ARTERIALS) {
    const r = await route(a.via, { continue_straight: 'true' })
    out.push({ id: a.id, name: a.name, ref: a.ref ?? null, line: tidy(r.line, 0.006), km: Math.round(r.distance / 100) / 10 })
    console.log(`arterial ${a.name}: ${(r.distance / 1000).toFixed(1)} km`)
  }
  return out
}

// ── Thirty vans ──────────────────────────────────────────────────────────────

// Thirty morning routes shared by the zones' share of the day's parcels (company.json), largest first.
// V-07 goes to Sant Martí: it is the van chapter 04 follows along the Ronda Litoral.
const VAN_ZONES = ['Z01', 'Z01', 'Z02', 'Z02', 'Z02', 'Z02', 'Z09', 'Z02', 'Z03', 'Z03', 'Z04', 'Z04', 'Z05', 'Z05', 'Z06', 'Z06', 'Z07', 'Z07', 'Z08', 'Z08', 'Z08', 'Z09', 'Z09', 'Z10', 'Z10', 'Z10', 'Z11', 'Z12', 'Z13', 'Z14']

async function vans() {
  const hub = await snap(HUB)
  const out = []
  for (const [i, zoneId] of VAN_ZONES.entries()) {
    const zone = company.zones.find((z) => z.id === zoneId)!
    const nth = VAN_ZONES.slice(0, i).filter((z) => z === zoneId).length
    // A delivery loop round the zone's centre, turned for each van of the zone, on real streets.
    const loop: LonLat[] = []
    const radius = 0.55 + 0.18 * nth
    for (let k = 0; k < 4; k++) {
      const angle = ((nth * 47 + k * 90 + i * 13) * Math.PI) / 180
      const p: LonLat = [zone.lon + (radius * Math.cos(angle)) / KX, zone.lat + (radius * Math.sin(angle)) / KY]
      loop.push(await snap(p))
    }
    const around = await route([...loop, loop[0]])
    const out1 = await route([hub, loop[0]])
    out.push({
      id: `V-${String(i + 1).padStart(2, '0')}`,
      zone: zoneId,
      // Staggered departures from 07:30, the hub's first departure, over a quarter of an hour.
      departMin: Math.round(i * 0.5 * 10) / 10,
      out: { line: tidy(out1.line, 0.004), minutes: Math.round(out1.duration / 6) / 10 },
      loop: { line: tidy(around.line, 0.004), minutes: Math.round(around.duration / 6) / 10 },
    })
  }
  console.log(`vans ${out.length}`)
  return { hub, vans: out }
}

// ── Chapter 01: where the morning goes wrong ─────────────────────────────────

/** One CSV row, with quoted fields that may hold commas. */
function csvRow(row: string): string[] {
  const out: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < row.length; i++) {
    const ch = row[i]
    if (quoted) {
      if (ch === '"' && row[i + 1] === '"') {
        field += '"'
        i++
      } else if (ch === '"') quoted = false
      else field += ch
    } else if (ch === '"') quoted = true
    else if (ch === ',') {
      out.push(field)
      field = ''
    } else field += ch
  }
  out.push(field)
  return out
}

async function incidents(litoral: LonLat[]) {
  // A real loading bay (DUM) in the Eixample: Open Data BCN, zones de càrrega i descàrrega.
  const bays = await cached('dum', async () => {
    const response = await fetch('https://opendata-ajuntament.barcelona.cat/data/api/3/action/package_show?id=zones-carrega-descarrega', { headers: { 'user-agent': UA } })
    const pkg = (await response.json()) as { result: { resources: { format: string; url: string }[] } }
    const csv = pkg.result.resources.find((r) => r.format === 'CSV')!
    const raw = Buffer.from(await (await fetch(csv.url, { headers: { 'user-agent': UA } })).arrayBuffer())
    const text = raw[0] === 0xff && raw[1] === 0xfe ? raw.toString('utf16le') : raw.toString('utf-8')
    const [head, ...rows] = text.replaceAll('\uFEFF', '').split(/\r?\n/).filter(Boolean)
    const cols = csvRow(head)
    const at = (name: string) => cols.indexOf(name)
    return rows.map((r) => {
      const c = csvRow(r)
      return { road: c[at('addresses_road_name')], number: c[at('addresses_start_street_number')], district: c[at('addresses_district_name')], lat: Number(c[at('geo_epgs_4326_lat')]), lon: Number(c[at('geo_epgs_4326_lon')]) }
    })
  })
  const bay = bays.find((b) => b.road === 'C Roger de Llúria' && b.number === '102' && b.district === 'Eixample')
  if (!bay) throw new Error('The Roger de Llúria 102 loading bay is not in the Open Data BCN list any more')
  const glories: LonLat = [2.1874, 41.4036]
  // A door in the Raval, on the Carrer de l'Hospital.
  const raval = await snap([2.1693, 41.3806])
  // The Ronda Litoral nearest Glòries: from the Barceloneta to the Llacuna exit.
  const a = along(litoral, [2.1782, 41.3748])
  const b = along(litoral, [2.2020, 41.3921])
  return {
    bay: { lon: bay.lon, lat: bay.lat, address: `Carrer de Roger de Llúria, ${bay.number}` },
    jam: tidy(slice(litoral, a, b), 0.003),
    glories,
    raval: { lon: raval[0], lat: raval[1], street: 'Carrer de l’Hospital' },
  }
}

// ── Chapter 04: one ping, one re-plan ────────────────────────────────────────

async function ping(litoral: LonLat[]) {
  // V-07, north-east bound on the Ronda Litoral by the Vila Olímpica, crawling since the Barceloneta.
  const vanKm = along(litoral, [2.185229, 41.381673])
  const van = litoral[litoral.findIndex((p) => dist(p, [2.185229, 41.381673]) < 0.02)] ?? [2.185229, 41.381673]
  const ahead = slice(litoral, vanKm, vanKm + 0.2)
  const heading = bearing(ahead[0], ahead[ahead.length - 1])
  const crawl = slice(litoral, vanKm - 0.9, vanKm)
  const jam = slice(litoral, vanKm, along(litoral, [2.2020, 41.3921]))

  // Fourteen stops left, in Poblenou and the 22@: points on a loose grid, each moved to its street.
  const stops: LonLat[] = []
  let seed = 7
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
  while (stops.length < 14) {
    const p: LonLat = [2.1905 + rand() * 0.0175, 41.3895 + rand() * 0.0150]
    // Keep to the land side of the Litoral and away from the other stops.
    if (p[1] < 41.3905 + (p[0] - 2.19) * 0.75) continue
    const s = await snap(p)
    if (stops.every((q) => dist(q, s) > 0.22)) stops.push(s)
  }
  const exitLlacuna: LonLat = [2.202005, 41.39209]
  const exitMarina: LonLat = [2.193023, 41.385185]

  // The plan made at dawn: stay on the Litoral to the Llacuna exit, then the stops east to west.
  const plannedOrder = stops.map((_, i) => i).sort((a, b) => stops[b][0] - stops[a][0])
  const planned = await route([van, exitLlacuna, ...plannedOrder.map((i) => stops[i])], { bearings: [`${heading},20`, `${bearing(exitLlacuna, [2.2027, 41.3925])},30`, ...plannedOrder.map(() => '')].join(';') })

  // The re-plan: leave at the Marina exit, before the jam, and let OSRM order the stops on real
  // road times (its trip service: a travelling-salesman heuristic over the road network).
  const trip = await osrm('trip', [exitMarina, ...stops], { source: 'first', roundtrip: 'true' })
  const replannedOrder = trip.waypoints
    .map((w, i) => ({ i, at: w.waypoint_index! }))
    .filter((w) => w.i > 0)
    .sort((a, b) => a.at - b.at)
    .map((w) => w.i - 1)
  const replanned = await route([van, exitMarina, ...replannedOrder.map((i) => stops[i])], { bearings: [`${heading},20`, '', ...replannedOrder.map(() => '')].join(';') })

  console.log(`ping: planned ${(planned.distance / 1000).toFixed(1)} km, re-planned ${(replanned.distance / 1000).toFixed(1)} km`)
  return {
    van: { lon: van[0], lat: van[1], heading },
    crawl: tidy(crawl, 0.002),
    jam: tidy(jam, 0.002),
    stops: stops.map(([lon, lat]) => ({ lon, lat })),
    planned: { order: plannedOrder, line: tidy(planned.line, 0.002) },
    replanned: { order: replannedOrder, line: tidy(replanned.line, 0.002) },
  }
}

// ── All together ─────────────────────────────────────────────────────────────

const base = await baseMap()
const lines = await arterials()
const fleet = await vans()
const litoral = (await route([[2.1562, 41.3523], [2.2020, 41.3921], [2.2185, 41.4075]], { continue_straight: 'true' })).line
const map = {
  about:
    'Generated by scripts/map.ts. Roads, coastline and rivers: OpenStreetMap contributors (ODbL), through the Overpass API. Routes: OSRM on the OpenStreetMap Catalonia extract. Loading bay: Open Data BCN (CC BY 4.0). Hub, zones and fleet: company.json (AI-generated, prompt 001). Coordinates are [lon, lat].',
  bbox: BBOX,
  ...base,
  arterials: lines,
  hub: fleet.hub,
  zones: company.zones.map((z) => ({ id: z.id, name: z.name, lon: z.lon, lat: z.lat })),
  vans: fleet.vans,
  incidents: await incidents(litoral),
  ping: await ping(litoral),
}
writeFileSync(OUT, JSON.stringify(map) + '\n')
console.log(`src/data/map.json  ${(JSON.stringify(map).length / 1024).toFixed(0)} KB`)
