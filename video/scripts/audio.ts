// The video's audio, from ElevenLabs: one clip per line of src/script.json, a few sound effects and
// the music. Run from video/:
//
//   node scripts/audio.ts lines      the narration, plus src/data/narration.json   (pnpm voice)
//   node scripts/audio.ts verify     each clip's word timings against its text, no API call
//   node scripts/audio.ts sfx        public/audio/sfx/*.mp3                         (pnpm sfx)
//   node scripts/audio.ts music      public/audio/music.mp3 (200 s, or the seconds given) and its loudness curve
//   node scripts/audio.ts envelope   src/data/music-envelope.json only, from the music there is
//   node scripts/audio.ts check      the plan's remaining characters                (pnpm audio:check)
//
// Every generation spends the plan's characters, so a line is only regenerated when its text, voice
// or settings change (a hash in narration.json), and a sound or the music only when its file is gone.
// The key is ELEVENLABS_API_KEY in the environment, or in video/.env (git-ignored); it is never printed.

import { execFileSync, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const PUBLIC = join(ROOT, 'public')
const NARRATION = join(ROOT, 'src/data/narration.json')
const API = 'https://api.elevenlabs.io'
const MODEL = 'eleven_multilingual_v2'

type Speaker = 'narrator'
type Voice = { id: string; name: string; settings: Record<string, number | boolean> }
// `say`, when set, is what the voice reads instead of `text` (a spelling for pronunciation); the screen
// still shows `text`, word for word, so both must have the same number of words.
type ScriptLine = { speaker: Speaker; text: string; say?: string }
type Script = { voices: Record<Speaker, Voice>; scenes: { id: string; lines: ScriptLine[] }[] }
export type Word = { text: string; startMs: number; endMs: number; said?: string }
export type NarrationLine = ScriptLine & { id: string; scene: string; file: string; durationMs: number; words: Word[]; hash: string }

function apiKey(): string {
  if (process.env.ELEVENLABS_API_KEY) return process.env.ELEVENLABS_API_KEY
  const file = join(ROOT, '.env')
  const key = existsSync(file) ? readFileSync(file, 'utf-8').match(/^ELEVENLABS_API_KEY=\s*"?([^"\s]+)/m)?.[1] : undefined
  if (!key) throw new Error('No ELEVENLABS_API_KEY in the environment or in video/.env')
  return key
}

