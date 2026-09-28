// When everything happens, measured from the narration: each line starts after the one before it, so
// changing a line's words moves everything after it and nothing needs retiming by hand. Visual beats
// hang off words (`beat('kpi-2', 'six')`), so they land on the word being said.

import narration from './data/narration.json'
import { FPS } from './theme'

type Word = { text: string; startMs: number; endMs: number }
type NarrationLine = { id: string; scene: string; speaker: 'narrator'; text: string; file: string; durationMs: number; words: Word[] }

export type TimedLine = NarrationLine & { at: number; frames: number }
export type Scene = { id: string; start: number; end: number; lines: TimedLine[] }

export const frames = (ms: number) => Math.round((ms / 1000) * FPS)

// Frames before a scene's first line: room for a picture or a camera move to arrive first.
const LEAD: Record<string, number> = { open: 30, incidents: 6, cascade: 12, kpi: 16, brand: 22, pipeline: 18, ping: 44, compare: 18, lineage: 16, origins: 12, smoke: 16, close: 18 }
// Frames after a scene's last line, before the next scene: a picture that needs to be seen.
const HOLD: Record<string, number> = { open: 8, incidents: 14, cascade: 40, kpi: 44, brand: 16, pipeline: 84, ping: 54, compare: 44, lineage: 50, origins: 36, smoke: 54, close: 120 }
const GAP = 6 // between two sentences
// A longer breath after some lines, where the picture has something to finish.
const AFTER: Record<string, number> = { 'open-0': 10, 'open-1': 14, 'kpi-0': 10, 'kpi-1': 18, 'pipeline-1': 8, 'pipeline-3': 10, 'ping-0': 16, 'ping-1': 14, 'ping-2': 14, 'compare-1': 8, 'compare-2': 10, 'origins-0': 8 }

const LINES = (narration as { lines: NarrationLine[] }).lines

export const SCENES: Scene[] = (() => {
  const ids = [...new Set(LINES.map((l) => l.scene))]
  let start = 0
  return ids.map((id) => {
    let t = start + (LEAD[id] ?? 8)
    const lines = LINES.filter((l) => l.scene === id).map((l, i, all) => {
      if (i > 0) t += GAP + (AFTER[all[i - 1].id] ?? 0)
      const line = { ...l, at: t, frames: frames(l.durationMs) }
      t += line.frames
      return line
    })
    const scene = { id, start, end: t + (HOLD[id] ?? 8), lines }
    start = scene.end
    return scene
  })
})()

export const TOTAL = SCENES[SCENES.length - 1].end
export const ALL_LINES = SCENES.flatMap((s) => s.lines)

export const scene = (id: string) => {
  const found = SCENES.find((s) => s.id === id)
  if (!found) throw new Error(`No scene ${id}`)
  return found
}

export const line = (id: string) => {
  const found = ALL_LINES.find((l) => l.id === id)
  if (!found) throw new Error(`No line ${id}`)
  return found
}

/** The frame a word starts on: the first word of `id` that starts with `word`, case-insensitive. */
export const beat = (id: string, word: string, nth = 0) => {
  const l = line(id)
  const matches = l.words.filter((w) => w.text.toLowerCase().replace(/[^\p{L}\p{N}'-]/gu, '').startsWith(word.toLowerCase()))
  const w = matches[nth]
  if (!w) throw new Error(`No word "${word}" in ${id}`)
  return l.at + frames(w.startMs)
}

export const lineEnd = (id: string) => {
  const l = line(id)
  return l.at + l.frames
}

// Chapters: the number says where you are in the story, the bar how much is left. The close has no
// number: it is the end card.
export const CHAPTERS: [string, string, string[]][] = [
  ['01', 'The morning plan', ['open', 'incidents', 'cascade']],
  ['02', 'One number', ['kpi']],
  ['03', 'The platform', ['brand', 'pipeline']],
  ['04', 'From a ping to a decision', ['ping']],
  ['05', 'Why not a map app', ['compare']],
  ['06', 'Built to be checked', ['lineage', 'origins', 'smoke']],
  ['', '', ['close']],
]
