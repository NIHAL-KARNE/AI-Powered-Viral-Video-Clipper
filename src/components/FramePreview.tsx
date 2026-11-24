import { useCallback, useEffect, useRef, useState } from "react";
import { Move, ScanFace } from "lucide-react";
import type { Clip } from "../lib/types";
import { aspectValue, cropFractions, cropStyle, sampleKeyframes, samplePath } from "../lib/frame";

export type FrameMode = "manual" | "face-track" | "center" | "pad" | "dual" | "inset";
export type Focus = { x: number; y: number };
/** Camera path sampled from face tracking: clip-relative times plus centres. */
export type TrackPath = { times: number[]; x: number[]; y: number[] } | null;

type VideoHandlers = {
  onTimeUpdate?: () => void;
  onPlay?: () => void;
  onPause?: () => void;
  onLoadedMetadata?: () => void;
};

/**
 * The preview shows exactly what the renderer will cut.
 *
 * A single crop is an inner video blown up so only the crop rectangle is
 * visible. Dual mode stacks a top and bottom panel, each cropping its own
 * subject. In manual and dual mode you can drag each panel directly on the
 * video to reposition the frame.
 */
export function FramePreview({
  clip,
  sourceWidth,
  sourceHeight,
  videoRef,
  autoFocus,
  trackPath,
  time,
  onFocusChange,
  onDualChange,
  onInsetChange,
  children,
  handlers,
  bottomRef,
}: {
  clip: Clip;
  sourceWidth: number;
  sourceHeight: number;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  autoFocus: Focus | null;
  trackPath?: TrackPath;
  /** Live preview time, in seconds inside the clip. */
  time: number;
  onFocusChange: (f: Partial<Focus>) => void;
  onDualChange: (which: "top" | "bottom", f: Partial<Focus & { zoom: number }>) => void;
  /** Background + inset: `part` says which frame is being moved. */
  onInsetChange?: (
    part: "inset" | "bg" | "pos" | "size",
    f: Partial<Focus & { zoom: number; size: number }>,
  ) => void;
  children?: React.ReactNode;
  handlers?: VideoHandlers;
  bottomRef?: React.RefObject<HTMLVideoElement | null>;
}) {
  const mode = (clip.crop_mode || "manual") as FrameMode;
  const aspect = aspectValue(clip.aspect || "9:16");
  // Backdrop copy of the video for full-frame mode's blurred bands.
  const bgRef = useRef<HTMLVideoElement>(null);

  if (mode === "pad") {
    // Full frame keeps the whole shot and letterboxes it. The Fill slider scales
    // that picture up and trims the overflow, which is exactly what the export
    // does: the video is drawn at `fill` times the frame size, centred, and the
    // container clips whatever spills outside. Using object-fit here would crop
    // differently, so the size is expressed as a percentage of the frame.
    const fill = Math.min(Math.max(clip.crop_zoom ?? 1, 1), 4);
    const offset = (1 - fill) * 50;
    return (
      <div className="absolute inset-0 overflow-hidden bg-black">
        {/* The export fills the empty bands with a blurred, darkened copy of the
            shot rather than pure black. Same two-video setup as dual mode, kept
            in sync by DualSync, so the preview matches what renders. */}
        <DualSync master={videoRef} slave={bgRef} />
        <video
          ref={bgRef}
          src={`/api/projects/${clip.project_id}/video`}
          preload="auto"
          muted
          playsInline
          aria-hidden
          className="absolute inset-0 h-full w-full object-cover"
          style={{ filter: "blur(28px) brightness(0.62)", transform: "scale(1.12)" }}
        />
        <video
          ref={videoRef}
          src={`/api/projects/${clip.project_id}/video`}
          preload="auto"
          playsInline
          {...handlers}
          className="absolute"
          style={{
            left: `${offset}%`,
            top: `${offset}%`,
            width: `${fill * 100}%`,
            height: `${fill * 100}%`,
            maxWidth: "none",
            objectFit: "contain",
          }}
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center">
          <span className="rounded-full bg-black/60 px-2 py-1 text-[10px] text-white/70 backdrop-blur">
            full frame{fill > 1.01 ? ` · ${fill.toFixed(2)}× fill` : " · no cropping"}
          </span>
        </div>
        {children}
      </div>
    );
  }

  if (mode === "dual") {
    const panelAspect = aspect * 2;
    return (
      <div className="absolute inset-0 flex flex-col bg-black">
        <DualSync master={videoRef} slave={bottomRef} />
        <DualPanel
          clip={clip}
          which="top"
          panelAspect={panelAspect}
          sourceWidth={sourceWidth}
          sourceHeight={sourceHeight}
          onChange={onDualChange}
          videoRef={videoRef}
          handlers={handlers}
        />
        <div className="relative z-30 h-0">
          <div className="absolute inset-x-0 -top-px h-[3px] bg-violet-400/70" />
          <div className="absolute inset-x-0 -top-5 flex justify-center">
            <span className="rounded-full bg-black/70 px-2 py-0.5 text-[9.5px] font-medium text-violet-100 backdrop-blur">
              drag each half to frame your subjects
            </span>
          </div>
        </div>
        <DualPanel
          clip={clip}
          which="bottom"
          panelAspect={panelAspect}
          sourceWidth={sourceWidth}
          sourceHeight={sourceHeight}
          onChange={onDualChange}
          muted
          videoRef={bottomRef}
        />
        {children}
      </div>
    );
  }

  if (mode === "inset") {
    return (
      <div className="absolute inset-0 overflow-hidden bg-black">
        <InsetLayer
          clip={clip}
          aspect={aspect}
          sourceWidth={sourceWidth}
          sourceHeight={sourceHeight}
          videoRef={videoRef}
          handlers={handlers}
          onChange={onInsetChange}
        />
        {children}
      </div>
    );
  }

  let zoom = Math.max(clip.crop_zoom ?? 1, 1);
  let cx = clip.crop_x ?? 0.5;
  let cy = clip.crop_y ?? 0.45;
  const keyframes = clip.keyframes ?? [];
  const tracked = mode === "face-track" && clip.track_motion !== false;

  if (keyframes.length >= 2 && mode !== "center") {
    // Hand-placed keyframes win: sample them at the playhead.
    const kf = sampleKeyframes(keyframes, time);
    if (kf) {
      cx = kf.x;
      cy = kf.y;
      zoom = Math.max(kf.zoom, 1);
    }
  } else if (mode === "center") {
    cx = 0.5;
    cy = 0.5;
  } else if (tracked) {
    const sample = trackPath
      ? samplePath(trackPath.times, trackPath.x, trackPath.y, time)
      : null;
    const point = sample ?? autoFocus;
    if (point) {
      cx = point.x;
      cy = point.y;
    }
  }
  const rect = cropFractions(sourceWidth, sourceHeight, aspect, cx, cy, zoom);

  // The export applies a slow centred push-in (`zoompan`, +0.0006 per frame up
  // to 1.10). It used to appear only after rendering, so clips looked like they
  // suddenly started zooming. Mirror the same curve here.
  const pushIn = clip.zoom
    ? Math.min(1 + 0.0006 * 30 * Math.max(time, 0), 1.1)
    : 1;
  const style = cropStyle(rect);
  if (pushIn > 1.001) {
    // Zoom about the crop centre so the subject stays put, as in the export.
    style.transformOrigin = `${(rect.left + rect.w / 2) * 100}% ${(rect.top + rect.h / 2) * 100}%`;
    style.transform = `scale(${pushIn.toFixed(4)})`;
  }

  // Keyframes are edited by dragging, so allow it even in auto-follow mode.
  const draggable = mode === "manual" || (keyframes.length >= 2 && mode !== "center");

  return (
    <div className="absolute inset-0 overflow-hidden bg-black">
      <video
        ref={videoRef}
        src={`/api/projects/${clip.project_id}/video`}
        preload="auto"
        playsInline
        {...handlers}
        style={style}
      />
      <DragSurface
        rect={rect}
        enabled={draggable}
        canDrag={mode === "face-track"}
        tracking={tracked}
        mode={mode}
        onMove={onFocusChange}
      />
      {children}
    </div>
  );
}

