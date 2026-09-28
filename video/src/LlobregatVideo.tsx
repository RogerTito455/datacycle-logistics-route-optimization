// The whole video: the map underneath, opaque scenes over it, the frame's chrome, and the sound.

import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion'
import { Header, SceneSources, Subtitles, Tags } from './Chrome'
import { MapStage } from './MapStage'
import { Brand, Close, Compare, Kpi, Lineage, Origins, Pipeline, Smoke } from './Scenes'
import envelope from './data/music-envelope.json'
import { ALL_LINES, SCENES, TOTAL, beat, line, lineEnd, scene } from './timeline'
import { C, FPS } from './theme'

// The music sits at MUSIC_LUFS between lines and about 9 dB lower under the voice (narration is at
// -16 LUFS). A generated track builds up, so each moment is turned down by how far its loudness
// (src/data/music-envelope.json) is over the target; nothing is turned up.
const MUSIC_LUFS = -24
const DUCK = 0.35
const LUFS: number[] = (envelope as { lufs: number[] }).lufs

function evenOut(frame: number): number {
  const second = frame / FPS
  // The power over the three seconds around this moment, so the level glides instead of stepping.
  const around = [second - 1, second, second + 1].map((s) => LUFS[Math.max(0, Math.min(LUFS.length - 1, Math.floor(s)))])
  const loudness = 10 * Math.log10(around.reduce((sum, l) => sum + Math.pow(10, l / 10), 0) / around.length)
  return Math.min(1, Math.pow(10, (MUSIC_LUFS - loudness) / 20))
}

// Scenes that cover the whole frame: the map is not drawn under them.
const OPAQUE = ['kpi', 'brand', 'pipeline', 'compare', 'lineage', 'origins', 'smoke']
const WITH_CLOCK = ['open', 'incidents', 'cascade', 'ping']

export function LlobregatVideo() {
  const f = useCurrentFrame()
  const current = [...SCENES].reverse().find((s) => f >= s.start) ?? SCENES[0]
  const covered = SCENES.some((s) => OPAQUE.includes(s.id) && f >= s.start + 8 && f < s.end)
  return (
    <AbsoluteFill style={{ background: C.ground, overflow: 'hidden' }}>
      {!covered && <MapStage f={f} />}
      <Kpi f={f} />
      <Brand f={f} />
      <Pipeline f={f} />
      <Compare f={f} />
      <Lineage f={f} />
      <Origins f={f} />
      <Smoke f={f} />
      <Close f={f} />
      <Header f={f} sceneId={current.id} />
      <Tags f={f} sceneId={current.id} clock={WITH_CLOCK.includes(current.id)} />
      <SceneSources f={f} />
      <Subtitles f={f} />
      <Sound />
    </AbsoluteFill>
  )
}

function Sfx({ at, name, volume = 0.3 }: { at: number; name: string; volume?: number }) {
  return (
    <Sequence from={Math.max(0, Math.round(at))} durationInFrames={120}>
      <Audio src={staticFile(`audio/sfx/${name}.mp3`)} volume={volume} />
    </Sequence>
  )
}

function Sound() {
  const talking = ALL_LINES.map((l) => [l.at, l.at + l.frames] as const)
  return (
    <>
      {ALL_LINES.map((l) => (
        <Sequence key={l.id} from={l.at} durationInFrames={l.frames + 10}>
          <Audio src={staticFile(l.file)} />
        </Sequence>
      ))}
      {SCENES.slice(1).map((s) => (
        <Sfx key={s.id} at={s.start - 4} name="whoosh" volume={0.18} />
      ))}
      <Sfx at={beat('open-1', 'thirty')} name="blip" volume={0.25} />
      <Sfx at={beat('open-1', 'seventy')} name="tick" volume={0.25} />
      <Sfx at={beat('open-1', 'fixed')} name="tick" volume={0.25} />
      <Sfx at={beat('open-2', 'wrong')} name="hit" volume={0.28} />
      <Sfx at={beat('incidents-0', 'car')} name="horn" volume={0.16} />
      <Sfx at={beat('incidents-0', 'ronda')} name="blip" volume={0.25} />
      <Sfx at={beat('incidents-0', 'rain') - 6} name="rain" volume={0.22} />
      <Sfx at={beat('incidents-0', 'nobody')} name="tick" volume={0.3} />
      <Sfx at={beat('cascade-0', 'delay')} name="tick" volume={0.22} />
      <Sfx at={beat('cascade-0', 'never')} name="tick" volume={0.3} />
      <Sfx at={beat('kpi-2', 'six')} name="hit" volume={0.3} />
      <Sfx at={beat('kpi-2', 'target')} name="blip" volume={0.28} />
      <Sfx at={scene('brand').start + 8} name="hit" volume={0.3} />
      <Sfx at={beat('pipeline-0', 'position')} name="scan" volume={0.2} />
      <Sfx at={beat('pipeline-2', 'redpanda')} name="blip" volume={0.22} />
      <Sfx at={beat('pipeline-3', 'timescaledb')} name="blip" volume={0.22} />
      <Sfx at={beat('pipeline-3', 'kpi')} name="blip" volume={0.22} />
      <Sfx at={beat('pipeline-4', 'grafana')} name="scan" volume={0.22} />
      <Sfx at={beat('ping-0', 'ping')} name="blip" volume={0.3} />
      <Sfx at={beat('ping-1', 'information')} name="tick" volume={0.28} />
      <Sfx at={beat('ping-2', 'knowledge')} name="tick" volume={0.28} />
      <Sfx at={line('ping-3').at} name="scan" volume={0.22} />
      <Sfx at={beat('ping-4', 're-orders')} name="chime" volume={0.22} />
      <Sfx at={beat('compare-3', 'fleet')} name="blip" volume={0.22} />
      <Sfx at={beat('lineage-0', 'source')} name="scan" volume={0.2} />
      <Sfx at={beat('origins-1', 'checked')} name="tick" volume={0.28} />
      <Sfx at={beat('smoke-0', 'one')} name="keys" volume={0.2} />
      <Sfx at={beat('smoke-0', 'tested')} name="keys" volume={0.2} />
      <Sfx at={lineEnd('smoke-0') + 8} name="chime" volume={0.26} />
      <Sfx at={line('close-0').at - 6} name="hit" volume={0.3} />
      <Audio
        src={staticFile('audio/music.mp3')}
        volume={(g) => {
          const fadeInOut = interpolate(g, [0, 24, TOTAL - 60, TOTAL], [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
          // Frames to the nearest speech: under the voice the music drops, and comes back over 12 frames.
          const away = Math.min(...talking.map(([a, b]) => (g < a - 6 ? a - 6 - g : g > b + 8 ? g - b - 8 : 0)))
          const duck = DUCK + (1 - DUCK) * Math.min(1, away / 12)
          return fadeInOut * evenOut(g) * duck
        }}
      />
    </>
  )
}
