import { useMemo } from "react";

export type CaptionWord = { start: number; end: number; word: string };

/**
 * Style metadata mirrored from `CAPTION_STYLES` in render.py.
 *
 * `sizePct` is the style's font size as a percentage of the 1920px reference
 * height. The export sizes captions from output height, so the preview must use
 * the same relative size or every style looks wrong next to the export.
 * `words` selects word-at-a-time chunking (3 words) versus sentence chunking
 * (7 words), matching `word_captions` in the renderer.
 */
const STYLE_META: Record<
  string,
  {
    font: string;
    weight: number;
    upper: boolean;
    color: string;
    stroke: string;
    shadow: string;
    sizePct: number;
    words: boolean;
  }
> = {
  "bold-pop": {
    font: "Inter, sans-serif",
    weight: 800,
    upper: true,
    color: "#fff",
    stroke: "#000",
    shadow: "0 3px 0 #000, 0 0 14px rgba(0,0,0,0.7)",
    sizePct: 5.42,
    words: true,
  },
  clean: {
    font: "Inter, sans-serif",
    weight: 600,
    upper: false,
    color: "#fff",
    stroke: "rgba(0,0,0,0.55)",
    shadow: "0 2px 10px rgba(0,0,0,0.6)",
    sizePct: 3.85,
    words: false,
  },
  karaoke: {
    font: "Inter, sans-serif",
    weight: 800,
    upper: true,
    color: "#fff",
    stroke: "#101010",
    shadow: "0 3px 0 #000",
    sizePct: 4.79,
    words: true,
  },
  editorial: {
    font: "Georgia, serif",
    weight: 600,
    upper: false,
    color: "#fff",
    stroke: "rgba(0,0,0,0.45)",
    shadow: "0 2px 12px rgba(0,0,0,0.5)",
    sizePct: 3.65,
    words: false,
  },
  neon: {
    font: "Inter, sans-serif",
    weight: 800,
    upper: true,
    color: "#fff7c2",
    stroke: "#b02cc9",
    shadow: "0 0 20px rgba(176,44,201,0.9)",
    sizePct: 5.0,
    words: true,
  },
};

/**
 * Keyword emphasis and emoji rules, mirrored from `backend/app/emphasis.py`.
 *
 * These must stay in step with the backend or the live preview drifts from the
 * export. Only the rules that matter for previewing are copied: the word sets
 * that decide which word is highlighted, and the ordered emoji patterns.
 */
const EMPHASIS = new Set(
  `never always nobody everybody everyone everything nothing money rich broke
million billion thousand percent free fake real truth lie scam secret mistake
worst best biggest craziest insane crazy wild unbelievable impossible disaster
failed failure won lost win lose quit fired hired banned suspended arrested exposed
caught betrayed cheated stole stolen killed died dead alive survived destroyed
love hate scared afraid terrified cry crying hurt painful broken heart proud
rich poor expensive cheap profit loss debt ruined homeless job career business
boss manager fired promoted salary income tax rent buying selling price
fast slow huge tiny massive dangerous illegal legal banned viral famous rich
yesterday tomorrow today now forever finally suddenly`.split(/\s+/),
);

/** Phrases that carry meaning as a unit (mirrors EMPHASIS_PHRASES). */
const EMPHASIS_PHRASES = [
  "feel bad", "feels bad", "lost my job", "lost it", "lost everything",
  "no way", "oh my god", "what the hell", "for real", "i swear",
  "never again", "one hundred percent", "right now", "all my money",
  "my whole life", "the truth", "sold out", "gave up", "walked away",
  "turned down", "blew up", "went viral", "messed up", "fucked up",
  "freaked out", "passed out", "knocked out", "broke down",
  "big deal", "life changing", "game changer", "at the end",
];

const REACTION = new Set(`haha lol lmao funny hilarious kidding joke laughed laughing dead dying`.split(/\s+/));

const NO_EMOJI = new Set(
  `the a an and but or so if when while because of to in on at for with from by
is are was were be been being am do does did has have had will would can could
should may might must not no yes i you he she it we they me him her us them
that this these those there here what which who whom whose how why where`.split(/\s+/),
);

