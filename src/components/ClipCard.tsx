import { useState } from "react";
import { Link } from "react-router-dom";
import { Play, Pencil, Download, Clock, Sparkles, Check, Loader2 } from "lucide-react";
import type { Clip } from "../lib/types";
import { api, fmtTime, mediaUrl } from "../lib/api";
import { ScoreRing } from "./ui";

export function ClipCard({
  clip,
  selected,
  onToggle,
  onError,
  queueIndex,
}: {
  clip: Clip;
  selected?: boolean;
  onToggle?: (id: string) => void;
  onError?: (message: string) => void;
  queueIndex?: number;
}) {
  const [downloading, setDownloading] = useState(false);

  const download = async () => {
    setDownloading(true);
    try {
      if (!clip.export_path) {
        await api.render(clip.id, {});
      }
      window.location.href = `/api/clips/${clip.id}/download`;
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Export failed");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div
      className={`card card-hover animate-rise group relative overflow-hidden ${
        selected ? "border-violet-400/60 shadow-[0_0_0_1px_rgba(167,139,250,0.35),0_20px_50px_-24px_rgba(129,102,255,0.85)]" : ""
      }`}
    >
      {onToggle && (
        <button
          onClick={() => onToggle(clip.id)}
          className={`absolute left-3 top-3 z-10 grid h-6 w-6 place-items-center rounded-md border transition ${
            selected
              ? "border-violet-300 bg-violet-500 text-white shadow-[0_0_16px_rgba(129,102,255,0.8)]"
              : "border-white/30 bg-black/45 text-transparent backdrop-blur-md hover:border-white/60"
          }`}
          aria-label={selected ? "Deselect clip" : "Select clip"}
        >
          <Check size={14} />
        </button>
      )}

      <Link to={`/editor/${clip.id}`} className="relative block aspect-video overflow-hidden bg-black/60">
        {clip.thumbnail ? (
          <img
            src={mediaUrl(clip.thumbnail)}
            alt={clip.selected_title}
            className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.04]"
          />
        ) : (
          <div className="grid h-full place-items-center text-slate-700">
            <Play size={28} />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/10 to-black/20" />
        <div className="absolute inset-x-3 top-3 flex justify-between">
          <span className="chip border-white/15 bg-black/45 backdrop-blur-md">{clip.category_label}</span>
          {queueIndex !== undefined && queueIndex >= 0 && (
            <span className="chip bg-violet-500/90 text-white">#{queueIndex + 1}</span>
          )}
        </div>
        <div className="absolute inset-x-3 bottom-3 flex items-end justify-between gap-2">
          <div className="min-w-0">
            <p className="line-clamp-2 text-[13.5px] font-semibold leading-snug text-white">
              {clip.selected_title || "Untitled moment"}
            </p>
            <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-300">
              <span className="rounded bg-black/60 px-1.5 py-0.5 tabular-nums">
                {fmtTime(clip.start)} – {fmtTime(clip.end)}
              </span>
              <span>{clip.duration.toFixed(0)}s</span>
            </div>
          </div>
          <div className="grid place-items-center rounded-full bg-black/65 p-2 opacity-0 backdrop-blur transition group-hover:opacity-100">
            <Play size={15} className="text-white" />
          </div>
        </div>
      </Link>

      <div className="relative flex items-center gap-3 p-3.5">
        <span className="pointer-events-none absolute inset-x-3 top-0 h-px bg-gradient-to-r from-transparent via-white/12 to-transparent" />
        <ScoreRing score={clip.score} size={46} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1 text-[11px] font-medium text-slate-400">
            <Sparkles size={11} className="text-violet-300" />
            {clip.reasons?.[0] ?? "Self-contained moment"}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px] text-slate-400">
            <span className="flex items-center gap-1">
              <Clock size={10} /> {clip.aspect} · {clip.caption_style}
            </span>
            {clip.export_path && <span className="text-emerald-400">exported</span>}
          </div>
        </div>
      </div>

      <div className="flex gap-2 px-3.5 pb-3.5">
        <Link to={`/editor/${clip.id}`} className="btn-ghost btn-sm flex-1">
          <Pencil size={13} /> Edit
        </Link>
        <button className="btn-ghost btn-sm flex-1" onClick={() => void download()} disabled={downloading}>
          {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
          {downloading ? "Rendering" : "Save MP4"}
        </button>
      </div>
    </div>
  );
}
