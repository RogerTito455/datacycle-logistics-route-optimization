// The logo and a small set of line icons, drawn here so every interface in the video is code.

import type { CSSProperties } from 'react'
import { C } from './theme'

/** The river-delta mark: an orange triangle with a smaller chevron inside, in the text colour. */
export function Mark({ size, color = C.orange, inner = C.ink, stroke = 3.6 }: { size: number; color?: string; inner?: string; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" style={{ display: 'block', overflow: 'visible' }}>
      <path d="M24 5 L44.5 41 H3.5 Z" stroke={color} strokeWidth={stroke} strokeLinejoin="round" />
      <path d="M15 34.5 L24 20 L33 34.5" stroke={inner} strokeWidth={stroke} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

/** The mark and the wordmark, side by side or stacked. */
export function Logo({ size, stacked = false, style }: { size: number; stacked?: boolean; style?: CSSProperties }) {
  return (
    <div style={{ display: 'flex', flexDirection: stacked ? 'column' : 'row', alignItems: 'center', gap: stacked ? size * 0.28 : size * 0.3, ...style }}>
      <Mark size={size} stroke={stacked ? 3 : 3.6} />
      <Wordmark size={stacked ? size * 0.62 : size * 0.72} />
    </div>
  )
}

export function Wordmark({ size, color = C.ink }: { size: number; color?: string }) {
  return (
    <span style={{ fontFamily: 'inherit', display: 'inline-flex', gap: size * 0.28, whiteSpace: 'nowrap' }}>
      <span style={{ color }}>LLOBREGAT</span>
      <span style={{ color: C.orange }}>EXPRESS</span>
    </span>
  )
}

// 24 × 24 line icons, 2 px strokes, round caps.
const PATHS: Record<string, string> = {
  van: 'M2 7h11v9H2z M13 10h4.5l3.5 3.5V16h-8 M6 19a2 2 0 1 0 0-4a2 2 0 0 0 0 4z M17 19a2 2 0 1 0 0-4a2 2 0 0 0 0 4z',
  car: 'M4 16v-3l2-5h12l2 5v3 M3 16h18v2H3z M7.5 16v2.5 M16.5 16v2.5 M7 13h.01 M17 13h.01',
  rain: 'M7 15a4.5 4.5 0 1 1 1.2-8.8A6 6 0 0 1 19 8.5a3.5 3.5 0 0 1-.5 6.5z M8 18l-1 3 M12 18l-1 3 M16 18l-1 3',
  door: 'M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17 M3 21h18 M14.5 12h.01',
  jam: 'M3 12h4 M10 12h4 M17 12h4 M5 7l-2 5 2 5 M19 7l2 5-2 5',
  pin: 'M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z M12 12a2.5 2.5 0 1 0 0-5a2.5 2.5 0 0 0 0 5z',
  clock: 'M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18z M12 7v5l3 2',
  signal: 'M5 12a7 7 0 0 1 14 0 M8.5 12a3.5 3.5 0 0 1 7 0 M12 12v9 M12 12h.01',
  road: 'M8 3L4 21 M16 3l4 18 M12 4v3 M12 10v4 M12 17v3',
  cloud: 'M7 18a4.5 4.5 0 1 1 1.2-8.8A6 6 0 0 1 19 11.5a3.5 3.5 0 0 1-.5 6.5z',
  database: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6 M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  stream: 'M3 8h12 M3 12h18 M3 16h9 M18 5l3 3-3 3',
  batch: 'M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z',
  gauge: 'M4 18a8 8 0 1 1 16 0 M12 18l4-6 M7 18h.01 M17 18h.01',
  route: 'M6 20a2 2 0 1 0 0-4a2 2 0 0 0 0 4z M18 8a2 2 0 1 0 0-4a2 2 0 0 0 0 4z M6 16V11a3 3 0 0 1 3-3h7 M18 8v5a3 3 0 0 1-3 3H8',
  archive: 'M3 4h18v4H3z M5 8v12h14V8 M10 12h4',
  cog: 'M12 15a3 3 0 1 0 0-6a3 3 0 0 0 0 6z M19 12l2-1-1-3-2 .3-1.3-1.3.3-2-3-1-1 2h-2l-1-2-3 1 .3 2L6 7.3 4 7 3 10l2 1v2l-2 1 1 3 2-.3 1.3 1.3-.3 2 3 1 1-2h2l1 2 3-1-.3-2 1.3-1.3 2 .3 1-3-2-1z',
  sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z M19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z',
  globe: 'M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18z M3 12h18 M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  x: 'M6 6l12 12 M18 6L6 18',
  terminal: 'M4 5h16v14H4z M7 9l3 3-3 3 M12 15h5',
  user: 'M12 12a4 4 0 1 0 0-8a4 4 0 0 0 0 8z M4 21a8 8 0 0 1 16 0',
  file: 'M6 3h8l4 4v14H6z M14 3v4h4 M9 12h6 M9 16h6',
  flag: 'M5 21V4 M5 4h11l-2 4 2 4H5',
  arrow: 'M4 12h15 M14 7l5 5-5 5',
  parcel: 'M3 7.5L12 3l9 4.5v9L12 21l-9-4.5z M3 7.5l9 4.5 9-4.5 M12 12v9 M7.5 5.2l9 4.5',
  map: 'M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z M9 3v15 M15 6v15',
  layers: 'M12 3l9 5-9 5-9-5z M3 13l9 5 9-5 M3 17.5l9 5 9-5',
  timer: 'M12 21a8 8 0 1 0 0-16a8 8 0 0 0 0 16z M12 9v4l2.5 1.5 M9 2h6',
}

export function Icon({ name, size = 24, color = C.ink, stroke = 2, style }: { name: keyof typeof PATHS | string; size?: number; color?: string; stroke?: number; style?: CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block', flex: 'none', ...style }}>
      <path d={PATHS[name] ?? PATHS.x} />
    </svg>
  )
}
