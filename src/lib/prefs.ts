const KEY = "clipforge.prefs";

export type Prefs = { preset: string; maxClips: number; aspects: string[] };

const DEFAULTS: Prefs = { preset: "any", maxClips: 8, aspects: ["9:16"] };
const KNOWN_ASPECTS = ["9:16", "4:5", "1:1", "16:9"];

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<Prefs>;
    const aspects = Array.isArray(parsed.aspects)
      ? KNOWN_ASPECTS.filter((a) => parsed.aspects?.includes(a))
      : [];
    return {
      preset: typeof parsed.preset === "string" ? parsed.preset : DEFAULTS.preset,
      maxClips: typeof parsed.maxClips === "number" ? parsed.maxClips : DEFAULTS.maxClips,
      aspects: aspects.length ? aspects : DEFAULTS.aspects,
    };
  } catch {
    return DEFAULTS;
  }
}

export function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable */
  }
}
