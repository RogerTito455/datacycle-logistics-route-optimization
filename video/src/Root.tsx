import { Composition } from 'remotion'
import { LlobregatVideo } from './LlobregatVideo'
import { TOTAL } from './timeline'
import { FPS, H, W } from './theme'

export function Root() {
  return <Composition id="LlobregatExpress" component={LlobregatVideo} durationInFrames={TOTAL} fps={FPS} width={W} height={H} />
}
