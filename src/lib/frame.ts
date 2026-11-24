/**
 * Crop geometry shared by the editor preview and the frame panel.
 *
 * The renderer works in whole pixels; the preview works in fractions of the
 * source frame. Both use the same rule: take the largest rectangle of the
 * target aspect that fits inside the source, divide by zoom, then centre it on
 * the focus point and clamp it inside the frame.
 */
export type Rect = { left: number; top: number; w: number; h: number };

export function cropFractions(
  sourceWidth: number,
  sourceHeight: number,
  panelAspect: number,
  cx: number,
  cy: number,
  zoom = 1,
): Rect {
  const sw = Math.max(sourceWidth, 1);
  const sh = Math.max(sourceHeight, 1);
  const z = Math.max(zoom || 1, 1);
  let w: number;
  let h: number;
  if (sw / sh > panelAspect) {
    h = 1;
    w = sh * panelAspect / sw;
  } else {
    w = 1;
    h = sw / panelAspect / sh;
  }
  w = Math.min(w / z, 1);
  h = Math.min(h / z, 1);
  const fx = Math.min(Math.max(cx ?? 0.5, 0), 1);
  const fy = Math.min(Math.max(cy ?? 0.45, 0), 1);
  const left = Math.min(Math.max(fx - w / 2, 0), 1 - w);
  const top = Math.min(Math.max(fy - h / 2, 0), 1 - h);
  return { left, top, w, h };
}

/** Style that pins a full-bleed video so only the crop rect is visible. */
export function cropStyle(rect: Rect): React.CSSProperties {
  return {
    position: "absolute",
    width: `${100 / rect.w}%`,
    height: `${100 / rect.h}%`,
    left: `${-(rect.left / rect.w) * 100}%`,
    top: `${-(rect.top / rect.h) * 100}%`,
    maxWidth: "none",
    objectFit: "fill",
  };
}

export function aspectValue(aspect: string): number {
  const [a, b] = aspect.split(":").map(Number);
  if (!a || !b) return 9 / 16;
  return a / b;
}

export const ASPECT_DIMS: Record<string, [number, number]> = {
  "9:16": [1080, 1920],
  "1:1": [1080, 1080],
  "4:5": [1080, 1350],
  "16:9": [1920, 1080],
};

/** Linear interpolation of a camera path (times, xs, ys) at time `t`. */
export function samplePath(
  times: number[],
  xs: number[],
  ys: number[],
  t: number,
): { x: number; y: number } | null {
  if (!times.length || times.length !== xs.length || times.length !== ys.length) return null;
  if (times.length === 1) return { x: xs[0], y: ys[0] };
  if (t <= times[0]) return { x: xs[0], y: ys[0] };
  if (t >= times[times.length - 1]) return { x: xs[xs.length - 1], y: ys[ys.length - 1] };
  for (let i = 0; i < times.length - 1; i += 1) {
    const t0 = times[i];
    const t1 = times[i + 1];
    if (t >= t0 && t <= t1) {
      const span = Math.max(t1 - t0, 0.001);
      const k = (t - t0) / span;
      return { x: xs[i] + (xs[i + 1] - xs[i]) * k, y: ys[i] + (ys[i + 1] - ys[i]) * k };
    }
  }
  return { x: xs[xs.length - 1], y: ys[ys.length - 1] };
}

/** Camera position and zoom for a keyframe list at time `t`. */
export function sampleKeyframes(
  keyframes: { t: number; x: number; y: number; zoom: number }[],
  t: number,
): { x: number; y: number; zoom: number } | null {
  const marks = [...(keyframes || [])].sort((a, b) => a.t - b.t);
  if (!marks.length) return null;
  if (marks.length === 1 || t <= marks[0].t) {
    return { x: marks[0].x, y: marks[0].y, zoom: Math.max(marks[0].zoom ?? 1, 1) };
  }
  const last = marks[marks.length - 1];
  if (t >= last.t) return { x: last.x, y: last.y, zoom: Math.max(last.zoom ?? 1, 1) };
  for (let i = 0; i < marks.length - 1; i += 1) {
    const a = marks[i];
    const b = marks[i + 1];
    if (t >= a.t && t <= b.t) {
      const span = Math.max(b.t - a.t, 0.001);
      const k = (t - a.t) / span;
      return {
        x: a.x + (b.x - a.x) * k,
        y: a.y + (b.y - a.y) * k,
        zoom: Math.max((a.zoom ?? 1) + ((b.zoom ?? 1) - (a.zoom ?? 1)) * k, 1),
      };
    }
  }
  return { x: last.x, y: last.y, zoom: Math.max(last.zoom ?? 1, 1) };
}
