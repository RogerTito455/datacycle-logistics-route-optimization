# Llobregat Express explainer video

A 2 min 36 s, 1920 × 1080, 30 fps explainer for the project, made in code: [Remotion](https://www.remotion.dev) for the picture, ElevenLabs for the narration, the sound effects and the music. It records nothing: every interface on screen (the map, the pipeline, the dashboard panel, the terminal) is drawn here, in the landing page's palette and type, from the platform's own data.

```bash
cd video
pnpm install
pnpm studio    # preview and scrub it in the browser
pnpm render    # out/llobregat-express.mp4 (git-ignored)
```

The narrator is the same voice, with the same settings, as the team's previous video (HackFire), so the two sound like one series.

## What it says

Everything is in English, with word-by-word subtitles. The script is [`src/script.json`](src/script.json), one entry per line.

| Chapter | Scenes | Shows |
|---|---|---|
| 01 The morning plan | `open`, `incidents`, `cascade` | The hub in the Zona Franca at 07:30 and thirty vans leaving on real roads to the fourteen zones; by 11:00, a car in a real loading bay, the Ronda Litoral jammed, rain, a door in the Raval; a route whose times slide later, stop after stop |
| 02 One number | `kpi` | The KPI, from `departed_at` to `delivered_at`, and the company's baseline (6 h 01) and target (5 h 30) |
| 03 The platform | `brand`, `pipeline` | The seven lifecycle stages with a streaming lane and a batch lane, the products as the voice names them, and the KPI panel drawn in the dashboard's style |
| 04 From a ping to a decision | `ping` | One ping from V-07 on the Ronda Litoral, as data, information, knowledge and action: the plan made at dawn (dashed) and the re-plan (orange) of its fourteen stops |
| 05 Why not a map app | `compare` | A navigation app and Llobregat Express side by side; no real product is named |
| 06 Built to be checked | `lineage`, `origins`, `smoke` | The lineage from `gps.pings` to the dashboard and the three metadata elements; real, generated and simulated data; `make up` and `make smoke`, 7 passed |
| Close | `close` | The end card: "Plans the fleet, not the trip.", the team, the course and the repository |

## Honesty rules

- **The vans are simulated on real roads.** Every scene that shows them carries a "Simulated fleet on real roads" chip. The times of day in chapters 01 and 04 are illustrative, and the clock says so.
- **Parts that are not built yet say so.** The GPS simulator and the KPI dashboard arrive at milestone M2 (5 October 2026), the optimizer at M3 (8 October 2026). Scenes that show them carry an "In development · M2" or "· M3" chip. All of these chips hang off one switch, `SHOW_IN_DEVELOPMENT` in [`src/config.ts`](src/config.ts): set it to `false` and render again once those parts exist.
- **361 and 330 minutes are the company's baseline and target**, from its AI-generated profile, never results; the KPI scene says it in words.
- **Every figure has a source**, in the one-line note at the bottom left of each scene (`SOURCES` in [`src/Chrome.tsx`](src/Chrome.tsx)) and in `script.json`'s `about`. Illustrative parts (the incidents, the stop list of chapter 01, the weekday-by-hour strip of chapter 04) are labelled as such.

## How it is built

- **Timing comes from the audio.** `pnpm voice` turns each line of `script.json` into one clip and writes [`src/data/narration.json`](src/data/narration.json) with its length and word timings (ElevenLabs `with-timestamps`). [`src/timeline.ts`](src/timeline.ts) lays the lines end to end, so rewording a line moves everything after it. Visual beats hang off words: `beat('kpi-2', 'six')` is the frame "six" is said on.
- **One map, one camera.** [`src/CityMap.tsx`](src/CityMap.tsx) draws [`src/data/map.json`](src/data/map.json) in kilometres from the hub with a virtual camera, and [`src/MapStage.tsx`](src/MapStage.tsx) flies it from the whole city to one stretch of the Ronda Litoral.
- **The rest** is in [`src/Scenes.tsx`](src/Scenes.tsx) (the KPI, the pipeline and dashboard panel, the comparison, the lineage, the data origins, the terminal and the end card) and [`src/Chrome.tsx`](src/Chrome.tsx) (brand pill, chapters and progress, clock, chips, source line, subtitles). The logo and icons are SVG in [`src/Icon.tsx`](src/Icon.tsx). Type is Big Shoulders (display cut), IBM Plex Sans and IBM Plex Mono, loaded with `@remotion/google-fonts`.
- **Sound.** The generated music builds up, so the mix evens it out: [`src/data/music-envelope.json`](src/data/music-envelope.json) holds its loudness second by second, and each moment is turned down to -24 LUFS between lines, about 9 dB lower under the voice, with 12-frame ramps ([`src/LlobregatVideo.tsx`](src/LlobregatVideo.tsx)). Effects land on beats.

## Map data

`pnpm map` (`scripts/map.ts`) rebuilds `src/data/map.json`, which is committed so a render needs no network:

| Layer | Source |
|---|---|
| Roads (motorway to tertiary for the city, the residential grid of Poblenou for chapter 04) | OpenStreetMap through the Overpass API, simplified (Douglas–Peucker, 4 to 12 m) |
| Coastline and sea | OpenStreetMap `natural=coastline` through the Overpass API: the ways are joined into one shore (land on the left, as OSM draws it) and the sea is closed round the south-east; breakwaters are the closed rings. Not a hand approximation |
| Llobregat and Besòs rivers | OpenStreetMap `waterway=river` through the Overpass API |
| The 30 vans' routes: hub to a delivery loop in their zone, and the loop, on real streets | The platform's OSRM at `http://localhost:5000` (`OSRM_URL` to change it), on the Catalonia road network |
| Ronda Litoral, Ronda de Dalt, Gran Via, Diagonal | OSRM routes through waypoints on each road |
| Chapter 04: V-07's position, the stretch it has crawled, its 14 stops, the plan made at dawn and the re-plan | OSRM `route`, `nearest` and `trip` (the re-plan is OSRM's trip service, an illustration of what the M3 optimizer will do) |
| The loading bay of chapter 01 (Carrer de Roger de Llúria, 102) | Open Data BCN, zones de càrrega i descàrrega (CC BY 4.0) |
| Hub, zones, fleet, stops per route, KPI baseline and target | [`src/data/company.json`](src/data/company.json), copied from `services/generator/seed/company.json` (AI-generated, prompt 001, validated against OpenStreetMap) |

