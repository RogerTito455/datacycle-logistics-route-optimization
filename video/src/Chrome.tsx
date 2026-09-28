// What stays on screen across scenes: the brand, the chapter and its progress, the clock, the honesty
// chips, the source line and the subtitles.

import type { ReactNode } from 'react'
import { SHOW_IN_DEVELOPMENT } from './config'
import { Icon, Mark } from './Icon'
import { ALL_LINES, CHAPTERS, SCENES, type TimedLine } from './timeline'
import { C, DISPLAY, clamp01, fade, mono, text } from './theme'

export function Header({ f, sceneId }: { f: number; sceneId: string }) {
  const chapter = CHAPTERS.find(([, , ids]) => ids.includes(sceneId)) ?? CHAPTERS[0]
  const intro = fade(f - 4, 14)
  return (
    <div style={{ position: 'absolute', left: 48, right: 48, top: 34, opacity: intro, zIndex: 40 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 20px 8px 14px', borderRadius: 999, background: 'rgba(21,30,27,0.92)', border: `1px solid ${C.line}` }}>
          <Mark size={26} stroke={4} />
          <span style={{ fontFamily: DISPLAY, fontWeight: 800, fontSize: 26, letterSpacing: 1, color: C.ink, fontVariationSettings: "'opsz' 72", lineHeight: 1 }}>
            LLOBREGAT <span style={{ color: C.orange }}>EXPRESS</span>
          </span>
        </div>
        {chapter[0] && (
          <div key={chapter[0]} style={{ display: 'flex', alignItems: 'baseline', gap: 12, opacity: fade(f - chapterStart(chapter[2]), 10) }}>
            <span style={mono(20, 600, C.orange)}>{chapter[0]}</span>
            <span style={text(24, 600, C.muted)}>{chapter[1]}</span>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 16, height: 4 }}>
        {CHAPTERS.map(([num, , ids]) => {
          const inChapter = SCENES.filter((s) => ids.includes(s.id))
          const a = inChapter[0].start
          const b = inChapter[inChapter.length - 1].end
          return (
            <div key={num || 'close'} style={{ flex: b - a, borderRadius: 2, background: 'rgba(147,162,155,0.16)', overflow: 'hidden' }}>
              <div style={{ width: `${clamp01((f - a) / (b - a)) * 100}%`, height: '100%', background: C.muted }} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

const chapterStart = (ids: string[]) => SCENES.find((s) => ids.includes(s.id))?.start ?? 0

/** The time of day on the map scenes: the one number that says where in the morning you are. */
export function Clock({ time, label, opacity }: { time: string; label: string; opacity: number }) {
  if (opacity <= 0) return null
  return (
    <div style={{ position: 'absolute', right: 48, top: 26, textAlign: 'right', opacity, zIndex: 40 }}>
      <div style={{ ...mono(58, 600, C.ink), lineHeight: 1.05 }}>{time}</div>
      <div style={{ ...mono(17, 500, C.muted), marginTop: 2 }}>{label}</div>
    </div>
  )
}

/** A small pill: what kind of thing the viewer is looking at. */
export function Chip({ children, color, icon, dashed = false, size = 17 }: { children: ReactNode; color: string; icon?: string; dashed?: boolean; size?: number }) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '5px 14px 5px 11px', borderRadius: 999, border: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`, background: 'rgba(13,20,18,0.88)', whiteSpace: 'nowrap', ...mono(size, 500, color) }}>
      {icon && <Icon name={icon} size={size + 2} color={color} />}
      {children}
    </div>
  )
}

export const SimulatedChip = () => (
  <Chip color={C.amber} icon="van">
    Simulated fleet on real roads
  </Chip>
)

/** Parts that are designed but not built yet. `SHOW_IN_DEVELOPMENT` in config.ts turns them all off. */
export function DevChip({ milestone, size }: { milestone: string; size?: number }) {
  if (!SHOW_IN_DEVELOPMENT) return null
  return (
    <Chip color={C.amber} icon="timer" dashed size={size}>
      In development · {milestone}
    </Chip>
  )
}

// Which chips each scene carries at the top right. Vans on screen: simulated. Unbuilt parts: in development.
const TAGS: Record<string, { simulated?: boolean; dev?: string }> = {
  open: { simulated: true },
  incidents: { simulated: true },
  cascade: { simulated: true },
  ping: { simulated: true, dev: 'M2/M3' },
  lineage: { dev: 'M2' },
}

export function Tags({ f, sceneId, clock }: { f: number; sceneId: string; clock: boolean }) {
  const tags = TAGS[sceneId]
  const s = SCENES.find((x) => x.id === sceneId)
  if (!tags || !s) return null
  const opacity = Math.min(fade(f - s.start - 4, 10), fade(s.end - f, 6))
  return (
    <div style={{ position: 'absolute', right: 48, top: clock ? 136 : 40, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10, opacity, zIndex: 41 }}>
      {tags.simulated && <SimulatedChip />}
      {tags.dev && <DevChip milestone={tags.dev} />}
    </div>
  )
}

// Where the data each scene shows comes from, in one line at the bottom left.
const SOURCES: Record<string, string> = {
  open: 'Hub, zones and fleet: company profile, AI-generated (prompt 001), validated against OpenStreetMap. Roads: OSRM on OpenStreetMap (ODbL). Vans: simulated.',
  incidents: 'Incidents illustrative, at real places. Loading bay: Open Data BCN, zones de càrrega i descàrrega (CC BY 4.0). Roads: OpenStreetMap (ODbL).',
  cascade: 'Illustrative route. Stops per route, minutes per stop and 2-hour windows: company profile, AI-generated (prompt 001).',
  kpi: 'Company profile, AI-generated (prompt 001): baseline 361 min, target 330 min, over 40 weekday routes. KPI definition: docs/phases/1-case.md.',
  brand: 'Datacycle · Unit 1 · Case 3, Logistics (Route Optimization). Architecture: docs/decisions/0001-architecture-baseline.md.',
  pipeline: 'Architecture: ADR 0001. GPS every 5 s (simulated), traffic state every 5 min (Open Data BCN, CC BY 4.0), weather hourly (Open-Meteo, CC BY 4.0).',
  ping: 'Ping: simulated fleet on OSRM roads (OpenStreetMap). Jam pattern: company profile risks (Ronda Litoral, 07:30–09:30). Re-plan: OSRM trip, illustrative.',
  compare: 'What each kind of tool is built to do. Two-hour delivery windows: company profile (prompt 001).',
  lineage: 'Lineage and the three metadata elements on every table: ADR 0001, decision 20. Model names as planned for M2.',
  origins: 'Open Data BCN (CC BY 4.0), Open-Meteo (CC BY 4.0), OpenStreetMap (ODbL). Prompts: prompts/. Validator: services/generator/validate_company.py.',
  smoke: 'Measured 28 September 2026 with every service idle: 1.8 GB of RAM for nine services. Smoke test: scripts/smoke-test.sh. CI: .github/workflows/ci.yml.',
}

export function SceneSources({ f }: { f: number }) {
  const s = [...SCENES].reverse().find((x) => f >= x.start)
  const words = s && SOURCES[s.id]
  if (!s || !words) return null
  const opacity = Math.min(fade(f - s.start - 6, 10), fade(s.end - f, 8))
  return <div style={{ position: 'absolute', left: 48, right: 48, bottom: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', opacity, ...mono(15, 400, C.muted), zIndex: 60 }}>{words}</div>
}

/** The line being said; its words light up as they are spoken. */
export function Subtitles({ f }: { f: number }) {
  const current = [...ALL_LINES].reverse().find((l) => f >= l.at - 3)
  if (!current) return null
  const next = ALL_LINES[ALL_LINES.indexOf(current) + 1]
  const until = Math.min(current.at + current.frames + 14, next ? next.at - 3 : Infinity)
  if (f > until) return null
  const opacity = Math.min(fade(f - current.at + 3, 5), fade(until - f, 5))
  return (
    <div style={{ position: 'absolute', left: 160, right: 160, bottom: 46, display: 'flex', justifyContent: 'center', zIndex: 50, opacity }}>
      <div style={{ maxWidth: 1480, padding: '12px 30px 14px', borderRadius: 16, background: 'rgba(13,20,18,0.88)', border: `1px solid ${C.line}`, textAlign: 'center' }}>
        <Karaoke line={current} f={f} />
      </div>
    </div>
  )
}

function Karaoke({ line, f }: { line: TimedLine; f: number }) {
  const ms = ((f - line.at) / 30) * 1000
  return (
    <span style={text(38, 600, C.faint)}>
      {line.words.map((w, i) => (
        <span key={i} style={{ color: ms >= w.startMs - 40 ? C.ink : '#6F7F78' }}>
          {w.text}
          {i < line.words.length - 1 ? ' ' : ''}
        </span>
      ))}
    </span>
  )
}