async function call(path: string, body?: object): Promise<Response> {
  const response = await fetch(API + path, {
    method: body ? 'POST' : 'GET',
    headers: { 'xi-api-key': apiKey(), 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw new Error(`ElevenLabs ${path}: HTTP ${response.status} ${(await response.text()).slice(0, 300)}`)
  return response
}

function ffmpeg(args: string[]): void {
  execFileSync('ffmpeg', ['-y', '-v', 'error', ...args])
}

function durationMs(file: string): number {
  const out = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file])
  return Math.round(Number(out.toString().trim()) * 1000)
}

const FILTER: Record<Speaker, string> = {
  narrator: 'loudnorm=I=-16:TP=-1.5:LRA=11',
}

function words(chars: string[], starts: number[], ends: number[], offset: number): Word[] {
  const out: Word[] = []
  let current: Word | null = null
  chars.forEach((char, i) => {
    if (/\s/.test(char)) {
      current = null
      return
    }
    if (!current) {
      current = { text: '', startMs: Math.max(0, Math.round((starts[i] - offset) * 1000)), endMs: 0 }
      out.push(current)
    }
    current.text += char
    current.endMs = Math.round((ends[i] - offset) * 1000)
  })
  return out
}

const readScript = (): Script => JSON.parse(readFileSync(join(ROOT, 'src/script.json'), 'utf-8'))
const count = (s: string) => s.trim().split(/\s+/).length

async function lines(): Promise<void> {
  const script = readScript()
  // A `say` with a different number of words would break the subtitles: refuse before spending anything.
  const uneven = script.scenes.flatMap((s) => s.lines.map((l, i) => ({ id: `${s.id}-${i}`, l }))).filter(({ l }) => l.say && count(l.say) !== count(l.text))
  if (uneven.length) throw new Error(`\`say\` and \`text\` differ in word count: ${uneven.map((u) => u.id).join(', ')}`)

  const previous: NarrationLine[] = existsSync(NARRATION) ? JSON.parse(readFileSync(NARRATION, 'utf-8')).lines : []
  const out: NarrationLine[] = []
  mkdirSync(join(PUBLIC, 'audio/lines'), { recursive: true })
  mkdirSync(dirname(NARRATION), { recursive: true })

  for (const scene of script.scenes) {
    for (const [index, line] of scene.lines.entries()) {
      const id = `${scene.id}-${index}`
      const file = `audio/lines/${id}.mp3`
      const voice = script.voices[line.speaker]
      const hash = createHash('sha1').update(JSON.stringify([MODEL, voice.id, voice.settings, line.say ?? line.text, FILTER[line.speaker]])).digest('hex').slice(0, 12)
      const kept = previous.find((p) => p.id === id && p.hash === hash)
      if (kept && existsSync(join(PUBLIC, file))) {
        out.push({ ...kept, ...line, id, scene: scene.id, file, words: kept.words.map((w, i) => ({ ...w, text: line.text.split(/\s+/)[i] })) })
        continue
      }
      const answer = (await (
        await call(`/v1/text-to-speech/${voice.id}/with-timestamps?output_format=mp3_44100_128`, {
          text: line.say ?? line.text,
          model_id: MODEL,
          voice_settings: voice.settings,
        })
      ).json()) as { audio_base64: string; alignment: { characters: string[]; character_start_times_seconds: number[]; character_end_times_seconds: number[] } }
      const { characters, character_start_times_seconds: starts, character_end_times_seconds: ends } = answer.alignment
      const raw = join(PUBLIC, `audio/lines/${id}.raw.mp3`)
      writeFileSync(raw, Buffer.from(answer.audio_base64, 'base64'))
      // Cut the clip to the voice, a breath either side, so the timeline measures speech, not silence.
      const spoken = characters.map((c, i) => (/\s/.test(c) ? -1 : i)).filter((i) => i >= 0)
      const from = Math.max(0, starts[spoken[0]] - 0.05)
      const to = ends[spoken[spoken.length - 1]] + 0.15
      ffmpeg(['-i', raw, '-af', `atrim=start=${from}:end=${to},asetpts=PTS-STARTPTS,${FILTER[line.speaker]}`, '-ar', '44100', '-ac', '2', '-b:a', '192k', join(PUBLIC, file)])
      rmSync(raw)
      const timed = words(characters, starts, ends, from)
      const shown = line.text.split(/\s+/)
      if (timed.length !== shown.length) throw new Error(`${id}: the alignment has ${timed.length} words, the text ${shown.length}`)
      const entry: NarrationLine = {
        id,
        scene: scene.id,
        ...line,
        file,
        durationMs: durationMs(join(PUBLIC, file)),
        words: timed.map((w, i) => ({ ...w, text: shown[i], said: w.text })),
        hash,
      }
      out.push(entry)
      console.log(`${id}  ${(entry.durationMs / 1000).toFixed(2)} s  ${line.text.slice(0, 60)}`)
    }
  }
  writeFileSync(NARRATION, JSON.stringify({ about: 'Generated by scripts/audio.ts from script.json. Do not edit.', lines: out }, null, 1) + '\n')
  const total = out.reduce((sum, l) => sum + l.durationMs, 0)
  console.log(`${out.length} lines, ${(total / 1000).toFixed(1)} s of speech`)
  verify()
}

/** Every clip's word timings against its text, from the with-timestamps alignment: the words the voice
 * was given must be the words aligned, in order, and no word may take an absurd time for its length. */
function verify(): void {
  const { lines: all } = JSON.parse(readFileSync(NARRATION, 'utf-8')) as { lines: (NarrationLine & { words: (Word & { said?: string })[] })[] }
  let flagged = 0
  for (const l of all) {
    const given = (l.say ?? l.text).split(/\s+/)
    const problems: string[] = []
    l.words.forEach((w, i) => {
      if (w.said !== undefined && w.said !== given[i]) problems.push(`word ${i} aligned as "${w.said}", sent "${given[i]}"`)
      // A spelled-out acronym (K-P-I) is said letter by letter: each letter counts as a short word.
      const said = w.said ?? w.text
      const spelled = /^(\p{Lu}-)+\p{Lu}\W*$/u.test(said) || /-(\p{Lu}-)*\p{Lu}\W*$/u.test(said)
      const letters = (said.replace(/[^\p{L}\p{N}]/gu, '').length || 1) * (spelled ? 2.5 : 1)
      const ms = w.endMs - w.startMs
      const perLetter = ms / letters
      const tooShort = letters >= 3 ? ms < 60 : ms < 15
      if (tooShort || perLetter > 260 || (letters > 3 && perLetter < 25)) problems.push(`"${w.text}" ${ms} ms for ${letters} letters`)
      const next = l.words[i + 1]
      const pause = next ? next.startMs - w.endMs : 0
      if (pause > (/[.,;:]$/.test(w.text) ? 1200 : 700)) problems.push(`${pause} ms pause after "${w.text}"`)
      if (pause < -30) problems.push(`"${next.text}" starts before "${w.text}" ends`)
    })
    const last = l.words[l.words.length - 1]
    if (last.endMs > l.durationMs) problems.push(`last word ends at ${last.endMs} ms, clip is ${l.durationMs} ms`)
    if (problems.length) {
      flagged++
      console.log(`${l.id}: ${problems.join('; ')}`)
    }
  }
  console.log(`verify: ${all.length} clips, ${flagged} flagged`)
}

// Short sounds for the edit. Kept synthetic and quiet: the video's world is an interface and a map.
const SFX: Record<string, [string, number]> = {
  whoosh: ['soft clean digital whoosh, airy transition swipe, no music', 0.8],
  blip: ['soft user interface blip, short bright confirmation tone', 0.5],
  tick: ['tiny digital data tick, crisp short click, interface', 0.5],
  hit: ['deep soft cinematic sub bass impact, short, clean', 1.4],
  scan: ['soft digital scanning sweep, gentle shimmer rising', 1.2],
  rain: ['light rain beginning to fall on a city street, soft steady patter, no thunder, no traffic', 3.0],
  horn: ['a single short car horn beep in a city street, distant, slightly muffled', 0.8],
  keys: ['fast quiet mechanical keyboard typing, a short burst of keystrokes', 1.2],
  chime: ['two-note soft positive success chime, clean synth, interface', 1.0],
}

async function sfx(): Promise<void> {
  mkdirSync(join(PUBLIC, 'audio/sfx'), { recursive: true })
  for (const [name, [prompt, seconds]] of Object.entries(SFX)) {
    const file = join(PUBLIC, `audio/sfx/${name}.mp3`)
    if (existsSync(file)) continue
    const audio = await (await call('/v1/sound-generation', { text: prompt, duration_seconds: seconds, prompt_influence: 0.5 })).arrayBuffer()
    writeFileSync(file, Buffer.from(audio))
    console.log(`sfx/${name}.mp3  ${seconds} s`)
  }
}

const MUSIC_PROMPT =
  'Instrumental underscore for a calm, precise technology explainer about a city delivery fleet and live data. ' +
  'Pulsing synth arpeggios, warm analog bass, soft electronic percussion at 105 BPM, light airy pads. ' +
  'Opens quiet and curious like an early morning, builds a steady forward momentum, lifts into a bright, ' +
  'confident resolution near the end. Modern and understated, no vocals, no drops, no cheesy EDM.'

// Longer than the video: a track that ends early leaves the close in silence.
async function music(seconds = Number(process.argv[3] ?? 200)): Promise<void> {
  const file = join(PUBLIC, 'audio/music.mp3')
  if (existsSync(file)) {
    console.log('audio/music.mp3 exists; delete it to make a new one')
  } else {
    const audio = await (await call('/v1/music', { prompt: MUSIC_PROMPT, music_length_ms: seconds * 1000 })).arrayBuffer()
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, Buffer.from(audio))
    console.log(`audio/music.mp3  ${(durationMs(file) / 1000).toFixed(1)} s`)
  }
  await envelope()
}

