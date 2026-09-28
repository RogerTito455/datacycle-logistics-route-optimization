// The video's look, from the team's landing page: a dark green-black ground, one orange for the brand
// and for every action, blue for what streams, and the traffic colours for how the day is going.

import { loadFont as loadDisplay } from '@remotion/google-fonts/BigShoulders'
import { loadFont as loadMono } from '@remotion/google-fonts/IBMPlexMono'
import { loadFont as loadSans } from '@remotion/google-fonts/IBMPlexSans'
import type { CSSProperties } from 'react'
import { spring } from 'remotion'

export const FPS = 30
export const W = 1920
export const H = 1080

// Big Shoulders is one variable family now; its display cut is the 72 pt optical size.
export const DISPLAY = loadDisplay('normal', { weights: ['700', '800'], subsets: ['latin', 'latin-ext'] }).fontFamily
export const SANS = loadSans('normal', { weights: ['400', '500', '600', '700'], subsets: ['latin', 'latin-ext'] }).fontFamily
export const MONO = loadMono('normal', { weights: ['400', '500', '600', '700'], subsets: ['latin', 'latin-ext'] }).fontFamily

export const C = {
  ground: '#0D1412',
  panel: '#151E1B',
  line: '#24302B',
  ink: '#E3E9E5',
  muted: '#93A29B',
  faint: '#5E6D66',
  orange: '#F2703A',
  blue: '#5B9BE6',
  green: '#4CB782',
  amber: '#E0A43A',
  red: '#EF5E4E',
  sea: '#0F1B1D',
  road: '#1E2925',
  roadMajor: '#2B3833',
} as const

export const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
/** Cubic in-out, for camera moves and anything that travels. */
export const ease = (v: number) => {
  const t = clamp01(v)
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}
export const easeOut = (v: number) => 1 - Math.pow(1 - clamp01(v), 3)
export const easeIn = (v: number) => Math.pow(clamp01(v), 2.2)
export const sp = (t: number, damping = 14, stiffness = 180) => spring({ frame: t, fps: FPS, config: { damping, stiffness } })

/** Rise and settle, for anything that appears. */
export const pop = (t: number): CSSProperties => {
  const s = sp(t)
  return { opacity: clamp01(s * 1.6), transform: `translateY(${22 * (1 - Math.min(1, s))}px) scale(${0.94 + 0.06 * Math.min(1.03, s)})` }
}

export const fade = (t: number, frames = 8) => clamp01(t / frames)

export const display = (size: number, color: string = C.ink): CSSProperties => ({
  fontFamily: DISPLAY,
  fontWeight: 800,
  fontSize: size,
  color,
  lineHeight: 0.92,
  textTransform: 'uppercase',
  letterSpacing: size > 80 ? 1 : 0.5,
  fontVariationSettings: "'opsz' 72",
})

export const text = (size: number, weight = 500, color: string = C.ink): CSSProperties => ({
  fontFamily: SANS,
  fontWeight: weight,
  fontSize: size,
  color,
  lineHeight: 1.25,
})

export const mono = (size: number, weight = 500, color: string = C.muted): CSSProperties => ({
  fontFamily: MONO,
  fontWeight: weight,
  fontSize: size,
  color,
  lineHeight: 1.3,
  fontVariantNumeric: 'tabular-nums',
})

/** hh:mm for minutes after midnight. */
export const hhmm = (minutes: number) => {
  const m = Math.floor(minutes)
  return `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}