/** Shape "16:9" -> 1.777. */
function shapeValue(shape?: string): number {
  const [a, b] = (shape || "16:9").split(":").map(Number);
  return a && b ? a / b : 16 / 9;
}

/**
 * Background + inset ("facecam over gameplay").
 *
 * The whole frame is the background, cropped like a normal cover crop (or shown
 * blurred and complete). A second, independent rectangle of the same source is
 * cropped into a window you can drag, resize and place anywhere — that window
 * is what the renderer composites on top. Both regions are separate crops of
 * one video, so the preview needs a second video element kept in sync.
 */
function InsetLayer({
  clip,
  aspect,
  sourceWidth,
  sourceHeight,
  videoRef,
  handlers,
  onChange,
}: {
  clip: Clip;
  aspect: number;
  sourceWidth: number;
  sourceHeight: number;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  handlers?: VideoHandlers;
  onChange?: (
    part: "inset" | "bg" | "pos" | "size",
    f: Partial<Focus & { zoom: number; size: number }>,
  ) => void;
}) {
  const insetRef = useRef<HTMLVideoElement | null>(null);
  const blurRef = useRef<HTMLVideoElement | null>(null);
  // Border width is specified in pixels at 1080 wide, so it has to be scaled by
  // the real rendered width. Container units round to whole pixels and made
  // every thickness look identical.
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [frameW, setFrameW] = useState(0);
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setFrameW(entry.contentRect.width));
    ro.observe(el);
    setFrameW(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);

  const bgFit = clip.inset_bg_fit ?? "cover";
  const bgX = clip.inset_bg_x ?? 0.5;
  const bgY = clip.inset_bg_y ?? 0.5;
  const bgZoom = Math.max(clip.inset_bg_zoom ?? 1, 1);

  const shapeAspect = shapeValue(clip.inset_shape);
  const size = Math.min(Math.max(clip.inset_size ?? 0.3, 0.12), 0.7);
  let wFrac = size;
  let hFrac = (size * aspect) / shapeAspect;
  if (hFrac > 0.9) {
    hFrac = 0.9;
    wFrac = (hFrac * shapeAspect) / aspect;
  }
  const posX = Math.min(Math.max(clip.inset_pos_x ?? 0.78, 0), 1);
  const posY = Math.min(Math.max(clip.inset_pos_y ?? 0.8, 0), 1);
  const left = Math.min(Math.max(posX - wFrac / 2, 0), 1 - wFrac);
  const top = Math.min(Math.max(posY - hFrac / 2, 0), 1 - hFrac);

  // Corner curve, expressed the way CSS measures it: horizontal percentages of
  // the width, vertical percentages of the height. The export uses "percent of
  // the shorter side", so convert here rather than approximating.
  // Work in "fractions of the frame width" so width and height compare directly.
  const radiusPct = Math.min(Math.max(clip.inset_radius ?? 4, 0), 50);
  const boxW = wFrac;
  const boxH = hFrac / aspect;
  const radiusUnits = (radiusPct / 100) * Math.min(boxW, boxH);
  const radiusX = (radiusUnits / boxW) * 100;
  const radiusY = (radiusUnits / boxH) * 100;

  const insetRect = cropFractions(
    sourceWidth,
    sourceHeight,
    shapeAspect,
    clip.inset_x ?? 0.5,
    clip.inset_y ?? 0.5,
    Math.max(clip.inset_zoom ?? 1, 1),
  );
  const bgRect = cropFractions(sourceWidth, sourceHeight, aspect, bgX, bgY, bgZoom);

  // Keep the extra video elements on the master's clock.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const m = videoRef.current;
      for (const ref of [insetRef, blurRef]) {
        const v = ref.current;
        if (!m || !v) continue;
        if (m.paused && !v.paused) v.pause();
        if (!m.paused && v.paused) void v.play().catch(() => {});
        if (Math.abs(v.currentTime - m.currentTime) > 0.25) v.currentTime = m.currentTime;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [videoRef]);

  const [busy, setBusy] = useState<"bg" | "inset" | "pos" | "size" | null>(null);
  const origin = useRef<{ x: number; y: number; l: number; t: number; w: number } | null>(null);

  const start = (kind: "bg" | "inset" | "pos" | "size") =>
    (e: React.PointerEvent<HTMLDivElement>) => {
    if (!onChange) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    origin.current = { x: e.clientX, y: e.clientY, l: left, t: top, w: wFrac };
    setBusy(kind);
  };
  const move = (kind: "bg" | "inset" | "pos" | "size") =>
    (e: React.PointerEvent<HTMLDivElement>) => {
    const o = origin.current;
    if (!onChange || !o || busy !== kind) return;
    const box = e.currentTarget.closest("[data-frame]") as HTMLElement | null;
    if (!box) return;
    const r = box.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const dx = (e.clientX - o.x) / r.width;
    const dy = (e.clientY - o.y) / r.height;
    if (kind === "bg") {
      onChange("bg", { x: bgX + dx * bgRect.w, y: bgY + dy * bgRect.h });
    } else if (kind === "inset") {
      onChange("inset", { x: (clip.inset_x ?? 0.5) + dx * insetRect.w, y: (clip.inset_y ?? 0.5) + dy * insetRect.h });
    } else if (kind === "pos") {
      onChange("pos", { x: o.l + dx + wFrac / 2, y: o.t + dy + hFrac / 2 });
    } else {
      // Resize from the corner: the window grows with the drag, keeping shape.
      onChange("size", { size: o.w + dx * 1.6 });
    }
  };
  const end = () => {
    origin.current = null;
    setBusy(null);
  };

  const drag = (kind: "bg" | "inset" | "pos" | "size") => ({
    onPointerDown: start(kind),
    onPointerMove: move(kind),
    onPointerUp: end,
    onPointerCancel: end,
  });

  return (
    <div ref={frameRef} data-frame className="absolute inset-0 overflow-hidden bg-black">
      {bgFit === "blur" ? (
        <>
          {/* Blurred, edge-filling copy behind a complete, contained copy. */}
          <video
            ref={blurRef}
            src={`/api/projects/${clip.project_id}/video`}
            preload="auto"
            muted
            playsInline
            className="absolute inset-0 h-full w-full object-cover"
            style={{ filter: "blur(26px) brightness(0.72)", transform: "scale(1.12)" }}
          />
          <video
            ref={videoRef}
            src={`/api/projects/${clip.project_id}/video`}
            preload="auto"
            playsInline
            {...handlers}
            className="absolute inset-0 h-full w-full object-contain"
          />
        </>
      ) : (
        <video
          ref={videoRef}
          src={`/api/projects/${clip.project_id}/video`}
          preload="auto"
          playsInline
          {...handlers}
          style={cropStyle(bgRect)}
        />
      )}

      {onChange && (
        <div
          {...drag("bg")}
          className="absolute inset-0 z-10 cursor-grab touch-none active:cursor-grabbing"
          aria-label="Drag to move the background"
        />
      )}

      <div
        className="absolute z-20 overflow-hidden"
        style={{
          left: `${left * 100}%`,
          top: `${top * 100}%`,
          width: `${wFrac * 100}%`,
          height: `${hFrac * 100}%`,
          // Mirror the export: the curve is a percentage of the shorter side,
          // and the outline sits inside the window area.
          borderRadius: `${radiusX}% / ${radiusY}%`,
          border:
            clip.inset_border === false
              ? "none"
              : `${Math.max(((clip.inset_border_width ?? 5) / 1080) * (frameW || 400), 1)}px solid ${
                  clip.inset_border_color ?? "#ffffff"
                }`,
          boxShadow:
            clip.inset_shadow === false ? "none" : "0 10px 34px rgba(0,0,0,0.62)",
        }}
      >
        <video
          ref={insetRef}
          src={`/api/projects/${clip.project_id}/video`}
          preload="auto"
          muted
          playsInline
          style={cropStyle(insetRect)}
        />
        {onChange && (
          <>
            <div
              {...drag("inset")}
              className="absolute inset-0 cursor-grab touch-none active:cursor-grabbing"
              aria-label="Drag to reframe the inset"
            />
            <div
              {...drag("pos")}
              className="absolute inset-x-0 top-0 h-5 cursor-move touch-none bg-gradient-to-b from-black/55 to-transparent"
              aria-label="Drag to move the inset window"
            />
            <div
              {...drag("size")}
              className="absolute bottom-0 right-0 h-5 w-5 cursor-nwse-resize touch-none bg-white/85"
              aria-label="Drag to resize the inset"
            />
          </>
        )}
        <span className="pointer-events-none absolute bottom-1 left-1.5 rounded bg-black/55 px-1 py-0.5 text-[8.5px] font-medium text-white/80">
          inset
        </span>
      </div>

      <span className="pointer-events-none absolute left-1/2 top-1.5 -translate-x-1/2 rounded-full bg-black/60 px-2 py-0.5 text-[9.5px] text-white/70 backdrop-blur">
        {bgFit === "blur" ? "blurred backdrop" : "drag background · drag inset to reframe"}
      </span>
    </div>
  );
}

