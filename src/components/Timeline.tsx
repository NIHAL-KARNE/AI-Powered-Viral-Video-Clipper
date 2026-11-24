import { useMemo, useRef } from "react";
import { Scissors } from "lucide-react";
import type { Clip } from "../lib/types";
import { fmtTime, mediaUrl } from "../lib/api";
const waveHeights = (count: number, seed = 7) =>
  Array.from({ length: count }, (_, i) => {
    const a = Math.sin((i + seed) * 1.7) * 0.5 + 0.5;
    const b = Math.sin((i + seed) * 0.43 + 1.2) * 0.3 + 0.5;
    return 12 + (a * 0.65 + b * 0.35) * 82;
  });
import type { CaptionData } from "./Inspector";

export function Timeline({
  clip,
  captions,
  time,
  effectiveStart,
  effectiveEnd,
  onSeek,
  onTrim,
  onExtend,
}: {
  clip: Clip;
  captions: CaptionData | null;
  time: number;
  effectiveStart: number;
  effectiveEnd: number;
  onSeek: (local: number) => void;
  onTrim: (patch: { trim_start?: number; trim_end?: number }) => void;
  onExtend?: (patch: { start?: number; end?: number }) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const duration = Math.max(clip.duration, 1);
  const trimStartPct = (clip.trim_start / duration) * 100;
  const trimEndPct = ((duration - clip.trim_end) / duration) * 100;
  const playheadPct = (Math.min(Math.max(time, 0), duration) / duration) * 100;
  const waves = useMemo(() => waveHeights(140), []);
  const cues = captions?.cues ?? [];

  const seek = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const frac = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
    onSeek(frac * duration);
  };

  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[13px] font-semibold text-white">
          <Scissors size={14} className="text-violet-300" /> Timeline
        </h3>
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <span className="rounded-md border border-white/10 bg-white/[0.06] px-1.5 py-0.5 tabular-nums shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]">
            in {fmtTime(effectiveStart)}
          </span>
          <span className="rounded-md border border-white/10 bg-white/[0.06] px-1.5 py-0.5 tabular-nums shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]">
            out {fmtTime(effectiveEnd)}
          </span>
          <span className="text-slate-500">{(effectiveEnd - effectiveStart).toFixed(1)}s</span>
        </div>
      </div>

      <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        <span>V1</span>
        <span className="font-normal normal-case tracking-normal text-slate-500">video · drag to scrub</span>
      </div>
      <div
        ref={trackRef}
        className="relative h-16 cursor-ew-resize touch-none select-none overflow-hidden rounded-xl border border-white/10 bg-black/50 shadow-[inset_0_1px_0_rgba(255,255,255,0.06),inset_0_10px_24px_-16px_rgba(0,0,0,0.95)]"
        onPointerDown={(e) => {
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
          seek(e.clientX);
        }}
        onPointerMove={(e) => {
          if (e.buttons === 1) seek(e.clientX);
        }}
      >
        <div className="absolute inset-0 flex">
          {Array.from({ length: 20 }).map((_, i) => (
            <div
              key={i}
              className="h-full flex-1 border-r border-black/40"
              style={{
                background: clip.thumbnail
                  ? `url(${mediaUrl(clip.thumbnail)}) center/${20 * 100}% 100%`
                  : `linear-gradient(180deg,hsl(${250 + i * 2} 35% ${14 + (i % 5) * 3}%),hsl(${250 + i * 2} 30% 8%))`,
              }}
            />
          ))}
        </div>
        <div className="pointer-events-none absolute inset-y-0 left-0 bg-black/72" style={{ width: `${trimStartPct}%` }} />
        <div className="pointer-events-none absolute inset-y-0 right-0 bg-black/72" style={{ width: `${100 - trimEndPct}%` }} />
        <div
          className="pointer-events-none absolute inset-y-0 border-x-2 border-violet-400"
          style={{ left: `${trimStartPct}%`, width: `${Math.max(trimEndPct - trimStartPct, 0)}%` }}
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2">
          {cues.map((c, i) => (
            <span
              key={i}
              className="absolute bottom-0 h-1.5 rounded-sm bg-teal-300/70"
              style={{
                left: `${(c.start / duration) * 100}%`,
                width: `${Math.max(((c.end - c.start) / duration) * 100, 0.4)}%`,
              }}
            />
          ))}
        </div>
        <div className="pointer-events-none absolute inset-y-0 z-10 w-0.5 bg-white" style={{ left: `${playheadPct}%` }}>
          <span className="absolute -top-0.5 left-1/2 h-2.5 w-2.5 -translate-x-1/2 rounded-full bg-white shadow" />
        </div>
      </div>

      <div className="mb-1 mt-3 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        <span>A1</span>
        <span className="font-normal normal-case tracking-normal text-slate-500">original audio</span>
        {clip.denoise && <span className="chip py-0 text-[9px]">denoised</span>}
        {clip.music !== "none" && <span className="chip py-0 text-[9px]">+ music</span>}
      </div>
      <div className="relative h-9 overflow-hidden rounded-lg border border-white/10 bg-black/40">
        <div className="absolute inset-0 top-1/2 flex h-full -translate-y-1/2 items-center gap-px overflow-hidden px-1">
          {waves.map((h, i) => {
            const t = (i / waves.length) * duration;
            const active = t >= effectiveStart && t <= effectiveEnd;
            return (
              <span
                key={i}
                className={`min-w-0 flex-1 basis-0 rounded-full ${active ? "bg-teal-300/70" : "bg-slate-600/50"}`}
                style={{ height: `${Math.max(h, 8)}%` }}
              />
            );
          })}
        </div>
        {clip.music !== "none" && <div className="absolute inset-x-0 bottom-0 h-2 bg-violet-400/25" />}
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/80" style={{ left: `${playheadPct}%` }} />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label flex justify-between">
            <span>Trim in</span>
            <span className="tabular-nums text-slate-400">{clip.trim_start.toFixed(1)}s</span>
          </label>
          <input
            type="range"
            min={0}
            max={Math.max(duration - 2, 1)}
            step={0.1}
            value={clip.trim_start}
            onChange={(e) => {
              const v = Math.min(Number(e.target.value), duration - clip.trim_end - 1);
              onTrim({ trim_start: Math.max(v, 0) });
            }}
            className="w-full accent-violet-500"
          />
        </div>
        <div>
          <label className="label flex justify-between">
            <span>Trim out</span>
            <span className="tabular-nums text-slate-400">{clip.trim_end.toFixed(1)}s</span>
          </label>
          <input
            type="range"
            min={0}
            max={Math.max(duration - 2, 1)}
            step={0.1}
            value={clip.trim_end}
            onChange={(e) => {
              const v = Math.min(Number(e.target.value), duration - clip.trim_start - 1);
              onTrim({ trim_end: Math.max(v, 0) });
            }}
            className="w-full accent-violet-500"
          />
        </div>
      </div>

      {onExtend && (
        <div className="mt-3.5 grid gap-3 border-t border-white/[0.08] pt-3 sm:grid-cols-2">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <span className="block text-[10.5px] font-medium uppercase tracking-wider text-slate-400">
                Extend beginning
              </span>
              <span className="font-mono text-[10.5px] text-slate-300">
                Starts at {fmtTime(clip.start, true)}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {[-5, -1, 1].map((delta) => {
                const nextStart = Math.max(0, Number((clip.start + delta).toFixed(2)));
                const disabled =
                  (delta < 0 && clip.start <= 0.05) ||
                  (delta > 0 && clip.end - nextStart < 1.5);
                return (
                  <button
                    key={delta}
                    type="button"
                    disabled={disabled}
                    onClick={() => onExtend({ start: nextStart })}
                    className="rounded-md border border-white/10 bg-white/[0.05] px-2 py-1 text-[10.5px] font-medium tabular-nums text-slate-200 transition hover:border-violet-400/60 hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    {delta > 0 ? `+${delta}s` : `${delta}s`}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <span className="block text-[10.5px] font-medium uppercase tracking-wider text-slate-400">
                Extend ending
              </span>
              <span className="font-mono text-[10.5px] text-slate-300">
                Ends at {fmtTime(clip.end, true)}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {[-1, 1, 5].map((delta) => {
                const maxEnd = clip.project_duration ?? clip.end + 60;
                const nextEnd = Math.min(maxEnd, Number((clip.end + delta).toFixed(2)));
                const disabled =
                  (delta > 0 && clip.project_duration != null && clip.end >= clip.project_duration - 0.05) ||
                  (delta < 0 && nextEnd - clip.start < 1.5);
                return (
                  <button
                    key={delta}
                    type="button"
                    disabled={disabled}
                    onClick={() => onExtend({ end: nextEnd })}
                    className="rounded-md border border-white/10 bg-white/[0.05] px-2 py-1 text-[10.5px] font-medium tabular-nums text-slate-200 transition hover:border-violet-400/60 hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    {delta > 0 ? `+${delta}s` : `${delta}s`}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
