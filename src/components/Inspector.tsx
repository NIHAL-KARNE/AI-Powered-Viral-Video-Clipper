import { useMemo, useState } from "react";
import {
  Captions,
  Crop,
  Volume2,
  Type,
  Sparkles,
  Palette,
  Move,
  Plus,
  Trash2,
} from "lucide-react";
import type { Clip, Overlay } from "../lib/types";
import { fmtTime } from "../lib/api";
import { FramePanel } from "./FramePanel";
import { StylePanel } from "./StylePanel";

export type CaptionData = {
  cues: { start: number; end: number; text: string }[];
  words: { start: number; end: number; word: string }[];
};

const CAPTION_LABELS: Record<string, { label: string; sub: string }> = {
  "bold-pop": { label: "Bold pop", sub: "3-word chunks" },
  clean: { label: "Clean", sub: "sentence lines" },
  karaoke: { label: "Karaoke", sub: "word highlight" },
  editorial: { label: "Editorial", sub: "serif" },
  neon: { label: "Neon", sub: "glow outline" },
};

const MUSIC_LABELS: Record<string, string> = {
  none: "No music",
  upbeat: "Upbeat bed",
  chill: "Chill bed",
  dramatic: "Dramatic bed",
  lofi: "Lo-fi bed",
};

const ASPECTS = {
  "9:16": "Shorts · Reels · TikTok",
  "1:1": "Feed post",
  "4:5": "Instagram portrait",
  "16:9": "YouTube",
} as const;

export function Toggle({
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
      <span>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label">{title}</label>
      {children}
    </div>
  );
}

export type InspectorTab = "captions" | "frame" | "style" | "audio" | "text" | "meta";

