// Switches for a re-render. The video is honest about what is not built yet: the GPS simulator and
// the KPI dashboard arrive at milestone M2 (5 October 2026), the optimizer at M3 (8 October 2026).
// Every scene that shows one of them carries an "In development" chip. Once they exist, set this to
// false and render again: the chips go, nothing else moves.
export const SHOW_IN_DEVELOPMENT = true

// The vans are always simulated on real roads, so that chip has no switch.
