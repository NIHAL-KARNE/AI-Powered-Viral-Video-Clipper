import { useState } from "react";
import { AlignCenter, Palette, Sparkles, Type, Wand2 } from "lucide-react";
import type { Clip } from "../lib/types";
import { api } from "../lib/api";
import { BrandKitPanel } from "./BrandKitPanel";

/** Colours that read well on video over a dark scene. */
const ACCENTS = [
  { hex: "#ffffff", label: "White" },
  { hex: "#a78bfa", label: "Violet" },
  { hex: "#22d3ee", label: "Cyan" },
  { hex: "#34d399", label: "Green" },
  { hex: "#fbbf24", label: "Amber" },
  { hex: "#fb7185", label: "Rose" },
  { hex: "#f472b6", label: "Pink" },
  { hex: "#60a5fa", label: "Blue" },
];

const FONTS = [
  { key: "", label: "Style default" },
  { key: "Inter", label: "Inter" },
  { key: "DejaVu Sans", label: "DejaVu Sans" },
  { key: "DejaVu Serif", label: "DejaVu Serif" },
];

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-3 rounded-lg glass-inset px-3 py-2.5">
      <span className="min-w-0">
        <span className="block text-[12px] font-medium text-white">{label}</span>
        <span className="mt-0.5 block text-[10.5px] leading-relaxed text-slate-400">{hint}</span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-violet-500"
      />
    </label>
  );
}

