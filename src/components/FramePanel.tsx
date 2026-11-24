import { useState } from "react";
import {
  Crop,
  Diamond,
  LayoutPanelTop,
  Maximize2,
  Move,
  Plus,
  RotateCcw,
  PictureInPicture2,
  ScanFace,
  Sparkles,
  SplitSquareVertical,
  Trash2,
} from "lucide-react";
import type { Clip } from "../lib/types";
import { sampleKeyframes, samplePath } from "../lib/frame";
import { api } from "../lib/api";

type FrameMode = "manual" | "face-track" | "center" | "pad" | "dual" | "inset";

const MODES: { key: FrameMode; label: string; hint: string; icon: typeof Crop }[] = [
  { key: "manual", label: "Move frame", hint: "Drag the box on the video", icon: Move },
  { key: "face-track", label: "Auto face", hint: "Follows the subject", icon: ScanFace },
  { key: "dual", label: "Dual frame", hint: "Two people, split top/bottom", icon: SplitSquareVertical },
  { key: "inset", label: "Background + inset", hint: "Facecam over the full shot", icon: PictureInPicture2 },
  { key: "center", label: "Centered", hint: "Fixed centre crop", icon: Crop },
  { key: "pad", label: "Full frame", hint: "Whole shot, blurred backdrop", icon: Maximize2 },
];

/** mm:ss.s, for keyframe times. */
function formatTime(t: number): string {
  const safe = Math.max(t, 0);
  const m = Math.floor(safe / 60);
  const sec = safe - m * 60;
  return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
}

/** Quick camera placements for the single-panel crop. */
const QUICK: { key: string; label: string; x?: number; y?: number; zoom?: number }[] = [
  { key: "face", label: "Face close-up", y: 0.38, zoom: 2.2 },
  { key: "wide", label: "Full subject", y: 0.45, zoom: 1 },
  { key: "left", label: "Left", x: 0.22, zoom: 1.3 },
  { key: "right", label: "Right", x: 0.78, zoom: 1.3 },
  { key: "top", label: "Upper", y: 0.25, zoom: 1.4 },
  { key: "low", label: "Lower", y: 0.7, zoom: 1.4 },
];

function Row({
  label,
  value,
  min,
  max,
  step,
  onChange,
  suffix = "",
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  suffix?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-center justify-between text-[10.5px] text-slate-400">
        <span>{label}</span>
        <span className="font-mono tabular-nums text-slate-400">
          {value.toFixed(step < 0.1 ? 2 : 1)}
          {suffix}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-violet-500"
      />
    </label>
  );
}

