import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Play,
  Pause,
  Undo2,
  Redo2,
  Download,
  Loader2,
  Check,
  RotateCcw,
  Sparkles,
  Crop,
} from "lucide-react";
import { api, fmtTime, mediaUrl } from "../lib/api";
import type { Clip } from "../lib/types";
import { CaptionPreview, type CaptionWord } from "../components/CaptionPreview";
import { FramePreview, FaceHint } from "../components/FramePreview";
import { Inspector, type CaptionData, type InspectorTab } from "../components/Inspector";
import { Timeline } from "../components/Timeline";
import { ErrorNote, ScoreBadge } from "../components/ui";
import { OverlayLayer } from "../components/OverlayLayer";

const ASPECT_CLASS: Record<string, string> = {
  "9:16": "aspect-[9/16]",
  "1:1": "aspect-square",
  "4:5": "aspect-[4/5]",
  "16:9": "aspect-video",
};

export default function EditorPage() {
  const { id = "" } = useParams();
  const [clip, setClip] = useState<Clip | null>(null);
  const [projectTitle, setProjectTitle] = useState("");
  const [captions, setCaptions] = useState<CaptionData | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [renderResult, setRenderResult] = useState<{ url: string; size: number } | null>(null);
  const [showRendered, setShowRendered] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [autoFocus, setAutoFocus] = useState<{ x: number; y: number } | null>(null);
  const [trackPath, setTrackPath] = useState<{ times: number[]; x: number[]; y: number[] } | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("captions");

  const videoRef = useRef<HTMLVideoElement>(null);
  const bottomRef = useRef<HTMLVideoElement>(null);
  const saveTimer = useRef<number | null>(null);
  const pendingRef = useRef<Partial<Clip>>({});

  useEffect(() => {
    let alive = true;
    Promise.all([api.clip(id), api.captions(id)])
      .then(([c, caps]) => {
        if (!alive) return;
        setClip(c);
        setProjectTitle((c as Clip & { project_title?: string }).project_title ?? "");
        setCaptions(caps as CaptionData);
        setLoaded(true);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : "Could not load clip"));
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    if (!clip || (clip.crop_mode !== "face-track" && clip.crop_mode !== "dual")) return;
    if (clip.crop_mode === "dual" && clip.dual_auto === false) return;
    let alive = true;
    api
      .focusSuggestions(clip.id)
      .then((s) => {
        if (!alive) return;
        setAutoFocus({ x: s.single.x, y: s.single.y });
        // The renderer's camera path, so the preview pans like the export does.
        setTrackPath(s.path && s.path.times.length > 1 ? s.path : null);
      })
      .catch(() => {
        /* face tracking is a nicety; fall back to the stored crop */
      });
    return () => {
      alive = false;
    };
  }, [clip?.id, clip?.crop_mode, clip?.dual_auto, clip?.aspect, clip?.crop_zoom]);

  const clipStart = clip?.start ?? 0;
  const extendClip = async (patch: { start?: number; end?: number }) => {
    if (!clip) return;
    const saved = await api.patchClip(clip.id, patch);
    setClip((c) => (c ? { ...c, ...saved } : saved));
    const freshCaptions = await api.captions(clip.id);
    setCaptions({ cues: freshCaptions.cues, words: freshCaptions.words ?? [] });
  };

  const saveCaptions = async (words: { start: number; end: number; word: string }[]) => {
    if (!clip) return;
    const updated = await api.saveCaptions(clip.id, words);
    setCaptions(updated);
    setClip((c) => (c ? { ...c, word_count: updated.words.length } : c));
  };

  const clipDuration = clip?.duration ?? 1;
  const effectiveStart = clip?.trim_start ?? 0;
  const sourceWidth = clip?.source_width ?? 1920;
  const sourceHeight = clip?.source_height ?? 1080;
  const effectiveEnd = Math.max(clipDuration - (clip?.trim_end ?? 0), effectiveStart + 1);

  const flush = useCallback(async () => {
    const patch = pendingRef.current;
    pendingRef.current = {};
    if (!Object.keys(patch).length) return;
    setSaving(true);
    try {
      const updated = await api.patchClip(id, patch);
      setClip((prev) => (prev ? { ...prev, ...updated } : prev));
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save changes");
    } finally {
      setSaving(false);
    }
  }, [id]);

  const update = useCallback(
    (patch: Partial<Clip>) => {
      setClip((prev) => (prev ? { ...prev, ...patch } : prev));
      pendingRef.current = { ...pendingRef.current, ...patch };
      setDirty(true);
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => void flush(), 600);
    },
    [flush],
  );

  useEffect(() => () => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
  }, []);

  const seekTo = useCallback(
    (local: number) => {
      const v = videoRef.current;
      const clamped = Math.min(Math.max(local, 0), clipDuration);
      if (v) v.currentTime = clipStart + clamped;
      setTime(clamped);
    },
    [clipStart, clipDuration],
  );

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      if (time < effectiveStart || time >= effectiveEnd - 0.06) {
        seekTo(effectiveStart);
      }
      void v.play();
    } else {
      v.pause();
    }
  }, [time, effectiveStart, effectiveEnd, seekTo]);

  const onTimeUpdate = () => {
    const v = videoRef.current;
    if (!v) return;
    const local = v.currentTime - clipStart;
    if (local >= effectiveEnd) {
      v.pause();
      seekTo(effectiveStart);
      return;
    }
    setTime(Math.max(local, 0));
  };

  const undo = async () => {
    await flush();
    try {
      setClip(await api.undo(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Nothing to undo");
    }
  };
  const redo = async () => {
    await flush();
    try {
      setClip(await api.redo(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Nothing to redo");
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.code === "ArrowLeft") {
        seekTo(time - 1);
      } else if (e.code === "ArrowRight") {
        seekTo(time + 1);
      } else if (e.code === "KeyZ" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void (e.shiftKey ? redo() : undo());
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const exportClip = async () => {
    setRendering(true);
    setError("");
    try {
      await flush();
      const res = await api.render(id, {});
      setRenderResult(res);
      setShowRendered(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Render failed");
    } finally {
      setRendering(false);
    }
  };

  if (!loaded) {
    return error ? <ErrorNote message={error} /> : <div className="skeleton h-[70vh]" />;
  }
  if (!clip) return <ErrorNote message={error || "Clip not found"} />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <Link
          to={`/project/${clip.project_id}`}
          className="inline-flex items-center gap-1.5 hover:text-slate-300"
        >
          <ArrowLeft size={13} /> Back to project
        </Link>
        <span>/</span>
        <span className="max-w-[38ch] truncate text-slate-400">{projectTitle}</span>
        <span className="ml-auto flex items-center gap-2">
          {saving ? (
            <span className="flex items-center gap-1.5 text-slate-400">
              <Loader2 size={12} className="animate-spin" /> Saving
            </span>
          ) : dirty ? (
            <span className="text-amber-300/80">Unsaved changes</span>
          ) : (
            <span className="flex items-center gap-1.5 text-emerald-300/80">
              <Check size={12} /> All changes saved
            </span>
          )}
        </span>
      </div>

      {error && <ErrorNote message={error} onClose={() => setError("")} />}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-4">
          <div className="card p-4 sm:p-5">
            <div className="flex flex-col items-center">
              <div
                className={`relative w-full overflow-hidden rounded-2xl bg-black shadow-2xl ${ASPECT_CLASS[clip.aspect] ?? ASPECT_CLASS["9:16"]}`}
                style={{
                  maxWidth: clip.aspect === "9:16" ? "min(100%, 370px)" : clip.aspect === "4:5" ? "min(100%, 470px)" : "100%",
                  // Captions size from this box's height (cqh), exactly as the
                  // export sizes them from the output frame's height.
                  containerType: "size",
                }}
              >
                {showRendered && renderResult ? (
                  <video
                    src={mediaUrl(renderResult.url)}
                    controls
                    autoPlay
                    className="h-full w-full bg-black object-contain"
                  />
                ) : (
                  <>
                    <FramePreview
                      clip={clip}
                      sourceWidth={sourceWidth}
                      sourceHeight={sourceHeight}
                      videoRef={videoRef}
                      bottomRef={bottomRef}
                      autoFocus={autoFocus}
                      trackPath={trackPath}
                      time={time}
                      handlers={{
                        onTimeUpdate,
                        onPlay: () => setPlaying(true),
                        onPause: () => setPlaying(false),
                        onLoadedMetadata: () => {
                          const v = videoRef.current;
                          if (v) v.currentTime = clipStart + effectiveStart;
                        },
                      }}
                      onFocusChange={(f) => {
                        const keys = clip.keyframes ?? [];
                        if (keys.length >= 2) {
                          // With a camera path set up, dragging moves the nearest
                          // keyframe instead of the whole clip's position.
                          let nearest = 0;
                          keys.forEach((k, i) => {
                            if (Math.abs(k.t - time) < Math.abs(keys[nearest].t - time)) nearest = i;
                          });
                          update({
                            keyframes: keys.map((k, i) =>
                              i === nearest
                                ? { ...k, x: f.x ?? k.x, y: f.y ?? k.y }
                                : k,
                            ),
                          });
                          return;
                        }
                        update({
                          crop_mode: "manual",
                          crop_x: f.x ?? clip.crop_x,
                          crop_y: f.y ?? clip.crop_y,
                        });
                      }}
                      onInsetChange={(part, f) => {
                        if (part === "bg") {
                          update({
                            inset_bg_x: Math.min(Math.max(f.x ?? clip.inset_bg_x ?? 0.5, 0), 1),
                            inset_bg_y: Math.min(Math.max(f.y ?? clip.inset_bg_y ?? 0.5, 0), 1),
                          });
                        } else if (part === "inset") {
                          update({
                            inset_x: Math.min(Math.max(f.x ?? clip.inset_x ?? 0.5, 0), 1),
                            inset_y: Math.min(Math.max(f.y ?? clip.inset_y ?? 0.5, 0), 1),
                          });
                        } else if (part === "pos") {
                          update({
                            inset_pos_x: Math.min(Math.max(f.x ?? clip.inset_pos_x ?? 0.78, 0), 1),
                            inset_pos_y: Math.min(Math.max(f.y ?? clip.inset_pos_y ?? 0.8, 0), 1),
                          });
                        } else {
                          update({
                            inset_size: Math.min(Math.max(f.size ?? clip.inset_size ?? 0.3, 0.12), 0.7),
                          });
                        }
                      }}
                      onDualChange={(which, f) =>
                        update(
                          which === "top"
                            ? {
                                dual_auto: false,
                                dual_top_x: f.x ?? clip.dual_top_x,
                                dual_top_y: f.y ?? clip.dual_top_y,
                                dual_top_zoom: f.zoom ?? clip.dual_top_zoom,
                              }
                            : {
                                dual_auto: false,
                                dual_bottom_x: f.x ?? clip.dual_bottom_x,
                                dual_bottom_y: f.y ?? clip.dual_bottom_y,
                                dual_bottom_zoom: f.zoom ?? clip.dual_bottom_zoom,
                              },
                        )
                      }
                    >
                      {/* Darkening for caption legibility is drawn by the export as
                          part of the caption styling, not as a gradient, so the
                          preview no longer over-darkens the lower third. */}
                      {clip.captions_enabled !== false && (
                        <CaptionPreview
                          words={(captions?.words ?? []) as CaptionWord[]}
                          time={time}
                          style={clip.caption_style}
                          position={clip.caption_position ?? "bottom"}
                          size={clip.caption_size ?? 100}
                          accent={clip.accent_color}
                          fontOverride={clip.caption_font || undefined}
                          keywords={clip.keywords_enabled !== false}
                          emoji={clip.emoji_enabled !== false}
                          captionWords={clip.caption_words ?? 5}
                        />
                      )}
                      {clip.headline_enabled !== false &&
                        clip.headline &&
                        time <= (clip.headline_seconds ?? 4) && (
                          <div
                            className="pointer-events-none absolute inset-x-4 z-20 flex flex-col items-center gap-1.5 pt-[5.5%] text-center"
                            style={{
                              animation: "headlineIn 320ms ease-out",
                            }}
                          >
                            <span
                              className="max-w-full text-balance font-extrabold leading-tight text-white"
                              style={{
                                fontSize: clip.aspect === "16:9" ? "22px" : "19px",
                                textShadow: "0 2px 10px rgba(0,0,0,0.85)",
                              }}
                            >
                              {clip.headline}
                            </span>
                            <span
                              className="h-[3px] w-16 rounded-full"
                              style={{ background: clip.accent_color ?? "#a78bfa" }}
                            />
                          </div>
                        )}
                      {clip.progress_bar && (
                        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 h-[11px] bg-black/35">
                          <div
                            className="h-full"
                            style={{
                              width: `${Math.min(Math.max(effectiveEnd ? (time - effectiveStart) / Math.max(effectiveEnd - effectiveStart, 0.1) : 0, 0), 1) * 100}%`,
                              background: clip.accent_color ?? "#8b5cf6",
                            }}
                          />
                        </div>
                      )}
                      <OverlayLayer
                        overlays={clip.overlays ?? []}
                        time={time}
                        onChange={(next) => update({ overlays: next })}
                      />
                      {clip.watermark && (
                        <span
                          className="pointer-events-none absolute right-3 z-20 rounded-full border border-white/15 bg-black/45 font-semibold tracking-wide text-white/95 shadow-[0_4px_16px_rgba(0,0,0,0.45)] backdrop-blur-md"
                          style={{
                            bottom: clip.progress_bar ? "18px" : "12px",
                            fontSize: `${Math.round(11 * ((clip.watermark_size ?? 100) / 100))}px`,
                            padding: `${Math.max(2, Math.round(3 * ((clip.watermark_size ?? 100) / 100)))}px ${Math.max(7, Math.round(9 * ((clip.watermark_size ?? 100) / 100)))}px`,
                            textShadow: "0 1px 3px rgba(0,0,0,0.6)",
                          }}
                        >
                          {clip.watermark}
                        </span>
                      )}
                      {time < effectiveStart || time >= effectiveEnd ? (
                        <button
                          onClick={() => seekTo(effectiveStart)}
                          className="absolute inset-0 z-30 grid place-items-center bg-black/30"
                          aria-label="Play clip"
                        >
                          <span className="grid h-14 w-14 place-items-center rounded-full bg-black/60 backdrop-blur">
                            <Play size={22} className="ml-0.5 text-white" />
                          </span>
                        </button>
                      ) : null}
                    </FramePreview>
                  </>
                )}
                <span className="pointer-events-none absolute left-2.5 top-2.5 z-30 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white/80 backdrop-blur">
                  {clip.aspect} ·{" "}
                  {clip.crop_mode === "pad"
                    ? "full frame"
                    : clip.crop_mode === "inset"
                      ? "background + inset"
                      : clip.crop_mode === "dual"
                      ? "dual frame"
                      : clip.crop_mode === "manual"
                        ? "manual frame"
                        : clip.crop_mode === "center"
                          ? "centred"
                          : "auto-track"}
                  {clip.crop_zoom && clip.crop_zoom > 1.01 ? ` · ${clip.crop_zoom.toFixed(1)}×` : ""}
                </span>
                <FaceHint visible={clip.crop_mode === "face-track" && !!autoFocus} />
                {showRendered && (
                  <span className="absolute right-2.5 top-2.5 rounded-md bg-emerald-500/85 px-1.5 py-0.5 text-[10px] font-medium text-white">
                    rendered
                  </span>
                )}
              </div>

              <div className="mt-4 flex w-full max-w-[440px] flex-wrap items-center gap-2.5">
                <button className="btn-ghost btn-sm" onClick={togglePlay}>
                  {playing ? <Pause size={13} /> : <Play size={13} />}
                  {playing ? "Pause" : "Play"}
                </button>
                <span className="font-mono text-[11px] tabular-nums text-slate-400">
                  {fmtTime(Math.max(time, 0), true)} / {fmtTime(clipDuration, true)}
                </span>
                <div className="ml-auto flex gap-1.5">
                  <button
                    className={`btn-ghost btn-sm ${inspectorTab === "frame" ? "text-violet-300" : ""}`}
                    onClick={() => setInspectorTab("frame")}
                    title="Edit the frame"
                  >
                    <Crop size={13} /> Frame
                  </button>
                  <button className="btn-ghost btn-sm" onClick={() => void undo()} title="Undo (Ctrl+Z)">
                    <Undo2 size={13} />
                  </button>
                  <button className="btn-ghost btn-sm" onClick={() => void redo()} title="Redo (Ctrl+Shift+Z)">
                    <Redo2 size={13} />
                  </button>
                  <button
                    className="btn-ghost btn-sm"
                    onClick={() => {
                      setShowRendered(false);
                      seekTo(effectiveStart);
                    }}
                    title="Live preview"
                  >
                    <RotateCcw size={13} />
                  </button>
                </div>
              </div>
              <p className="mt-2 text-[10.5px] text-slate-400">
                Space to play · ←/→ to step · captions follow the real word timings
              </p>
            </div>
          </div>

          <Timeline
            clip={clip}
            captions={captions}
            time={time}
            effectiveStart={effectiveStart}
            effectiveEnd={effectiveEnd}
            onSeek={(t) => seekTo(t)}
            onTrim={(patch) => update(patch)}
              onExtend={extendClip}
          />
        </div>

        <div className="min-w-0 space-y-4">
          <div className="card p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  {clip.category_label}
                </p>
                <h2 className="mt-1 line-clamp-2 text-[15px] font-semibold leading-snug text-white">
                  {clip.selected_title || "Untitled clip"}
                </h2>
              </div>
              <ScoreBadge score={clip.score} />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <span className="chip">{fmtTime(clip.start)}–{fmtTime(clip.end)}</span>
              <span className="chip">{clip.duration.toFixed(1)}s</span>
              <span className="chip">{clip.word_count} words</span>
            </div>
            <button className="btn-primary mt-4 w-full" onClick={() => void exportClip()} disabled={rendering}>
              {rendering ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
              {rendering ? "Rendering clip…" : "Render & export MP4"}
            </button>
            {renderResult && (
              <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
                <span className="flex items-center gap-1.5 text-emerald-300/80">
                  <Check size={11} /> {(renderResult.size / 1048576).toFixed(1)} MB MP4 ready
                </span>
                <span className="flex gap-2">
                  <button
                    className="underline hover:text-white"
                    onClick={() => setShowRendered((v) => !v)}
                  >
                    {showRendered ? "preview source" : "watch"}
                  </button>
                  <a className="underline hover:text-white" href={`/api/clips/${clip.id}/download`}>
                    download
                  </a>
                </span>
              </div>
            )}
            <p className="mt-3 flex items-start gap-1.5 text-[10.5px] leading-relaxed text-slate-400">
              <Sparkles size={11} className="mt-0.5 shrink-0 text-violet-400" />
              Rendering applies your crop, captions, overlays, trims, denoise and music in one pass.
            </p>
          </div>

          <Inspector
            clip={clip}
            captions={captions}
            onSaveCaptions={saveCaptions}
            update={update}
            seekTo={(t) => seekTo(t)}
            time={time}
            autoFocus={autoFocus}
            trackPath={trackPath}
            duration={clipDuration}
            tab={inspectorTab}
            onTabChange={setInspectorTab}
          />
        </div>
      </div>
    </div>
  );
}
