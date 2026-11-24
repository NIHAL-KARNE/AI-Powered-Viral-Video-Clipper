import { useEffect, useState } from "react";
import { BookMarked, Check, Download, Loader2, Save, Sparkles } from "lucide-react";
import type { BrandKit, Clip } from "../lib/types";
import { api } from "../lib/api";

/** Fields the brand kit owns. Crop, framing and timing stay per clip. */
const KIT_KEYS = [
  "caption_style",
  "caption_position",
  "caption_size",
  "caption_font",
  "accent_color",
  "watermark",
  "watermark_size",
  "music",
  "music_volume",
  "progress_bar",
  "emoji_enabled",
  "keywords_enabled",
  "inset_border_color",
  "inset_border_width",
  "inset_radius",
] as const;

/**
 * Saved channel look.
 *
 * Competitors store logo, caption colours and music once and stamp them onto
 * every clip. This is the same idea: save the current clip's styling as the
 * kit, then apply it to any clip in one click instead of re-setting eight
 * controls each time.
 */
export function BrandKitPanel({
  clip,
  update,
  onApplied,
}: {
  clip: Clip;
  update: (patch: Partial<Clip>) => void;
  /** Lets the editor refresh anything derived from the clip after applying. */
  onApplied?: (count: number) => void;
}) {
  const [kit, setKit] = useState<BrandKit | null>(null);
  const [busy, setBusy] = useState<"save" | "apply" | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .settings()
      .then((s) => {
        if (alive) setKit(s.brand_kit ?? {});
      })
      .catch(() => {
        /* the panel still works with a local copy */
      });
    return () => {
      alive = false;
    };
  }, []);

  const currentLook = (): BrandKit => {
    const out: BrandKit = { name: kit?.name ?? "My channel" };
    for (const key of KIT_KEYS) {
      const value = (clip as unknown as Record<string, unknown>)[key];
      if (value !== undefined && value !== null) {
        (out as Record<string, unknown>)[key] = value;
      }
    }
    return out;
  };

  const save = async () => {
    setBusy("save");
    setNote("");
    try {
      const next = { ...(kit ?? {}), ...currentLook() };
      const saved = await api.saveSettings({ brand_kit: next });
      setKit(saved.brand_kit ?? next);
      setNote("Saved. Apply it to any clip from here.");
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Could not save the brand kit");
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    setBusy("apply");
    setNote("");
    try {
      const res = await api.brandApply({ clip_ids: [clip.id] });
      // Mirror the server patch so the preview updates immediately.
      update(res.patch as Partial<Clip>);
      setNote("Brand kit applied to this clip.");
      onApplied?.(res.applied);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Could not apply the brand kit");
    } finally {
      setBusy(null);
    }
  };

  const saved = kit && Object.keys(kit).length > 0;
  const hasSavedLook = saved && KIT_KEYS.some((k) => kit?.[k] !== undefined);

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3">
      <div className="flex items-center gap-1.5">
        <BookMarked size={12} className="text-violet-300" />
        <span className="text-[12px] font-medium text-white">Brand kit</span>
        {hasSavedLook && (
          <span className="ml-auto rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[9.5px] font-medium text-emerald-300">
            saved
          </span>
        )}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-slate-400">
        Save this clip&apos;s captions, colours, watermark and music once, then apply the same look
        to every clip. Framing and timing stay as they are.
      </p>

      <div className="mt-2.5 flex gap-1.5">
        <button
          className="btn-ghost btn-sm flex-1 justify-center"
          onClick={() => void save()}
          disabled={busy !== null}
        >
          {busy === "save" ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Save size={12} />
          )}
          Save look
        </button>
        <button
          className="btn-primary btn-sm flex-1 justify-center"
          onClick={() => void apply()}
          disabled={busy !== null || !hasSavedLook}
        >
          {busy === "apply" ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Download size={12} />
          )}
          Apply kit
        </button>
      </div>

      {hasSavedLook && (
        <div className="mt-2 flex flex-wrap gap-1">
          {kit?.caption_style && (
            <Chip icon={<Sparkles size={9} />} text={String(kit.caption_style)} />
          )}
          {kit?.accent_color && (
            <Chip
              icon={
                <span
                  className="h-2 w-2 rounded-full ring-1 ring-white/30"
                  style={{ background: String(kit.accent_color) }}
                />
              }
              text={String(kit.accent_color)}
            />
          )}
          {kit?.watermark && <Chip icon={<Check size={9} />} text={String(kit.watermark)} />}
          {kit?.music && kit.music !== "none" && <Chip text={String(kit.music)} />}
        </div>
      )}

      {note && (
        <p className="mt-2 text-[10.5px] text-slate-400" role="status">
          {note}
        </p>
      )}
    </div>
  );
}

function Chip({ icon, text }: { icon?: React.ReactNode; text: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.05] px-1.5 py-0.5 text-[9.5px] text-slate-300">
      {icon}
      {text}
    </span>
  );
}