/** Ordered: first anchored match wins, so stronger emotions lead. */
const EMOJI_RULES: [RegExp, string][] = [
  [/\b(haha|lol|lmao|hilarious|funny|joking|kidding|laughed|laughing)\b/, "😂"],
  [/\b(cry|cried|crying|tears|sad|devastated|heartbroken)\b/, "😢"],
  [/\b(love|loved|adorable|beautiful|amazing)\b/, "❤️"],
  [/\b(scared|afraid|terrified|horrified|fear)\b/, "😱"],
  [/\b(money|rich|million|billion|profit|salary|income|cash|dollars?|paid|paycheck)\b/, "💰"],
  [/\b(broke|debt|lost|losing|lose|ruined|bankrupt)\b/, "💸"],
  [/\b(fired|quit|lost my job|unemployed|laid off)\b/, "🚪"],
  [/\b(won|win|winning|victory|champion|first place)\b/, "🏆"],
  [/\b(crazy|insane|wild|unbelievable|impossible|craziest|nuts|mind blown)\b/, "🤯"],
  [/\b(secret|the truth|lying|lied|lie to|scam|fake|exposed|betray\w*)\b/, "🤫"],
  [/\b(dead|died|dying|killed|murder)\b/, "💀"],
  [/\b(fire|burning|flame|lit)\b/, "🔥"],
  [/\b(warning|danger|dangerous|careful|illegal|banned)\b/, "⚠️"],
  [/\b(career|business|boss|manager|office|meeting|interview|salary|promotion)\b/, "💼"],
  [/\b(game|gaming|played|player|gamer|stream)\b/, "🎮"],
  [/\b(food|eat|eating|hungry|meal|pizza|burger)\b/, "🍔"],
  [/\b(car|cars|driving|drove|truck|lambo|ferrari|parking lot)\b/, "🚗"],
  [/\b(clock|o'?clock|late again|running late|too early)\b/, "⏰"],
  [/\b(phone|text|call|message|dm)\b/, "📱"],
  [/\b(school|college|teacher|student|exam|graduat\w*)\b/, "🎓"],
  [/\b(oh my god|what the hell|what the fuck|no way|whoa|wow)\b/, "😳"],
  [/\b(hold on|listen to me|stop right there)\b/, "✋"],
  [/\b(help|please|need you)\b/, "🙏"],
  [/\b(feel bad|feels bad|so bad|terrible|awful|horrible|sucks)\b/, "😞"],
  [/\b(tired|exhausted|sleepy|no sleep)\b/, "😴"],
  [/\b(nervous|anxious|stress\w*|worried|panic)\b/, "😬"],
  [/\b(proud|grateful|thank god|blessed|lucky)\b/, "🙏"],
  [/\b(angry|mad|pissed|furious|rage)\b/, "😡"],
  [/\b(fight|punch|attack|war|beat him|beat me)\b/, "💥"],
  [/\b(gym|workout|strong|muscle|training)\b/, "💪"],
];

const coreWord = (raw: string) =>
  raw.replace(/[^A-Za-z0-9'%.-]/g, "").toLowerCase();

/** Which words in a cue get the keyword colour. Mirrors `highlight_words`. */
export function highlightWords(words: CaptionWord[], limit = 2): boolean[] {
  const out = words.map(() => false);
  const scored: { score: number; i: number }[] = [];
  words.forEach((w, i) => {
    const core = coreWord(w.word);
    if (!core || NO_EMOJI.has(core)) return;
    let score = 0;
    if (EMPHASIS.has(core) || EMPHASIS.has(core.replace(/s$/, ""))) score += 3;
    if (REACTION.has(core)) score += 1.2;
    if (/^\d[\d,.]*%?$/.test(core)) score += 2.4;
    if (core.length >= 7) score += 0.6;
    if (w.word === w.word.toUpperCase() && core.length > 2) score += 0.5;
    if (w.word.trim().endsWith("!")) score += 0.4;
    if (score > 0) scored.push({ score, i });
  });
  scored
    .sort((a, b) => b.score - a.score || a.i - b.i)
    .slice(0, limit)
    .forEach(({ i }) => (out[i] = true));

  // Phrase emphasis: colour every word of a meaningful phrase.
  const flat = words.map((w) => coreWord(w.word));
  for (const phrase of EMPHASIS_PHRASES) {
    const parts = phrase.split(" ");
    for (let start = 0; start + parts.length <= flat.length; start++) {
      const window = flat.slice(start, start + parts.length);
      if (window.every((w, k) => w === parts[k])) {
        parts.forEach((_, k) => (out[start + k] = true));
        break;
      }
    }
  }
  return out;
}

/** First anchored emoji match in a word window. Mirrors `plan_emoji`. */
function emojiFor(wordList: string[]): string | null {
  const core = wordList.join(" ").toLowerCase().replace(/[^a-z' ]/g, "").trim();
  if (!core) return null;
  for (const [re, emoji] of EMOJI_RULES) {
    if (new RegExp(`^(?:${re.source})`).test(core)) return emoji;
  }
  return null;
}

export type EmojiMark = { index: number; emoji: string };

/**
 * Where emoji appear across the clip, matching the backend planner: match on
 * the word, anchor to its cue, then space them out.
 */
export function planEmoji(cues: CaptionWord[][]): EmojiMark[] {
  const flat: { ci: number; t: number; word: string }[] = [];
  cues.forEach((cue, ci) =>
    cue.forEach((w) => flat.push({ ci, t: w.start, word: w.word })),
  );
  const found: { ci: number; t: number; emoji: string }[] = [];
  for (let i = 0; i < flat.length; i++) {
    const emoji = emojiFor(flat.slice(i, i + 3).map((w) => w.word));
    if (emoji) found.push({ ci: flat[i].ci, t: flat[i].t, emoji });
  }
  const plan: EmojiMark[] = [];
  const used = new Set<number>();
  let lastG = "";
  let lastT = -999;
  for (const f of found) {
    if (used.has(f.ci) || f.emoji === lastG || f.t - lastT < 2.8) continue;
    plan.push({ index: f.ci, emoji: f.emoji });
    used.add(f.ci);
    lastG = f.emoji;
    lastT = f.t;
  }
  if (!plan.length) return plan;
  // Fill long flat stretches with the clip's dominant emoji, skipping filler.
  const tally = new Map<string, number>();
  plan.forEach((p) => tally.set(p.emoji, (tally.get(p.emoji) ?? 0) + 1));
  const dominant = [...tally.entries()].sort((a, b) => b[1] - a[1])[0][0];
  let prevT = cues[0]?.[0]?.start ?? 0;
  cues.forEach((cue, ci) => {
    const start = cue[0]?.start ?? 0;
    const end = cue[cue.length - 1]?.end ?? start;
    if (used.has(ci)) {
      prevT = start;
      return;
    }
    const real = cue.filter((w) => {
      const core = coreWord(w.word);
      return core && !NO_EMOJI.has(core);
    });
    if (real.length < 2 || end - start < 0.6 || start - prevT < 7.5) return;
    plan.push({ index: ci, emoji: dominant });
    used.add(ci);
    prevT = start;
  });
  plan.sort((a, b) => a.index - b.index);
  return plan;
}

/**
 * Caption chunks, matching `word_captions` in render.py.
 *
 * Word styles break on any punctuation; sentence styles only on a sentence end.
 * Keeping this in step means the export shows the same words at the same moment.
 */
const DANGLING = new Set(
  `the a an to of and but or for with in on at my your his her their its our is
are was were be been that which who as than so if`.split(/\s+/),
);
const HARD_END = /[.!?]["')\]]*$/;
const SOFT_END = /[,;:—–-]["')\]]*$/;
const CAPTION_MAX_DUR = 2.8;

/** Group words into cue-sized chunks. Mirrors `caption_chunks` in render.py. */
export function captionChunks(words: CaptionWord[], maxWords = 5): CaptionWord[][] {
  const max = Math.max(2, Math.min(Math.round(maxWords) || 5, 7));
  const chunks: CaptionWord[][] = [];
  let cur: CaptionWord[] = [];
  for (const w of words) {
    cur.push(w);
    const word = (w.word ?? "").trim();
    const dur = (cur[cur.length - 1]?.end ?? 0) - (cur[0]?.start ?? 0);
    const hard = HARD_END.test(word);
    const soft = SOFT_END.test(word);
    const longEnough = cur.length >= Math.max(3, max - 1);
    if (!hard) {
      if (!(cur.length >= max || (soft && longEnough) || (dur >= CAPTION_MAX_DUR && cur.length >= 3))) {
        continue;
      }
      const core = word.toLowerCase().replace(/[^a-z']/g, "");
      if (DANGLING.has(core) && cur.length > 2) {
        const moved = cur.pop() as CaptionWord;
        chunks.push(cur);
        cur = [moved];
        continue;
      }
    }
    chunks.push(cur);
    cur = [];
  }
  if (cur.length) chunks.push(cur);
  return chunks.filter((c) => c.length);
}

/** Sentence styles keep longer lines; word styles use readable 4-5 word cues. */
export function buildCues(words: CaptionWord[], wordStyle = true, maxWords = 5) {
  return captionChunks(words, wordStyle ? maxWords : 7);
}

export function CaptionPreview({
  words,
  time,
  style,
  position = "bottom",
  size = 100,
  accent,
  fontOverride,
  keywords = true,
  emoji = true,
  captionWords = 5,
}: {
  words: CaptionWord[];
  time: number;
  style: string;
  position?: string;
  size?: number;
  /** Accent colour for the active word (karaoke) and headline underline. */
  accent?: string;
  /** Optional font family from the Style tab. */
  fontOverride?: string;
  /** Colour the meaning-carrying word in each cue, like the export does. */
  keywords?: boolean;
  /** Show the auto emoji beside the caption block. */
  emoji?: boolean;
  /** Words per cue, matching the export's caption-length setting. */
  captionWords?: number;
}) {
  const base = STYLE_META[style] ?? STYLE_META["bold-pop"];
  const isAccentStyle = style === "karaoke" || style === "neon";
  const meta = {
    ...base,
    font: fontOverride ? `"${fontOverride}", ${base.font}` : base.font,
    color: accent && isAccentStyle ? accent : base.color,
  };
  const activeColor = accent ?? "#ffe14d";
  // Fixed warm yellow, matching KEYWORD_COLOURS in render.py: the spoken word
  // already uses the accent, so a keyword in the same colour would vanish.
  const keywordColor = style === "neon" ? "#ffffff" : "#ffe14d";
  const cues = useMemo(
    () => buildCues(words, base.words, captionWords),
    [words, base.words, captionWords],
  );
  const emojiPlan = useMemo(
    () => (emoji ? planEmoji(cues) : []),
    [cues, emoji],
  );

  const cue = useMemo(() => {
    if (!cues.length) return null;
    const past = cues.filter((c) => c[0].start <= time + 0.08);
    return past.length ? past[past.length - 1] : cues[0];
  }, [cues, time]);

  if (!cue) return null;

  const active = cue.findIndex((w) => time >= w.start - 0.04 && time <= w.end + 0.1);
  const flags = keywords ? highlightWords(cue) : cue.map(() => false);
  const emojiMark = emojiPlan.find((m) => cues[m.index] === cue);
  // Same anchors the renderer uses: top 8.5%, centre, bottom 15% from the edge.
  const posStyle =
    position === "top"
      ? { top: "8.5%" }
      : position === "center"
        ? { top: "50%", transform: "translateY(-50%)" }
        : { bottom: "15%" };

  // Emoji sit beside the caption band, never on top of the words. Anchors
  // mirror the render graph: bottom captions get it above-right, centre gets
  // it to the right, top gets it below the block.
  const emojiAnchor =
    position === "center"
      ? { top: "34%", left: "76%" }
      : position === "top"
        ? { top: "20%", left: "78%" }
        : { top: "66%", left: "74%" };

  return (
    <>
      {emojiMark && (
        <span
          className="pointer-events-none absolute z-20 select-none leading-none"
          style={{
            ...emojiAnchor,
            fontSize: `calc(8.5cqh * ${size / 100})`,
            filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.55))",
          }}
          aria-hidden
        >
          {emojiMark.emoji}
        </span>
      )}
    <div
      className="pointer-events-none absolute inset-x-0 flex justify-center px-[7%]"
      style={posStyle}
    >
      <div
        className="flex max-w-full flex-wrap items-baseline justify-center gap-x-[0.28em] text-center leading-[1.12]"
        style={{
          fontFamily: meta.font,
          fontWeight: meta.weight,
          color: meta.color,
          // Sized from the frame's height, like the export, so the caption
          // occupies the same share of the picture at every aspect ratio.
          fontSize: `calc(${meta.sizePct}cqh * ${size / 100})`,
          WebkitTextStroke: `0.055em ${meta.stroke}`,
          paintOrder: "stroke fill",
          textShadow: meta.shadow,
          letterSpacing: meta.upper ? "0.005em" : "0",
        }}
      >
        {cue.map((w, i) => {
          const label = meta.upper ? w.word.toUpperCase() : w.word;
          const isActive = i === active;
          return (
            <span
              key={`${w.start}-${i}`}
              className="transition-[color,transform] duration-100"
              style={{
                color: isActive
                  ? activeColor
                  : flags[i] && keywords
                    ? keywordColor
                    : undefined,
                transform: isActive ? "scale(1.03)" : undefined,
                display: "inline-block",
              }}
            >
              {label}
            </span>
          );
        })}
      </div>
    </div>
    </>
  );
}
