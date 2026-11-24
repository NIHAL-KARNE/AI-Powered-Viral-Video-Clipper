import { useCallback, useRef, useState } from "react";
import type { Overlay } from "../lib/types";

/**
 * Text overlays drawn over the preview, draggable with the mouse.
 *
 * Layout mirrors the renderer: overlays in the same band stack downward instead
 * of piling up on the same spot, and a dragged overlay keeps a free x/y that is
 * exported exactly as placed. Font sizes and wrap width use the same rules as
 * `render.py` so the preview and the export agree.
 */

const BANDS: Record<Overlay["position"], number> = { top: 0.06, center: 0.4, bottom: 0.66 };
/** Reference height the stored overlay sizes are authored against. */
const BASE_HEIGHT = 1920;

type Box = { x: number; y: number; w: number; h: number };

/** Preview pixels per stored size unit, from the preview's own height. */
function scaleFor(previewHeight: number) {
  return previewHeight / BASE_HEIGHT;
}

/**
 * Same wrapping rule as the renderer: roughly 0.62em per glyph, 86% of the
 * frame width. Returns the rows so both line breaks and stacking match.
 */
export function wrapOverlay(text: string, sizePx: number, frameWidth: number): string[] {
  const maxChars = Math.max(Math.floor((frameWidth * 0.86) / (sizePx * 0.62)), 8);
  const words = (text || "").split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  if (words.join(" ").length <= maxChars) return [words.join(" ")];
  const rows: string[] = [];
  let current: string[] = [];
  for (const word of words) {
    const trial = [...current, word].join(" ");
    if (current.length && trial.length > maxChars) {
      rows.push(current.join(" "));
      current = [word];
    } else {
      current.push(word);
    }
  }
  if (current.length) rows.push(current.join(" "));
  if (rows.length > 1 && rows[rows.length - 1].length < maxChars * 0.45) {
    const parts = rows[rows.length - 2].split(" ");
    if (parts.length > 1) {
      const moved = parts.pop() as string;
      rows[rows.length - 2] = parts.join(" ");
      rows[rows.length - 1] = `${moved} ${rows[rows.length - 1]}`;
    }
  }
  return rows;
}

/** Top-left corner and size for each overlay, in fractions of the frame. */
export function overlayBoxes(
  overlays: Overlay[],
  frameWidth: number,
  frameHeight: number,
): Box[] {
  const used = { ...BANDS };
  return overlays.map((ov) => {
    const sizePx = Math.max(ov.size * scaleFor(frameHeight), 10);
    const rows = wrapOverlay(ov.text, sizePx, frameWidth);
    const w = Math.min(
      Math.max(...rows.map((r) => r.length), 1) * sizePx * 0.62,
      frameWidth * 0.9,
    ) / Math.max(frameWidth, 1);
    const h = (rows.length * sizePx * 1.22) / Math.max(frameHeight, 1);
    if (ov.x != null && ov.y != null) {
      return {
        x: Math.min(Math.max(ov.x, 0), 1 - w),
        y: Math.min(Math.max(ov.y, 0), 1 - h),
        w,
        h,
      };
    }
    const band = ov.position in BANDS ? ov.position : "top";
    let y = used[band];
    if (y + h > 0.97) y = Math.max(0.02, 0.97 - h);
    used[band] = y + h + 0.02;
    return { x: (1 - w) / 2, y, w, h };
  });
}

export function OverlayLayer({
  overlays,
  time,
  onChange,
}: {
  overlays: Overlay[];
  time: number;
  onChange: (next: Overlay[]) => void;
}) {
  const layerRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ index: number; dx: number; dy: number } | null>(null);

  const visible = overlays
    .map((ov, index) => ({ ov, index }))
    .filter(({ ov }) => ov.text.trim() && time >= ov.start && time <= ov.end);

  const frame = () => {
    const el = layerRef.current;
    const rect = el?.getBoundingClientRect();
    return { width: rect?.width ?? 360, height: rect?.height ?? 640 };
  };

  const boxes = overlayBoxes(overlays, frame().width, frame().height);
  const px = frame().height / BASE_HEIGHT;

  const startDrag = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, index: number, box: Box) => {
      e.preventDefault();
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      setDrag({ index, dx: e.clientX - box.x * frame().width, dy: e.clientY - box.y * frame().height });
    },
    [],
  );

  const moveDrag = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!drag) return;
      const { width, height } = frame();
      if (!width || !height) return;
      const box = boxes[drag.index];
      if (!box) return;
      const nx = Math.min(Math.max((e.clientX - drag.dx) / width, 0), 1 - box.w);
      const ny = Math.min(Math.max((e.clientY - drag.dy) / height, 0), 1 - box.h);
      onChange(
        overlays.map((o, i) =>
          i === drag.index ? { ...o, x: Number(nx.toFixed(4)), y: Number(ny.toFixed(4)) } : o,
        ),
      );
    },
    [drag, boxes, overlays, onChange],
  );

  const endDrag = useCallback(() => setDrag(null), []);

  return (
    <div ref={layerRef} className="pointer-events-none absolute inset-0 z-10" data-overlay-layer>
      {visible.map(({ ov, index }) => {
        const box = boxes[index];
        if (!box) return null;
        const sizePx = Math.max(ov.size * px, 10);
        const isDragging = drag?.index === index;
        return (
          <div
            key={ov.id ?? index}
            role="button"
            tabIndex={0}
            aria-label={`Move overlay ${index + 1}`}
            onPointerDown={(e) => startDrag(e, index, box)}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            className={`pointer-events-auto absolute cursor-grab touch-none select-none text-center font-extrabold leading-tight active:cursor-grabbing ${
              isDragging ? "rounded bg-white/5 ring-1 ring-violet-400/70" : "hover:ring-1 hover:ring-white/25"
            }`}
            style={{
              left: `${box.x * 100}%`,
              top: `${box.y * 100}%`,
              width: `${box.w * 100}%`,
              color: ov.color || "#ffffff",
              fontSize: `${sizePx}px`,
              textShadow: "0 2px 10px rgba(0,0,0,0.9), 0 0 3px rgba(0,0,0,0.7)",
            }}
          >
            {wrapOverlay(ov.text, sizePx, frame().width).map((row, r) => (
              <span key={r} className="block">
                {row}
              </span>
            ))}
          </div>
        );
      })}
    </div>
  );
}