export function FramePanel({
  clip,
  update,
  time = 0,
  seekTo,
  autoFocus,
  trackPath,
}: {
  clip: Clip;
  update: (patch: Partial<Clip>) => void;
  time?: number;
  seekTo?: (t: number) => void;
  autoFocus?: { x: number; y: number } | null;
  trackPath?: { times: number[]; x: number[]; y: number[] } | null;
}) {
  const mode = (clip.crop_mode || "manual") as FrameMode;
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState("");

  const snap = async () => {
    setBusy(true);
    setHint("");
    try {
      const s = await api.focusSuggestions(clip.id);
      if (mode === "dual") {
        update({
          dual_auto: false,
          dual_top_x: s.dual.top.x,
          dual_top_y: s.dual.top.y,
          dual_bottom_x: s.dual.bottom.x,
          dual_bottom_y: s.dual.bottom.y,
        });
        setHint("Centred each panel on a subject");
      } else if (mode === "inset") {
        // The facecam is usually the smaller subject: put the inset on a face.
        update({
          inset_x: s.single.x,
          inset_y: s.single.y,
          inset_zoom: Math.max(clip.inset_zoom ?? 1, 1.3),
        });
        setHint(
          s.single.faces
            ? "Inset centred on a face — drag it if that's the wrong person"
            : "No face found — centred the inset instead",
        );
      } else {
        update({
          crop_mode: "manual",
          crop_x: s.single.x,
          crop_y: s.single.y,
          crop_zoom: Math.max(clip.crop_zoom ?? 1, 1.4),
        });
        setHint(s.single.faces ? `Found ${s.single.faces} face${s.single.faces === 1 ? "" : "s"}` : "No face found — centred instead");
      }
    } catch (e) {
      setHint(e instanceof Error ? e.message : "Could not analyse the frame");
    } finally {
      setBusy(false);
    }
  };

  const reset = () =>
    update({
      crop_mode: "manual",
      crop_x: 0.5,
      crop_y: 0.45,
      crop_zoom: 1,
      dual_auto: true,
      dual_top_x: 0.28,
      dual_top_y: 0.45,
      dual_top_zoom: 1,
      dual_bottom_x: 0.72,
      dual_bottom_y: 0.45,
      dual_bottom_zoom: 1,
      inset_x: 0.5,
      inset_y: 0.5,
      inset_zoom: 1.8,
      inset_size: 0.3,
      inset_shape: "16:9",
      inset_pos_x: 0.78,
      inset_pos_y: 0.8,
      inset_bg_fit: "cover",
      inset_bg_zoom: 1,
      inset_border: true,
      inset_border_color: "#ffffff",
      inset_border_width: 5,
      inset_radius: 4,
      inset_shadow: true,
    });

  // ---- camera keyframes -------------------------------------------------
  const keyframes = [...(clip.keyframes ?? [])].sort((a, b) => a.t - b.t);
  const hasKeys = keyframes.length >= 2;
  // Position the playhead is currently showing, so a new key can pick it up.
  const currentPoint = () => {
    if (hasKeys) {
      const kf = sampleKeyframes(keyframes, time);
      if (kf) return kf;
    }
    // No keys yet: capture whatever the preview is showing right now — the
    // tracked subject in auto mode, otherwise the saved crop.
    if ((clip.crop_mode || "manual") === "face-track" && trackPath && trackPath.times.length > 1) {
      const s = samplePath(trackPath.times, trackPath.x, trackPath.y, time);
      if (s) return { x: s.x, y: s.y, zoom: Math.max(clip.crop_zoom ?? 1, 1.4) };
    }
    if (autoFocus && (clip.crop_mode || "manual") === "face-track") {
      return { x: autoFocus.x, y: autoFocus.y, zoom: Math.max(clip.crop_zoom ?? 1, 1.4) };
    }
    return {
      x: clip.crop_x ?? 0.5,
      y: clip.crop_y ?? 0.45,
      zoom: Math.max(clip.crop_zoom ?? 1, 1.4),
    };
  };

  const addKeyframe = () => {
    const p = currentPoint();
    const t = Math.min(Math.max(time, 0), Math.max(clip.duration ?? 0, 0.1));
    // Replace a keyframe that is already sitting on this moment.
    const kept = keyframes.filter((k) => Math.abs(k.t - t) > 0.25);
    update({
      keyframes: [...kept, { t: Math.round(t * 100) / 100, x: p.x, y: p.y, zoom: p.zoom }]
        .sort((a, b) => a.t - b.t),
      crop_mode: mode === "center" || mode === "pad" ? "manual" : mode,
    });
  };

  const removeKeyframe = (index: number) =>
    update({ keyframes: keyframes.filter((_, i) => i !== index) });

  const patchKeyframe = (index: number, patch: Partial<{ x: number; y: number; zoom: number }>) =>
    update({
      keyframes: keyframes.map((k, i) => (i === index ? { ...k, ...patch } : k)),
    });

  const topX = clip.dual_top_x ?? 0.28;
  const topY = clip.dual_top_y ?? 0.45;
  const topZ = clip.dual_top_zoom ?? 1;
  const botX = clip.dual_bottom_x ?? 0.72;
  const botY = clip.dual_bottom_y ?? 0.45;
  const botZ = clip.dual_bottom_zoom ?? 1;

  return (
    <div className="space-y-4">
      <div>
        <label className="label">Frame layout</label>
        <div className="grid grid-cols-2 gap-1.5">
          {MODES.map(({ key, label, hint: h, icon: Icon }) => {
            const active = mode === key;
            return (
              <button
                key={key}
                onClick={() =>
                  update(
                    key === "inset" && (clip.inset_zoom ?? null) === null
                      ? {
                          crop_mode: key,
                          // Start as a real facecam window rather than a
                          // full-frame crop that looks like nothing happened.
                          inset_zoom: 1.8,
                          inset_size: 0.3,
                          inset_pos_x: 0.78,
                          inset_pos_y: 0.8,
                          inset_shape: "16:9",
                          inset_radius: 4,
                          inset_border: true,
                          inset_border_color: "#ffffff",
                          inset_border_width: 5,
                          inset_shadow: true,
                        }
                      : { crop_mode: key },
                  )
                }
                aria-pressed={active}
                className={`flex items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition ${
                  active
                    ? "border-violet-400/70 bg-violet-500/15 text-white"
                    : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                }`}
              >
                <Icon size={13} className={active ? "mt-0.5 shrink-0 text-violet-300" : "mt-0.5 shrink-0 text-slate-400"} />
                <span className="min-w-0">
                  <span className="block text-[11.5px] font-medium leading-tight">{label}</span>
                  <span className="mt-0.5 block text-[9.5px] leading-snug text-slate-400">{h}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {mode === "manual" && (
        <>
          <div className="rounded-lg border border-violet-400/25 bg-violet-500/[0.07] px-2.5 py-2">
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-violet-100">
              <Move size={11} /> Drag the video to move the frame
            </p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">
              The box is what you keep. Everything outside is cut.
            </p>
          </div>

          <Row
            label="Zoom"
            value={Math.max(clip.crop_zoom ?? 1, 1)}
            min={1}
            max={4}
            step={0.05}
            suffix="×"
            onChange={(v) => update({ crop_zoom: v })}
          />
          <div className="grid grid-cols-2 gap-2">
            <Row label="Horizontal" value={clip.crop_x ?? 0.5} min={0} max={1} step={0.01} onChange={(v) => update({ crop_x: v })} />
            <Row label="Vertical" value={clip.crop_y ?? 0.45} min={0} max={1} step={0.01} onChange={(v) => update({ crop_y: v })} />
          </div>

          <div>
            <label className="label">Quick positions</label>
            <div className="grid grid-cols-3 gap-1.5">
              {QUICK.map((q) => (
                <button
                  key={q.key}
                  onClick={() =>
                    update({
                      crop_x: q.x ?? clip.crop_x ?? 0.5,
                      crop_y: q.y ?? clip.crop_y ?? 0.45,
                      crop_zoom: q.zoom ?? 1,
                    })
                  }
                  className="rounded-md glass-inset px-2 py-1.5 text-[10.5px] text-slate-300 transition hover:border-white/20 hover:text-white"
                >
                  {q.label}
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {(mode === "manual" || mode === "face-track") && (
        <div className="space-y-2 rounded-lg glass-inset p-2.5">
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              <Diamond size={10} className="text-violet-300" /> Camera keyframes
            </p>
            <span className="font-mono text-[9.5px] text-slate-400">{keyframes.length} set</span>
          </div>
          <p className="text-[10px] leading-relaxed text-slate-400">
            Park the playhead where you want the frame to be, then add a keyframe. The camera moves
            smoothly between them.
          </p>

          <button className="btn-ghost btn-sm w-full" onClick={addKeyframe} disabled={hasKeys && keyframes.some((k) => Math.abs(k.t - time) < 0.25)}>
            <Plus size={11} /> Add keyframe at {formatTime(time)}
          </button>

          {keyframes.length > 0 && (
            <ul className="space-y-1.5">
              {keyframes.map((kf, i) => {
                const active = Math.abs(kf.t - time) < 0.25;
                return (
                  <li
                    key={`${kf.t}-${i}`}
                    className={`rounded-md border px-2 py-1.5 transition ${
                      active ? "border-violet-400/50 bg-violet-500/10" : "border-white/10 bg-white/[0.05]"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <button
                        className="flex flex-1 items-center gap-1.5 text-left text-[11px] text-slate-200 hover:text-white"
                        onClick={() => seekTo?.(kf.t)}
                        title="Jump to this keyframe"
                      >
                        <Diamond size={9} className="text-violet-300" />
                        {formatTime(kf.t)}
                        <span className="font-mono text-[9.5px] text-slate-400">
                          {kf.x.toFixed(2)}, {kf.y.toFixed(2)} · {Math.max(kf.zoom ?? 1, 1).toFixed(2)}×
                        </span>
                      </button>
                      <button
                        className="rounded p-1 text-slate-400 transition hover:bg-white/10 hover:text-rose-300"
                        onClick={() => removeKeyframe(i)}
                        title="Delete keyframe"
                        aria-label="Delete keyframe"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <input
                        type="range"
                        min={1}
                        max={3}
                        step={0.05}
                        value={Math.max(kf.zoom ?? 1, 1)}
                        onChange={(e) => patchKeyframe(i, { zoom: Number(e.target.value) })}
                        className="w-full accent-violet-500"
                        aria-label={`Zoom at ${formatTime(kf.t)}`}
                      />
                      <span className="w-8 shrink-0 text-right font-mono text-[9.5px] text-slate-400">
                        {Math.max(kf.zoom ?? 1, 1).toFixed(1)}×
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          {hasKeys && (
            <div className="flex items-center justify-between gap-2 pt-0.5">
              <p className="text-[9.5px] leading-snug text-slate-400">
                Drag the box on the video to move the keyframe at the playhead.
              </p>
              <button
                className="shrink-0 rounded px-1.5 py-1 text-[10px] text-slate-400 transition hover:bg-white/10 hover:text-white"
                onClick={() => update({ keyframes: [] })}
              >
                Clear all
              </button>
            </div>
          )}
        </div>
      )}

      {mode === "dual" && (
        <>
          <div className="rounded-lg glass-inset px-2.5 py-2">
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-white">
              <LayoutPanelTop size={11} className="text-violet-300" /> Two panels, one video
            </p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">
              Top half shows one person, bottom half the other. Drag each half to reposition it.
            </p>
          </div>

          <div className="rounded-lg glass-inset p-2.5">
            <Row
              label="Zoom both panels"
              value={Math.max((topZ + botZ) / 2, 1)}
              min={1}
              max={6}
              step={0.05}
              suffix="×"
              onChange={(v) => update({ dual_top_zoom: v, dual_bottom_zoom: v })}
            />
            <div className="mt-1.5 grid grid-cols-4 gap-1.5">
              {[1, 1.5, 2, 3].map((z) => (
                <button
                  key={z}
                  onClick={() => update({ dual_top_zoom: z, dual_bottom_zoom: z })}
                  className="rounded-md border border-white/10 bg-white/[0.045] px-1 py-1 text-[10px] text-slate-300 transition hover:border-violet-400/50 hover:text-white"
                >
                  {z}×
                </button>
              ))}
            </div>
          </div>

          <label className="flex cursor-pointer items-center justify-between rounded-lg glass-inset px-2.5 py-2">
            <span className="text-[11.5px] text-slate-200">Auto-follow both subjects</span>
            <input
              type="checkbox"
              checked={clip.dual_auto !== false}
              onChange={(e) => update({ dual_auto: e.target.checked })}
              className="h-4 w-4 accent-violet-500"
            />
          </label>

          {(
            [
              { which: "top" as const, label: "Top panel", x: topX, y: topY, z: topZ, px: "dual_top_x", py: "dual_top_y", pz: "dual_top_zoom" },
              { which: "bottom" as const, label: "Bottom panel", x: botX, y: botY, z: botZ, px: "dual_bottom_x", py: "dual_bottom_y", pz: "dual_bottom_zoom" },
            ]
          ).map((p) => (
            <div key={p.which} className="space-y-2 rounded-lg glass-inset p-2.5">
              <p className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {p.label}
                <span className="font-mono text-[9.5px] font-normal normal-case tracking-normal text-slate-400">
                  {p.x.toFixed(2)}, {p.y.toFixed(2)}
                </span>
              </p>
              <div className="grid grid-cols-2 gap-2">
                <Row label="Horizontal" value={p.x} min={0} max={1} step={0.01} onChange={(v) => update({ [p.px]: v } as Partial<Clip>)} />
                <Row label="Vertical" value={p.y} min={0} max={1} step={0.01} onChange={(v) => update({ [p.py]: v } as Partial<Clip>)} />
              </div>
              <Row label="Zoom" value={Math.max(p.z, 1)} min={1} max={6} step={0.05} suffix="×" onChange={(v) => update({ [p.pz]: v } as Partial<Clip>)} />
            </div>
          ))}
        </>
      )}

      {mode === "inset" && (
        <>
          <div className="rounded-lg glass-inset px-2.5 py-2">
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-white">
              <PictureInPicture2 size={11} className="text-violet-300" /> Background + facecam window
            </p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">
              The whole shot stays as the background. The window on top is a second crop you choose —
              drag the picture to reframe it, drag its top bar to move it, drag the corner to resize.
            </p>
          </div>

          <div>
            <label className="label">Background</label>
            <div className="grid grid-cols-2 gap-1.5">
              {[
                { key: "cover", label: "Crop to fill", hint: "Drops the edges" },
                { key: "blur", label: "Blurred full shot", hint: "Keeps everything" },
              ].map((o) => (
                <button
                  key={o.key}
                  onClick={() => update({ inset_bg_fit: o.key })}
                  aria-pressed={(clip.inset_bg_fit ?? "cover") === o.key}
                  className={`rounded-lg border px-2 py-1.5 text-left transition ${
                    (clip.inset_bg_fit ?? "cover") === o.key
                      ? "border-violet-400/70 bg-violet-500/15 text-white"
                      : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                  }`}
                >
                  <span className="block text-[11px] font-medium">{o.label}</span>
                  <span className="text-[9.5px] text-slate-400">{o.hint}</span>
                </button>
              ))}
            </div>
          </div>

          {(clip.inset_bg_fit ?? "cover") === "cover" && (
            <div className="space-y-2 rounded-lg glass-inset p-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Background framing
              </p>
              <div className="grid grid-cols-2 gap-2">
                <Row label="Horizontal" value={clip.inset_bg_x ?? 0.5} min={0} max={1} step={0.01} onChange={(v) => update({ inset_bg_x: v })} />
                <Row label="Vertical" value={clip.inset_bg_y ?? 0.5} min={0} max={1} step={0.01} onChange={(v) => update({ inset_bg_y: v })} />
              </div>
              <Row
                label="Zoom"
                value={Math.max(clip.inset_bg_zoom ?? 1, 1)}
                min={1}
                max={4}
                step={0.05}
                suffix="×"
                onChange={(v) => update({ inset_bg_zoom: v })}
              />
            </div>
          )}

          <div className="space-y-2 rounded-lg border border-violet-400/25 bg-violet-500/[0.07] p-2.5">
            <p className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-violet-100">
              Inset window
              <span className="font-mono text-[9.5px] font-normal normal-case tracking-normal text-slate-300">
                {(clip.inset_x ?? 0.5).toFixed(2)}, {(clip.inset_y ?? 0.5).toFixed(2)}
              </span>
            </p>
            <Row
              label="Size"
              value={clip.inset_size ?? 0.3}
              min={0.12}
              max={0.7}
              step={0.01}
              suffix=""
              onChange={(v) => update({ inset_size: v })}
            />
            <div className="grid grid-cols-2 gap-2">
              <Row label="Crop X" value={clip.inset_x ?? 0.5} min={0} max={1} step={0.01} onChange={(v) => update({ inset_x: v })} />
              <Row label="Crop Y" value={clip.inset_y ?? 0.5} min={0} max={1} step={0.01} onChange={(v) => update({ inset_y: v })} />
            </div>
            <Row
              label="Crop zoom"
              value={Math.max(clip.inset_zoom ?? 1, 1)}
              min={1}
              max={6}
              step={0.05}
              suffix="×"
              onChange={(v) => update({ inset_zoom: v })}
            />
            <div className="grid grid-cols-5 gap-1.5">
              {[1, 1.5, 2, 3, 5].map((z) => (
                <button
                  key={z}
                  onClick={() => update({ inset_zoom: z })}
                  className={`rounded-md border px-1 py-1 text-[10px] transition ${
                    Math.abs((clip.inset_zoom ?? 1) - z) < 0.02
                      ? "border-violet-400/70 bg-violet-500/20 text-white"
                      : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-violet-400/50 hover:text-white"
                  }`}
                >
                  {z}×
                </button>
              ))}
            </div>
            <div>
              <label className="label">Window shape</label>
              <div className="grid grid-cols-4 gap-1.5">
                {["16:9", "4:3", "1:1", "9:16"].map((sh) => (
                  <button
                    key={sh}
                    onClick={() => update({ inset_shape: sh })}
                    aria-pressed={(clip.inset_shape ?? "16:9") === sh}
                    className={`rounded-md border px-1 py-1 text-[10.5px] transition ${
                      (clip.inset_shape ?? "16:9") === sh
                        ? "border-violet-400/70 bg-violet-500/20 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                    }`}
                  >
                    {sh}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Row label="Place X" value={clip.inset_pos_x ?? 0.78} min={0} max={1} step={0.01} onChange={(v) => update({ inset_pos_x: v })} />
              <Row label="Place Y" value={clip.inset_pos_y ?? 0.8} min={0} max={1} step={0.01} onChange={(v) => update({ inset_pos_y: v })} />
            </div>
            <div className="space-y-2.5 rounded-lg glass-inset p-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Window styling
              </p>

              <label className="flex cursor-pointer items-center justify-between">
                <span className="text-[11px] text-slate-200">Outline</span>
                <input
                  type="checkbox"
                  checked={clip.inset_border !== false}
                  onChange={(e) => update({ inset_border: e.target.checked })}
                  className="h-4 w-4 accent-violet-500"
                />
              </label>

              {clip.inset_border !== false && (
                <>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {[
                      { hex: "#ffffff", name: "White" },
                      { hex: "#22d3ee", name: "Cyan" },
                      { hex: "#a78bfa", name: "Violet" },
                      { hex: "#f472b6", name: "Pink" },
                      { hex: "#facc15", name: "Yellow" },
                      { hex: "#4ade80", name: "Green" },
                      { hex: "#0f172a", name: "Ink" },
                    ].map((c) => {
                      const active =
                        (clip.inset_border_color ?? "#ffffff").toLowerCase() === c.hex;
                      return (
                        <button
                          key={c.hex}
                          onClick={() => update({ inset_border_color: c.hex })}
                          title={c.name}
                          aria-label={`${c.name} outline`}
                          aria-pressed={active}
                          className={`h-6 w-6 rounded-full border-2 transition ${
                            active
                              ? "scale-110 border-white shadow-[0_0_0_2px_rgba(139,92,246,0.55)]"
                              : "border-white/25 hover:border-white/60"
                          }`}
                          style={{ background: c.hex }}
                        />
                      );
                    })}
                    <label
                      className="relative h-6 w-6 cursor-pointer overflow-hidden rounded-full border-2 border-white/25 bg-[conic-gradient(#f87171,#fbbf24,#4ade80,#22d3ee,#a78bfa,#f87171)]"
                      title="Pick any colour"
                    >
                      <input
                        type="color"
                        value={clip.inset_border_color ?? "#ffffff"}
                        onChange={(e) => update({ inset_border_color: e.target.value })}
                        className="absolute inset-0 cursor-pointer opacity-0"
                        aria-label="Custom outline colour"
                      />
                    </label>
                    <span className="ml-auto font-mono text-[9.5px] uppercase text-slate-400">
                      {clip.inset_border_color ?? "#ffffff"}
                    </span>
                  </div>

                  <Row
                    label="Thickness"
                    value={clip.inset_border_width ?? 5}
                    min={1}
                    max={16}
                    step={1}
                    suffix=""
                    onChange={(v) => update({ inset_border_width: v })}
                  />
                </>
              )}

              <Row
                label="Corner curve"
                value={clip.inset_radius ?? 4}
                min={0}
                max={50}
                step={1}
                suffix="%"
                onChange={(v) => update({ inset_radius: v })}
              />
              <div className="grid grid-cols-4 gap-1.5">
                {[
                  { label: "Square", v: 0 },
                  { label: "Soft", v: 4 },
                  { label: "Round", v: 12 },
                  { label: "Pill", v: 40 },
                ].map((o) => (
                  <button
                    key={o.v}
                    onClick={() => update({ inset_radius: o.v })}
                    className={`rounded-md border px-1 py-1 text-[10px] transition ${
                      Math.abs((clip.inset_radius ?? 4) - o.v) < 0.6
                        ? "border-violet-400/70 bg-violet-500/20 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-violet-400/50 hover:text-white"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>

              <label className="flex cursor-pointer items-center justify-between pt-0.5">
                <span className="text-[11px] text-slate-200">Soft shadow</span>
                <input
                  type="checkbox"
                  checked={clip.inset_shadow !== false}
                  onChange={(e) => update({ inset_shadow: e.target.checked })}
                  className="h-4 w-4 accent-violet-500"
                />
              </label>
            </div>
            <div>
              <label className="label">Quick corners</label>
              <div className="grid grid-cols-4 gap-1.5">
                {[
                  { label: "↖", x: 0.2, y: 0.2 },
                  { label: "↗", x: 0.8, y: 0.2 },
                  { label: "↙", x: 0.2, y: 0.8 },
                  { label: "↘", x: 0.8, y: 0.8 },
                ].map((c) => (
                  <button
                    key={c.label}
                    onClick={() => update({ inset_pos_x: c.x, inset_pos_y: c.y })}
                    className="rounded-md glass-inset py-1 text-[12px] text-slate-300 transition hover:border-white/20 hover:text-white"
                    aria-label={`Put the inset at ${c.label}`}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {mode === "pad" && (
        <div className="space-y-2">
          <div className="rounded-lg border border-violet-400/25 bg-violet-500/[0.07] px-2.5 py-2">
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-violet-100">
              <Maximize2 size={11} /> Scale to fill more of the frame
            </p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">
              The whole shot stays in frame. Raising the zoom enlarges it and trims the
              edges that spill outside — it never crops into the middle of the picture.
            </p>
          </div>
          <Row
            label="Fill"
            value={Math.max(clip.crop_zoom ?? 1, 1)}
            min={1}
            max={3}
            step={0.05}
            suffix="×"
            onChange={(v) => update({ crop_zoom: v })}
          />
          {(clip.crop_zoom ?? 1) > 1.01 && (
            <button className="btn-ghost btn-sm w-full" onClick={() => update({ crop_zoom: 1 })}>
              <RotateCcw size={11} /> Reset to full frame
            </button>
          )}
        </div>
      )}

      {mode !== "pad" && mode !== "center" && (
        <div>
          <button className="btn-ghost btn-sm w-full" onClick={() => void snap()} disabled={busy}>
            {busy ? <Sparkles size={12} className="animate-pulse" /> : <ScanFace size={12} />}
            {busy ? "Detecting…" : "Snap to subject"}
          </button>
          {hint && <p className="mt-1.5 text-center text-[10px] text-slate-400">{hint}</p>}
        </div>
      )}

      {mode !== "pad" && mode !== "center" && (
        <button className="btn-ghost btn-sm w-full" onClick={reset}>
          <RotateCcw size={11} /> Reset frame
        </button>
      )}

      <p className="text-[10px] leading-relaxed text-slate-500">
        The preview box matches the exported crop exactly.
      </p>
    </div>
  );
}