const ENVELOPE = join(ROOT, 'src/data/music-envelope.json')

/** The music's loudness second by second (EBU R128 momentary, LUFS), so the mix can even it out:
 * a generated track that builds up can be 10 dB louder at its peak than where it starts. */
async function envelope(): Promise<void> {
  const run = spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-i', join(PUBLIC, 'audio/music.mp3'), '-af', 'ebur128', '-f', 'null', '-'], { encoding: 'utf-8' })
  const perSecond: number[][] = []
  for (const match of run.stderr.matchAll(/t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+|-inf)/g)) {
    const second = Math.floor(Number(match[1]))
    const lufs = match[2] === '-inf' ? -70 : Number(match[2])
    ;(perSecond[second] ??= []).push(lufs)
  }
  const lufs = perSecond.map((values) => Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10)
  writeFileSync(ENVELOPE, JSON.stringify({ about: 'Generated by scripts/audio.ts music: the music loudness per second, LUFS.', lufs }) + '\n')
  console.log(`src/data/music-envelope.json  ${lufs.length} s, ${Math.min(...lufs)} to ${Math.max(...lufs)} LUFS`)
}

async function check(): Promise<void> {
  const plan = (await (await call('/v1/user/subscription')).json()) as { tier: string; character_count: number; character_limit: number }
  const script = readScript()
  const needed = script.scenes.flatMap((s) => s.lines).reduce((sum, l) => sum + (l.say ?? l.text).length, 0)
  console.log({ tier: plan.tier, used: plan.character_count, limit: plan.character_limit, remaining: plan.character_limit - plan.character_count, wholeNarration: needed })
}

const commands: Record<string, () => Promise<void> | void> = { lines, verify, sfx, music: () => music(), envelope, check }
const command = commands[process.argv[2] ?? '']
if (!command) {
  console.error(`Usage: node scripts/audio.ts ${Object.keys(commands).join('|')}`)
  process.exit(1)
}
// A failed run (no key, an error from ElevenLabs, ffmpeg missing) ends with one line and a non-zero
// exit code, instead of an unhandled rejection's stack trace.
try {
  await command()
} catch (error) {
  console.error(`scripts/audio.ts ${process.argv[2]}: ${error instanceof Error ? error.message : String(error)}`)
  process.exit(1)
}