function DragSurface({
  rect,
  enabled,
  canDrag,
  mode,
  tracking = false,
  onMove,
}: {
  rect: { left: number; top: number; w: number; h: number };
  enabled: boolean;
  canDrag: boolean;
  mode: FrameMode;
  tracking?: boolean;
  onMove: (f: Partial<Focus>) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const last = useRef<{ x: number; y: number } | null>(null);

  const down = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!enabled) return;
      e.preventDefault();
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      last.current = { x: e.clientX, y: e.clientY };
      setDragging(true);
    },
    [enabled],
  );

  const move = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!enabled || !last.current) return;
      const box = e.currentTarget.getBoundingClientRect();
      const dx = e.clientX - last.current.x;
      const dy = e.clientY - last.current.y;
      last.current = { x: e.clientX, y: e.clientY };
      if (!box.width || !box.height) return;
      // The visible crop (`rect.w` of the source) fills the whole box, so one
      // source-width equals box.width / rect.w pixels. Dragging a crop-width
      // should move the frame exactly one crop-width.
      const nextX = rect.left + rect.w / 2 + (dx / box.width) * rect.w;
      const nextY = rect.top + rect.h / 2 + (dy / box.height) * rect.h;
      onMove({
        x: Math.min(Math.max(nextX, rect.w / 2), 1 - rect.w / 2),
        y: Math.min(Math.max(nextY, rect.h / 2), 1 - rect.h / 2),
      });
    },
    [enabled, onMove, rect],
  );

  const up = useCallback(() => {
    last.current = null;
    setDragging(false);
  }, []);

  return (
    <div
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      className={`absolute inset-0 z-20 ${enabled ? "cursor-grab touch-none active:cursor-grabbing" : canDrag ? "cursor-pointer" : "pointer-events-none"}`}
    >
      <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_0_2px_rgba(196,181,253,0.45)]" />
      <div className="pointer-events-none absolute inset-0 grid grid-cols-3 grid-rows-3 opacity-20">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="border border-white/40" />
        ))}
      </div>
      {enabled ? (
        <span
          className={`pointer-events-none absolute left-1/2 top-1/2 grid h-8 w-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full text-white shadow-lg transition ${
            dragging ? "scale-110 bg-violet-500" : "bg-violet-500/85"
          }`}
        >
          <Move size={14} />
        </span>
      ) : (
        <span className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-black/65 px-2 py-1 text-[10px] text-white/75 backdrop-blur">
          {mode === "face-track"
            ? tracking
              ? "auto-following subject"
              : "fixed crop"
            : "fixed centre"}
        </span>
      )}
    </div>
  );
}

