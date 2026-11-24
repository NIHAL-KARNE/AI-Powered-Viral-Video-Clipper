import { Check } from "lucide-react";

export const ASPECT_META: Record<string, { label: string; hint: string }> = {
  "9:16": { label: "Vertical", hint: "Shorts · Reels · TikTok" },
  "4:5": { label: "Portrait", hint: "Instagram feed" },
  "1:1": { label: "Square", hint: "Feed post" },
  "16:9": { label: "Landscape", hint: "YouTube · X" },
};

const ORDER = ["9:16", "4:5", "1:1", "16:9"];

/** A little proportional frame, so the ratio is readable without words. */
function AspectGlyph({ aspect, active }: { aspect: string; active: boolean }) {
  const [w, h] = aspect.split(":").map(Number);
  // fit inside a 22×22 box
  const scale = 22 / Math.max(w, h);
  return (
    <span
      className={`shrink-0 rounded-[3px] border transition ${
        active
          ? "border-violet-300/80 bg-violet-400/25 shadow-[0_0_10px_rgba(129,102,255,0.55)]"
          : "border-white/25 bg-white/5"
      }`}
      style={{ width: `${w * scale}px`, height: `${h * scale}px` }}
    />
  );
}

/**
 * Multi-select for output ratios. Every chosen ratio becomes its own clip for
 * each detected moment, so they can be edited and exported independently.
 */
export function AspectPicker({
  value,
  onChange,
  available,
  disabled,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  /** Ratios the renderer supports; defaults to the four standard ones. */
  available?: string[];
  disabled?: boolean;
}) {
  const ratios = (available ?? ORDER).filter((a) => ASPECT_META[a]);
  const toggle = (aspect: string) => {
    if (disabled) return;
    if (value.includes(aspect)) {
      // Never leave the selection empty — at least one ratio is required.
      if (value.length === 1) return;
      onChange(value.filter((a) => a !== aspect));
    } else {
      onChange(ORDER.filter((a) => a === aspect || value.includes(a)));
    }
  };

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {ratios.map((aspect) => {
        const active = value.includes(aspect);
        const meta = ASPECT_META[aspect];
        return (
          <button
            key={aspect}
            type="button"
            onClick={() => toggle(aspect)}
            aria-pressed={active}
            disabled={disabled}
            className={`group relative flex flex-col items-start gap-2 rounded-xl border px-3 py-2.5 text-left transition ${
              active
                ? "border-violet-400/55 bg-violet-500/[0.12] shadow-[inset_0_1px_0_rgba(255,255,255,0.14),0_10px_26px_-18px_rgba(129,102,255,0.9)]"
                : "border-white/10 bg-white/[0.035] hover:border-white/20 hover:bg-white/[0.06]"
            } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
          >
            <span className="flex w-full items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <AspectGlyph aspect={aspect} active={active} />
                <span
                  className={`font-mono text-[11.5px] font-semibold tabular-nums ${
                    active ? "text-violet-100" : "text-slate-300"
                  }`}
                >
                  {aspect}
                </span>
              </span>
              <span
                className={`grid h-4 w-4 place-items-center rounded-full border transition ${
                  active
                    ? "border-violet-300 bg-violet-500 text-white"
                    : "border-white/20 text-transparent"
                }`}
              >
                <Check size={10} strokeWidth={3.5} />
              </span>
            </span>
            <span className="min-w-0">
              <span
                className={`block text-[11.5px] font-medium ${active ? "text-white" : "text-slate-300"}`}
              >
                {meta.label}
              </span>
              <span className="block truncate text-[10px] text-slate-400">{meta.hint}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
