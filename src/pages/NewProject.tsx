import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Wand2, Sparkles, Clock, Layers, Cpu } from "lucide-react";
import { api } from "../lib/api";
import type { Options } from "../lib/types";
import { loadPrefs, savePrefs } from "../lib/prefs";
import { ErrorNote, PageHead } from "../components/ui";
import { AspectPicker } from "../components/AspectPicker";
import { IntakePanel } from "../components/IntakePanel";

export default function NewProject() {
  const [options, setOptions] = useState<Options | null>(null);
  const [preset, setPreset] = useState(loadPrefs().preset);
  const [maxClips, setMaxClips] = useState(loadPrefs().maxClips);
  const [aspects, setAspects] = useState<string[]>(loadPrefs().aspects);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    api.options().then(setOptions).catch(() => setOptions(null));
  }, []);

  useEffect(() => {
    savePrefs({ preset, maxClips, aspects });
  }, [preset, maxClips, aspects]);

  return (
    <div className="space-y-6">
      <PageHead
        title="New project"
        subtitle="Bring in a long video, choose how many clips you want, then let the analyzer do the searching."
      />

      {error && <ErrorNote message={error} onClose={() => setError("")} />}

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="card p-5 sm:p-6">
          <h3 className="text-sm font-semibold text-white">1 · Add your video</h3>
          <p className="mb-4 mt-1 text-xs text-slate-400">
            Upload a file or import from a supported link. Nothing leaves this machine.
          </p>
          <IntakePanel compact />
          <div className="mt-5 rounded-xl glass-inset p-4 text-[12px] leading-relaxed text-slate-400">
            <p className="flex items-center gap-2 font-medium text-slate-300">
              <Cpu size={14} className="text-violet-300" /> What happens next
            </p>
            <ol className="mt-2 space-y-1.5 pl-1">
              <li>1. Audio is extracted and transcribed with word-level timing.</li>
              <li>2. Scene, face, motion and audio energy signals are measured.</li>
              <li>3. Sentence-aligned windows are scored for hook, emotion, novelty and coherence.</li>
              <li>4. Overlapping picks are suppressed so clips don&apos;t repeat the same moment.</li>
            </ol>
          </div>
        </div>

        <div className="card h-fit p-5 sm:p-6">
          <h3 className="text-sm font-semibold text-white">2 · Detection settings</h3>
          <p className="mb-4 mt-1 text-xs text-slate-400">Applies to the project you add on the left.</p>

          <label className="label">Clip length target</label>
          <div className="space-y-2">
            {options
              ? Object.entries(options.presets).map(([key, p]) => (
                  <button
                    key={key}
                    onClick={() => setPreset(key)}
                    className={`flex w-full items-center justify-between rounded-xl border px-3.5 py-2.5 text-left text-sm transition ${
                      preset === key
                        ? "border-violet-400/50 bg-violet-500/10 text-white"
                        : "border-white/10 bg-white/[0.045] text-slate-300 hover:border-white/20"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <Clock size={14} className={preset === key ? "text-violet-300" : "text-slate-400"} />
                      {p.label}
                    </span>
                    <span className="text-[11px] text-slate-400">{p.min}–{p.max}s</span>
                  </button>
                ))
              : [0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-11" />)}
          </div>

          <div className="mt-5">
            <label className="label">
              Maximum clips · <span className="text-violet-300">{maxClips}</span>
            </label>
            <input
              type="range"
              min={3}
              max={20}
              value={maxClips}
              onChange={(e) => setMaxClips(Number(e.target.value))}
              className="w-full accent-violet-500"
            />
            <div className="mt-1 flex justify-between text-[10.5px] text-slate-400">
              <span>3 — focused</span>
              <span>20 — exhaustive</span>
            </div>
          </div>

          <div className="mt-5">
            <label className="label flex items-center justify-between">
              <span>Output formats</span>
              <span className="font-normal normal-case tracking-normal text-slate-400">
                {aspects.length > 1 ? `${aspects.length} clips per moment` : "one clip per moment"}
              </span>
            </label>
            <AspectPicker value={aspects} onChange={setAspects} />
          </div>

          <div className="glass-inset mt-5 flex items-start gap-2 p-3 text-[11.5px] leading-relaxed text-slate-400">
            <Layers size={14} className="mt-0.5 shrink-0 text-slate-400" />
            These become the defaults when you open a new video. You can change them again on the
            project page before analyzing.
          </div>

          <button
            className="btn-ghost mt-5 w-full"
            onClick={() => {
              setError("");
              navigate("/videos");
            }}
          >
            <Wand2 size={15} /> Pick an existing video
          </button>
          <p className="mt-3 flex items-start gap-1.5 text-[11px] text-slate-400">
            <Sparkles size={12} className="mt-0.5 shrink-0 text-violet-400" />
            Tip: pick 30–45s for talking-head content, 15–30s for punchy reaction clips.
          </p>
        </div>
      </div>
    </div>
  );
}