The Overpass and OSRM answers are cached in `scripts/.cache/` (git-ignored); delete a file there to fetch it again. Overpass is sometimes busy (HTTP 504): the script tries three mirrors in turn.

## Audio

`scripts/audio.ts` needs `ELEVENLABS_API_KEY` in the environment or in `video/.env` (git-ignored), and spends the plan's characters, so it only regenerates what changed:

| Command | Writes | Regenerates when |
|---|---|---|
| `pnpm voice` | `public/audio/lines/*.mp3`, `src/data/narration.json` | A line's text, `say`, voice or settings change |
| `pnpm sfx` | `public/audio/sfx/*.mp3` | The file is missing |
| `pnpm music` | `public/audio/music.mp3` (200 s by default; this one is 178 s) and `src/data/music-envelope.json` | The file is missing; the loudness curve is always remeasured |
| `node scripts/audio.ts verify` | Nothing: checks every clip's word timings against its text | Run by `pnpm voice` after generating |
| `pnpm audio:check` | Nothing: prints the plan's remaining characters and the narration's size | |

The narrator is Christopher (`eleven_multilingual_v2`, stability 0.55, similarity 0.8, style 0.1, speaker boost, speed 1.1). A line's `say` is a spelling for the voice only (`Yoo-bruh-gat`, `Lee-to-rahl`, `Glo-ree-es`, `Timescale-D-B`, `D-B-T`), with the same number of words as its `text`; the script refuses to spend anything if they differ. There is no speech recognition here: `verify` checks the with-timestamps alignment instead, that every word the voice was given is the word aligned, in order, and that no word takes an absurd time for its length. The generated audio is committed, so a render needs no key.

## Re-rendering

```bash
pnpm render
cp out/llobregat-express.mp4 /mnt/c/Users/crtit/Desktop/LlobregatExpress-video-EN.mp4
```

A full render took 28 to 50 minutes here (12 threads, shared with the platform's containers). `pnpm typecheck` checks the source.