export function StylePanel({
  clip,
  update,
}: {
  clip: Clip;
  update: (patch: Partial<Clip>) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [ideas, setIdeas] = useState<string[]>([]);
  const [hint, setHint] = useState("");

  const accent = clip.accent_color ?? "#a78bfa";
  const headlineOn = clip.headline_enabled !== false;

  const suggest = async () => {
    setBusy(true);
    setHint("");
    try {
      const res = await api.headlineSuggestions(clip.id);
      setIdeas(res.options);
      if (!res.options.length) setHint("No strong line found in this clip.");
    } catch (e) {
      setHint(e instanceof Error ? e.message : "Could not generate headlines");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <BrandKitPanel clip={clip} update={update} />
      <div>
        <label className="label">Headline</label>
        <ToggleRow
          label="Show headline"
          hint="Bold title at the top for the opening seconds"
          checked={headlineOn}
          onChange={(v) => update({ headline_enabled: v })}
        />
        <input
          className="input mt-2 py-2 text-[12px]"
          value={clip.headline ?? ""}
          maxLength={80}
          placeholder="Short line for the top of the frame"
          disabled={!headlineOn}
          onChange={(e) => update({ headline: e.target.value })}
        />
        <div className="mt-2 flex items-center gap-2">
          <button className="btn-ghost btn-sm" onClick={() => void suggest()} disabled={busy}>
            {busy ? <Wand2 size={12} className="animate-pulse" /> : <Sparkles size={12} />}
            {busy ? "Thinking…" : "Suggest headlines"}
          </button>
          {ideas.length > 0 && (
            <button className="text-[10.5px] text-slate-400 underline hover:text-slate-300" onClick={() => setIdeas([])}>
              clear
            </button>
          )}
        </div>
        {hint && <p className="mt-1.5 text-[10.5px] text-slate-400">{hint}</p>}
        {ideas.length > 0 && (
          <div className="mt-2 space-y-1.5">
            {ideas.map((t) => (
              <button
                key={t}
                onClick={() => {
                  update({ headline: t, headline_enabled: true });
                  setIdeas([]);
                }}
                className={`w-full rounded-lg border px-2.5 py-2 text-left text-[11.5px] leading-snug transition ${
                  clip.headline === t
                    ? "border-violet-400/60 bg-violet-500/12 text-white"
                    : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>

      {headlineOn && (
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="mb-1 flex justify-between text-[10.5px] text-slate-400">
              <span>Headline length</span>
              <span className="tabular-nums text-slate-400">{clip.headline_seconds ?? 4}s</span>
            </span>
            <input
              type="range"
              min={1}
              max={12}
              step={0.5}
              value={clip.headline_seconds ?? 4}
              onChange={(e) => update({ headline_seconds: Number(e.target.value) })}
              className="w-full accent-violet-500"
            />
          </label>
          <label className="block">
            <span className="mb-1 flex justify-between text-[10.5px] text-slate-400">
              <span>Caption size</span>
              <span className="tabular-nums text-slate-400">{clip.caption_size ?? 100}%</span>
            </span>
            <input
              type="range"
              min={70}
              max={140}
              step={5}
              value={clip.caption_size ?? 100}
              onChange={(e) => update({ caption_size: Number(e.target.value) })}
              className="w-full accent-violet-500"
            />
          </label>
        </div>
      )}

      <div>
        <label className="label flex items-center gap-1.5">
          <Palette size={12} /> Accent colour
        </label>
        <div className="grid grid-cols-4 gap-1.5">
          {ACCENTS.map((c) => (
            <button
              key={c.hex}
              onClick={() => update({ accent_color: c.hex })}
              title={c.label}
              aria-label={c.label}
              className={`group flex flex-col items-center gap-1 rounded-lg border px-1.5 py-1.5 transition ${
                accent.toLowerCase() === c.hex
                  ? "border-violet-400/70 bg-violet-500/10"
                  : "border-white/10 bg-white/[0.045] hover:border-white/20"
              }`}
            >
              <span
                className="h-4 w-4 rounded-full ring-1 ring-white/25"
                style={{ background: c.hex }}
              />
              <span className="text-[9px] text-slate-400">{c.label}</span>
            </button>
          ))}
        </div>
        <div className="mt-2 flex items-center gap-2">
          <input
            type="color"
            value={accent}
            onChange={(e) => update({ accent_color: e.target.value })}
            className="h-7 w-10 cursor-pointer rounded border border-white/10 bg-transparent"
            aria-label="Custom accent colour"
          />
          <span className="font-mono text-[10.5px] text-slate-400">{accent}</span>
          <span className="ml-auto text-[10px] text-slate-500">headline, captions, bar</span>
        </div>
      </div>

      <div>
        <label className="label flex items-center gap-1.5">
          <Type size={12} /> Caption font
        </label>
        <div className="grid grid-cols-2 gap-1.5">
          {FONTS.map((f) => (
            <button
              key={f.key || "default"}
              onClick={() => update({ caption_font: f.key })}
              className={`rounded-lg border px-2 py-1.5 text-[11px] transition ${
                (clip.caption_font ?? "") === f.key
                  ? "border-violet-400/60 bg-violet-500/12 text-white"
                  : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
              }`}
              style={{ fontFamily: f.key || undefined }}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="label flex items-center gap-1.5">
          <AlignCenter size={12} /> On-screen extras
        </label>
        <div className="space-y-2">
          <label className="block rounded-lg glass-inset px-3 py-2.5">
            <span className="mb-1 flex items-center justify-between text-[10.5px] text-slate-400">
              <span>Words per caption</span>
              <span className="tabular-nums text-slate-300">
                {clip.caption_words ?? 5} words
              </span>
            </span>
            <input
              type="range"
              min={2}
              max={7}
              step={1}
              value={clip.caption_words ?? 5}
              onChange={(e) => update({ caption_words: Number(e.target.value) })}
              className="w-full accent-violet-500"
            />
            <span className="mt-1 block text-[10px] leading-relaxed text-slate-500">
              Longer cues are easier to read; shorter ones fade faster. 4–5 works for most clips.
            </span>
          </label>
          <ToggleRow
            label="Auto emoji"
            hint="Drops a fitting emoji beside the captions when the line calls for one"
            checked={clip.emoji_enabled !== false}
            onChange={(v) => update({ emoji_enabled: v })}
          />
          <ToggleRow
            label="Highlight keywords"
            hint="Colours the word that carries the meaning, so captions scan at a glance"
            checked={clip.keywords_enabled !== false}
            onChange={(v) => update({ keywords_enabled: v })}
          />
          <ToggleRow
            label="Progress bar"
            hint="Thin accent bar along the bottom that fills as the clip plays"
            checked={!!clip.progress_bar}
            onChange={(v) => update({ progress_bar: v })}
          />
          <ToggleRow
            label="Remove filler words"
            hint='Drops "um", "uh" and drawn-out pauses while keeping sentences intact'
            checked={!!clip.remove_fillers}
            onChange={(v) => update({ remove_fillers: v })}
          />
          <ToggleRow
            label="Smooth camera tracking"
            hint="Camera drifts with the subject instead of holding one crop"
            checked={clip.track_motion !== false}
            onChange={(v) => update({ track_motion: v })}
          />
        </div>
      </div>

      <p className="text-[10px] leading-relaxed text-slate-500">
        These are applied when you render, and the live preview reflects the headline, colour
        and caption size.
      </p>
    </div>
  );
}