/** Mirrors play state and corrects drift between the two dual panels. */
function DualSync({
  master,
  slave,
}: {
  master: React.RefObject<HTMLVideoElement | null>;
  slave?: React.RefObject<HTMLVideoElement | null>;
}) {
  useEffect(() => {
    if (!slave) return;
    let raf = 0;
    const tick = () => {
      const m = master.current;
      const s = slave.current;
      if (m && s) {
        if (!m.paused && s.paused) void s.play().catch(() => {});
        if (m.paused && !s.paused) s.pause();
        if (Math.abs(s.currentTime - m.currentTime) > 0.25) s.currentTime = m.currentTime;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [master, slave]);
  return null;
}

const DEFAULTS = {
  top: { x: 0.28, y: 0.45, zoom: 1 },
  bottom: { x: 0.72, y: 0.45, zoom: 1 },
};

function DualPanel({
  clip,
  which,
  panelAspect,
  sourceWidth,
  sourceHeight,
  onChange,
  videoRef,
  handlers,
  muted,
}: {
  clip: Clip;
  which: "top" | "bottom";
  panelAspect: number;
  sourceWidth: number;
  sourceHeight: number;
  onChange: (which: "top" | "bottom", f: Partial<Focus & { zoom: number }>) => void;
  videoRef?: React.RefObject<HTMLVideoElement | null>;
  handlers?: VideoHandlers;
  muted?: boolean;
}) {
  const prefix = which === "top" ? "dual_top" : "dual_bottom";
  const x = (clip[`${prefix}_x` as keyof Clip] as number | undefined) ?? DEFAULTS[which].x;
  const y = (clip[`${prefix}_y` as keyof Clip] as number | undefined) ?? DEFAULTS[which].y;
  const z = Math.max((clip[`${prefix}_zoom` as keyof Clip] as number | undefined) ?? 1, 1);
  const rect = cropFractions(sourceWidth, sourceHeight, panelAspect, x, y, z);
  const [dragging, setDragging] = useState(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  const down = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    last.current = { x: e.clientX, y: e.clientY };
    setDragging(true);
  };
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!last.current) return;
    const box = boxRef.current?.getBoundingClientRect();
    if (!box || !box.width) return;
    const dx = e.clientX - last.current.x;
    const dy = e.clientY - last.current.y;
    last.current = { x: e.clientX, y: e.clientY };
    onChange(which, {
      x: Math.min(Math.max(x + dx / (box.width * rect.w), rect.w / 2), 1 - rect.w / 2),
      y: Math.min(Math.max(y + dy / (box.height * rect.h), rect.h / 2), 1 - rect.h / 2),
    });
  };
  const up = () => {
    last.current = null;
    setDragging(false);
  };

  return (
    <div ref={boxRef} className="relative min-h-0 flex-1 overflow-hidden bg-black">
      <video
        ref={videoRef}
        src={`/api/projects/${clip.project_id}/video`}
        preload="auto"
        playsInline
        muted={muted}
        {...handlers}
        style={cropStyle(rect)}
      />
      <div
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        className="absolute inset-0 z-10 cursor-grab touch-none active:cursor-grabbing"
      >
        <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_0_2px_rgba(196,181,253,0.4)]" />
        <div className="pointer-events-none absolute inset-0 grid grid-cols-3 grid-rows-3 opacity-15">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="border border-white/40" />
          ))}
        </div>
        <span className="pointer-events-none absolute left-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[9.5px] text-violet-100 backdrop-blur">
          {which === "top" ? "Top" : "Bottom"}
        </span>
        <span
          className={`pointer-events-none absolute left-1/2 top-1/2 grid h-7 w-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full text-white shadow-lg transition ${
            dragging ? "scale-110 bg-violet-500" : "bg-violet-500/80"
          }`}
        >
          <Move size={12} />
        </span>
      </div>
    </div>
  );
}

export function FaceHint({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <span className="pointer-events-none absolute right-2.5 top-2.5 z-30 flex items-center gap-1 rounded-md bg-black/65 px-1.5 py-0.5 text-[10px] text-emerald-200 backdrop-blur">
      <ScanFace size={10} /> tracking
    </span>
  );
}