export function Inspector({
  clip,
  captions,
  onSaveCaptions,
  update,
  seekTo,
  duration,
  time = 0,
  autoFocus,
  trackPath,
  tab: controlledTab,
  onTabChange,
}: {
  clip: Clip;
  captions: CaptionData | null;
  onSaveCaptions?: (words: { start: number; end: number; word: string }[]) => Promise<void>;
  update: (patch: Partial<Clip>) => void;
  seekTo: (local: number) => void;
  duration: number;
  /** Playhead position inside the clip, for keyframe editing. */
  time?: number;
  autoFocus?: { x: number; y: number } | null;
  trackPath?: { times: number[]; x: number[]; y: number[] } | null;
  tab?: InspectorTab;
  onTabChange?: (tab: InspectorTab) => void;
}) {
  const [localTab, setLocalTab] = useState<InspectorTab>("captions");
  const tab = controlledTab ?? localTab;
  const setTab = (next: InspectorTab) => {
    setLocalTab(next);
    onTabChange?.(next);
  };
  const overlays: Overlay[] = useMemo(() => clip.overlays ?? [], [clip.overlays]);

  const addOverlay = () => {
    const next: Overlay[] = [
      ...overlays,
      {
        id: `ov${Date.now()}`,
        text: "Add your text",
        start: 0,
        end: Math.max(duration - 1, 1),
        position: "top",
        size: 54,
        color: "#ffffff",
      },
    ];
    update({ overlays: next });
  };

  const patchOverlay = (index: number, patch: Partial<Overlay>) => {
    update({ overlays: overlays.map((o, i) => (i === index ? { ...o, ...patch } : o)) });
  };

  const removeOverlay = (index: number) => {
    update({ overlays: overlays.filter((_, i) => i !== index) });
  };

  const cueList = captions?.cues ?? [];
  const [editingCue, setEditingCue] = useState<number | null>(null);
  const [cueDraft, setCueDraft] = useState("");
  const [captionSaved, setCaptionSaved] = useState(false);

  const commitCueEdit = async (cueIndex: number, rawText: string) => {
    setEditingCue(null);
    if (!onSaveCaptions || !captions) return;
    const cue = cueList[cueIndex];
    if (!cue) return;
    const trimmed = rawText.trim();
    if (trimmed === cue.text.trim()) return;

    const existing = captions.words ?? [];
    const inCue: { start: number; end: number; word: string }[] = [];
    const others: { start: number; end: number; word: string }[] = [];
    for (const w of existing) {
      if (w.start >= cue.start - 0.005 && w.start < cue.end - 0.005) {
        inCue.push(w);
      } else {
        others.push(w);
      }
    }

    const tokens = trimmed ? trimmed.split(/\s+/) : [];
    let replacement: { start: number; end: number; word: string }[] = [];
    if (tokens.length > 0 && tokens.length === inCue.length) {
      replacement = inCue.map((w, i) => ({ ...w, word: tokens[i] }));
    } else if (tokens.length > 0) {
      const span = Math.max(cue.end - cue.start, 0.25);
      const step = span / tokens.length;
      replacement = tokens.map((word, i) => ({
        start: Number((cue.start + i * step).toFixed(3)),
        end: Number((cue.start + (i + 1) * step).toFixed(3)),
        word,
      }));
    }

    const merged = [...others, ...replacement].sort((a, b) => a.start - b.start);
    await onSaveCaptions(merged);
    setCaptionSaved(true);
    setTimeout(() => setCaptionSaved(false), 1600);
  };

  const addCaptionAtPlayhead = async () => {
    if (!onSaveCaptions) return;
    const existing = captions?.words ?? [];
    const st = Math.max(0, Math.min(time, Math.max(duration - 0.6, 0)));
    const en = Math.min(st + 1.5, Math.max(duration, st + 0.5));
    const newWord = { start: Number(st.toFixed(3)), end: Number(en.toFixed(3)), word: "New caption" };
    const merged = [...existing, newWord].sort((a, b) => a.start - b.start);
    await onSaveCaptions(merged);
    setCaptionSaved(true);
    setTimeout(() => setCaptionSaved(false), 1600);
  };

  return (
    <div className="card overflow-hidden">
      <div className="no-scrollbar flex gap-1 overflow-x-auto border-b border-white/8 p-1.5">
        {(
          [
            { key: "captions", label: "Captions", icon: Captions },
            { key: "frame", label: "Frame", icon: Crop },
            { key: "audio", label: "Audio", icon: Volume2 },
            { key: "style", label: "Style", icon: Palette },
            { key: "text", label: "Overlays", icon: Type },
            { key: "meta", label: "Titles", icon: Sparkles },
          ] as const
        ).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex shrink-0 items-center gap-1.5 rounded-[9px] border px-3 py-2 text-[12px] font-medium transition ${
              tab === key
                ? "border-white/12 bg-gradient-to-b from-white/12 to-white/[0.03] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.16)]"
                : "border-transparent text-slate-400 hover:bg-white/[0.04] hover:text-slate-200"
            }`}
          >
            <Icon size={12.5} className={tab === key ? "text-violet-200" : ""} /> {label}
          </button>
        ))}
      </div>

      <div className="max-h-[54vh] space-y-4 overflow-y-auto p-4">
        {tab === "captions" && (
          <>
            <Toggle
              label="Show captions"
              hint="Turn off to hide captions in the preview and export."
              checked={clip.captions_enabled !== false}
              onChange={(v) => update({ captions_enabled: v })}
            />
            <Section title="Caption style">
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(CAPTION_LABELS).map(([key, meta]) => (
                  <button
                    key={key}
                    onClick={() => update({ caption_style: key })}
                    className={`rounded-lg border px-2.5 py-2 text-left text-[11.5px] transition ${
                      clip.caption_style === key
                        ? "border-violet-400/60 bg-violet-500/12 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                    }`}
                  >
                    {meta.label}
                    <span className="mt-1 block text-[9.5px] uppercase tracking-wide text-slate-400">
                      {meta.sub}
                    </span>
                  </button>
                ))}
              </div>
            </Section>
            <Section title="Position">
              <div className="grid grid-cols-3 gap-2">
                {(["top", "center", "bottom"] as const).map((p) => (
                  <button
                    key={p}
                    onClick={() => update({ caption_position: p })}
                    className={`rounded-lg border px-2 py-1.5 text-[11px] capitalize transition ${
                      (clip.caption_position ?? "bottom") === p
                        ? "border-violet-400/60 bg-violet-500/12 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-400"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </Section>
            <div>
              <label className="label flex justify-between">
                <span>Caption size</span>
                <span className="tabular-nums text-slate-400">{clip.caption_size ?? 100}%</span>
              </label>
              <input
                type="range"
                min={70}
                max={140}
                value={clip.caption_size ?? 100}
                onChange={(e) => update({ caption_size: Number(e.target.value) })}
                className="w-full accent-violet-500"
              />
            </div>
            <Section title={`Edit captions · ${cueList.length}`}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-[10.5px] text-slate-400">
                  Click any line to fix misheard words. Clear a line to remove it.
                </p>
                {captionSaved && (
                  <span className="shrink-0 text-[10px] font-medium text-emerald-400">
                    Saved
                  </span>
                )}
              </div>
              <div className="max-h-72 space-y-1 overflow-y-auto pr-0.5">
                {cueList.map((c, i) => {
                  const isEditing = editingCue === i;
                  return (
                    <div
                      key={`${c.start}-${i}`}
                      className="flex items-center gap-1.5 rounded-lg px-1.5 py-1 hover:bg-white/[0.04]"
                    >
                      <button
                        type="button"
                        onClick={() => seekTo(c.start)}
                        title="Jump to this caption"
                        className="w-9 shrink-0 font-mono text-[10px] text-slate-500 hover:text-violet-300"
                      >
                        {fmtTime(c.start)}
                      </button>
                      {isEditing ? (
                        <input
                          autoFocus
                          value={cueDraft}
                          onChange={(e) => setCueDraft(e.target.value)}
                          onBlur={() => commitCueEdit(i, cueDraft)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.currentTarget.blur();
                            } else if (e.key === "Escape") {
                              setEditingCue(null);
                            }
                          }}
                          aria-label={`Edit caption at ${fmtTime(c.start)}`}
                          className="min-w-0 flex-1 rounded-md border border-violet-400/70 bg-black/50 px-2 py-1 text-[11.5px] text-white outline-none"
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            seekTo(c.start);
                            setEditingCue(i);
                            setCueDraft(c.text);
                          }}
                          className="min-w-0 flex-1 rounded-md px-1.5 py-1 text-left text-[11.5px] text-slate-200 hover:bg-white/[0.06] hover:text-white"
                        >
                          {c.text}
                        </button>
                      )}
                    </div>
                  );
                })}
                {!cueList.length && (
                  <p className="text-[11px] text-slate-400">
                    No spoken words inside this window yet.
                  </p>
                )}
              </div>
              {onSaveCaptions && (
                <button
                  type="button"
                  onClick={addCaptionAtPlayhead}
                  className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.045] px-2.5 py-1.5 text-[11px] font-medium text-slate-200 transition hover:border-violet-400/50 hover:text-white"
                >
                  <Plus size={12} /> Add caption at {fmtTime(time)}
                </button>
              )}
            </Section>
          </>
        )}

        {tab === "frame" && (
          <>
            <Section title="Aspect ratio">
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(ASPECTS).map(([a, sub]) => (
                  <button
                    key={a}
                    onClick={() => update({ aspect: a })}
                    className={`rounded-lg border px-2.5 py-2 text-[11.5px] transition ${
                      clip.aspect === a
                        ? "border-violet-400/60 bg-violet-500/12 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                    }`}
                  >
                    {a}
                    <span className="mt-0.5 block text-[9.5px] text-slate-400">{sub}</span>
                  </button>
                ))}
              </div>
            </Section>
            <FramePanel
              clip={clip}
              update={update}
              time={time}
              seekTo={seekTo}
              autoFocus={autoFocus}
              trackPath={trackPath}
            />
            <Toggle
              label="Subtle zoom-in"
              hint="Slow push toward the subject during the clip"
              checked={clip.zoom}
              onChange={(v) => update({ zoom: v })}
            />
            <Toggle
              label="Remove dead air"
              hint="Cuts pauses over 0.55s while keeping sentences intact"
              checked={clip.smart_cuts}
              onChange={(v) => update({ smart_cuts: v })}
            />
          </>
        )}

        {tab === "audio" && (
          <>
            <div>
              <label className="label flex justify-between">
                <span>Original audio</span>
                <span className="tabular-nums text-slate-400">{Math.round(clip.volume * 100)}%</span>
              </label>
              <input
                type="range"
                min={0}
                max={2}
                step={0.05}
                value={clip.volume}
                onChange={(e) => update({ volume: Number(e.target.value) })}
                className="w-full accent-violet-500"
              />
            </div>
            <Toggle
              label="Reduce background noise"
              hint="FFT denoise before loudness normalisation"
              checked={clip.denoise}
              onChange={(v) => update({ denoise: v })}
            />
            <Section title="Background music">
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(MUSIC_LABELS).map(([m, label]) => (
                  <button
                    key={m}
                    onClick={() => update({ music: m })}
                    className={`rounded-lg border px-2.5 py-2 text-[11.5px] transition ${
                      clip.music === m
                        ? "border-violet-400/60 bg-violet-500/12 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[10.5px] leading-relaxed text-slate-400">
                Beds are generated locally (synthesised tones), so exports stay royalty-free.
              </p>
            </Section>
            <div>
              <label className="label flex justify-between">
                <span>Music level</span>
                <span className="tabular-nums text-slate-400">{Math.round(clip.music_volume * 100)}%</span>
              </label>
              <input
                type="range"
                min={0}
                max={0.5}
                step={0.01}
                value={clip.music_volume}
                onChange={(e) => update({ music_volume: Number(e.target.value) })}
                disabled={clip.music === "none"}
                className="w-full accent-violet-500 disabled:opacity-40"
              />
            </div>
          </>
        )}

        {tab === "style" && <StylePanel clip={clip} update={update} />}

        {tab === "text" && (
          <>
            <Section title="Text overlays">
              <button className="btn-ghost btn-sm w-full" onClick={addOverlay} disabled={overlays.length >= 4}>
                <Plus size={13} /> Add overlay {overlays.length >= 4 && "(max 4)"}
              </button>
            </Section>
            <div className="space-y-3">
              {overlays.map((o, i) => (
                <div key={o.id ?? i} className="space-y-2 rounded-lg glass-inset p-3">
                  <div className="flex items-center gap-2">
                    <input
                      className="input py-1.5 text-[12px]"
                      value={o.text}
                      onChange={(e) => patchOverlay(i, { text: e.target.value })}
                      placeholder="Overlay text"
                    />
                    <button
                      className="btn-ghost btn-sm shrink-0 px-2"
                      onClick={() => removeOverlay(i)}
                      aria-label="Remove overlay"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-[10px] text-slate-400">
                      From (s)
                      <input
                        type="number"
                        min={0}
                        max={duration}
                        step={0.1}
                        value={o.start}
                        onChange={(e) => patchOverlay(i, { start: Number(e.target.value) })}
                        className="input mt-1 py-1 text-[11px]"
                      />
                    </label>
                    <label className="text-[10px] text-slate-400">
                      To (s)
                      <input
                        type="number"
                        min={0}
                        max={duration}
                        step={0.1}
                        value={o.end}
                        onChange={(e) => patchOverlay(i, { end: Number(e.target.value) })}
                        className="input mt-1 py-1 text-[11px]"
                      />
                    </label>
                  </div>
                  <div className="flex gap-2">
                    <select
                      className="input py-1 text-[11px]"
                      value={o.x != null ? "free" : o.position}
                      onChange={(e) => {
                        const value = e.target.value;
                        if (value === "free") {
                          // Keep the current spot but switch to free placement.
                          patchOverlay(i, {
                            x: o.x ?? 0.1,
                            y: o.y ?? (o.position === "top" ? 0.06 : o.position === "center" ? 0.4 : 0.66),
                          });
                        } else {
                          patchOverlay(i, {
                            position: value as Overlay["position"],
                            x: undefined,
                            y: undefined,
                          });
                        }
                      }}
                    >
                      <option value="top">Top</option>
                      <option value="center">Center</option>
                      <option value="bottom">Bottom</option>
                      <option value="free">Free (drag)</option>
                    </select>
                    <input
                      type="color"
                      value={o.color}
                      onChange={(e) => patchOverlay(i, { color: e.target.value })}
                      className="h-8 w-10 rounded border border-white/10 bg-transparent"
                      aria-label="Overlay colour"
                    />
                    <input
                      type="range"
                      min={28}
                      max={96}
                      value={o.size}
                      onChange={(e) => patchOverlay(i, { size: Number(e.target.value) })}
                      className="flex-1 accent-violet-500"
                      aria-label="Overlay size"
                    />
                  </div>
                </div>
              ))}
              {overlays.length > 0 && (
                <p className="flex items-center gap-1.5 text-[10.5px] leading-relaxed text-slate-400">
                  <Move size={11} className="shrink-0 text-violet-300" />
                  Drag an overlay on the video to place it. Long text wraps automatically.
                </p>
              )}
              {!overlays.length && (
                <p className="text-[11px] text-slate-400">
                  Overlays are burned into the export at their own in/out times.
                </p>
              )}
            </div>
            <Section title="Branding watermark">
              <input
                className="input py-2 text-[12px]"
                value={clip.watermark}
                placeholder="@yourhandle"
                maxLength={40}
                onChange={(e) => update({ watermark: e.target.value })}
              />
              {clip.watermark.trim() && (
                <div className="mt-2.5 space-y-2 rounded-lg glass-inset p-2.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-slate-300">Watermark size</span>
                    <span className="font-mono text-slate-400">
                      {Math.round(clip.watermark_size ?? 100)}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min={50}
                    max={220}
                    step={5}
                    value={clip.watermark_size ?? 100}
                    onChange={(e) => update({ watermark_size: Number(e.target.value) })}
                    aria-label="Watermark size"
                    className="w-full accent-violet-500"
                  />
                  <div className="grid grid-cols-4 gap-1.5">
                    {[
                      { label: "S", v: 75 },
                      { label: "M", v: 100 },
                      { label: "L", v: 140 },
                      { label: "XL", v: 180 },
                    ].map((o) => (
                      <button
                        key={o.v}
                        type="button"
                        onClick={() => update({ watermark_size: o.v })}
                        className={`rounded-md border px-1 py-1 text-[10px] transition ${
                          Math.abs((clip.watermark_size ?? 100) - o.v) < 4
                            ? "border-violet-400/70 bg-violet-500/20 text-white"
                            : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-violet-400/50 hover:text-white"
                        }`}
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <p className="mt-1.5 text-[10.5px] text-slate-400">
                Frosted pill badge in the bottom-right corner. Leave blank to hide.
              </p>
            </Section>
          </>
        )}

        {tab === "meta" && (
          <>
            <Section title="Suggested titles">
              <div className="space-y-1.5">
                {clip.titles.map((t, i) => (
                  <button
                    key={`${t}-${i}`}
                    onClick={() => update({ selected_title: t })}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-[11.5px] leading-snug transition ${
                      clip.selected_title === t
                        ? "border-violet-400/60 bg-violet-500/12 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </Section>
            <Section title="Clip title">
              <input
                className="input py-2 text-[12px]"
                value={clip.selected_title}
                onChange={(e) => update({ selected_title: e.target.value })}
                maxLength={120}
              />
            </Section>
            <Section title="Opening hook">
              <textarea
                className="input min-h-[64px] py-2 text-[12px]"
                value={clip.hook}
                onChange={(e) => update({ hook: e.target.value })}
                maxLength={240}
              />
            </Section>
            <Section title="Description">
              <textarea
                className="input min-h-[72px] py-2 text-[12px]"
                value={clip.description}
                onChange={(e) => update({ description: e.target.value })}
                maxLength={300}
              />
            </Section>
            <Section title="Hashtags">
              <input
                className="input py-2 text-[12px]"
                value={clip.hashtags.join(" ")}
                onChange={(e) =>
                  update({
                    hashtags: e.target.value
                      .split(/\s+/)
                      .filter(Boolean)
                      .map((t) => (t.startsWith("#") ? t : `#${t}`)),
                  })
                }
              />
              <div className="mt-2 flex flex-wrap gap-1">
                {clip.hashtags.map((h) => (
                  <span key={h} className="chip text-[10px]">{h}</span>
                ))}
              </div>
            </Section>
            <div className="rounded-lg glass-inset p-3">
              <p className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
                Why this moment
              </p>
              <ul className="mt-1.5 space-y-1 text-[11px] leading-relaxed text-slate-400">
                {clip.reasons.map((r) => (
                  <li key={r}>· {r}</li>
                ))}
              </ul>
              <div className="mt-2 flex flex-wrap gap-1">
                {Object.entries(clip.components ?? {}).map(([k, v]) => (
                  <span key={k} className="chip text-[9.5px] capitalize">
                    {k} {v.toFixed(0)}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
