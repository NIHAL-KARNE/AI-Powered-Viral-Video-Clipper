import { useEffect, useState } from "react";
import { Settings2, Cpu, Sparkles, Save, Loader2, KeyRound, Info } from "lucide-react";
import { api } from "../lib/api";
import type { Options, Settings } from "../lib/types";
import { ErrorNote, PageHead } from "../components/ui";
import { AspectPicker } from "../components/AspectPicker";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [options, setOptions] = useState<Options | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.settings(), api.options()])
      .then(([s, o]) => {
        setSettings(s);
        setOptions(o);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load settings"));
  }, []);

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setError("");
    try {
      const next = await api.saveSettings(settings);
      setSettings(next);
      setSaved(true);
      setTimeout(() => setSaved(false), 2400);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return error ? <ErrorNote message={error} /> : <div className="skeleton h-64" />;
  }

  return (
    <div className="space-y-6">
      <PageHead
        eyebrow="Preferences"
        title="Settings"
        subtitle="Tune the local AI engine and optional cloud language model."
        action={
          <button className="btn-primary" onClick={() => void save()} disabled={saving}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            {saved ? "Saved" : "Save changes"}
          </button>
        }
      />
      {error && <ErrorNote message={error} onClose={() => setError("")} />}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card p-5 sm:p-6">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Cpu size={16} className="text-violet-300" /> Local speech recognition
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
            Whisper runs on this machine. Larger models are more accurate but slower. Models are
            downloaded once on first use.
          </p>
          <div className="mt-5">
            <label className="label">Whisper model</label>
            <select
              className="input"
              value={settings.whisper_model}
              onChange={(e) => setSettings({ ...settings, whisper_model: e.target.value })}
            >
              {(options?.whisper_models ?? ["base.en"]).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <p className="mt-2 text-[11px] text-slate-400">
              base.en is a good balance for 1-hour podcasts. tiny.en is fastest; small.en is more accurate.
            </p>
          </div>

          <div className="mt-5">
            <label className="label">Maximum clips per video · {settings.max_clips}</label>
            <input
              type="range"
              min={3}
              max={20}
              value={settings.max_clips}
              onChange={(e) => setSettings({ ...settings, max_clips: Number(e.target.value) })}
              className="w-full accent-violet-500"
            />
          </div>

          <div className="mt-5">
            <label className="label flex items-center justify-between">
              <span>Default output formats</span>
              <span className="font-normal normal-case tracking-normal text-slate-400">
                {settings.default_aspects?.length > 1
                  ? `${settings.default_aspects.length} per moment`
                  : "one per moment"}
              </span>
            </label>
            <AspectPicker
              value={settings.default_aspects?.length ? settings.default_aspects : [settings.default_aspect]}
              onChange={(next) =>
                setSettings({ ...settings, default_aspects: next, default_aspect: next[0] })
              }
            />
            <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
              New analyses produce one clip per moment for each selected format. You can still change
              this per video before analyzing.
            </p>
          </div>
        </section>

        <section className="card p-5 sm:p-6">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Sparkles size={16} className="text-teal-300" /> Optional LLM refinement
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
            By default all scoring and titles are generated locally. You can optionally send clip
            transcripts to an OpenAI-compatible API to rewrite titles and re-estimate scores.
          </p>

          <label className="mt-5 flex cursor-pointer items-center justify-between rounded-xl glass-inset px-4 py-3">
            <span className="text-sm text-slate-200">Enable LLM refinement</span>
            <input
              type="checkbox"
              checked={settings.llm_enabled}
              onChange={(e) => setSettings({ ...settings, llm_enabled: e.target.checked })}
              className="h-4 w-4 accent-violet-500"
            />
          </label>

          <div className={`mt-4 space-y-4 transition ${settings.llm_enabled ? "" : "pointer-events-none opacity-45"}`}>
            <div>
              <label className="label">API base URL</label>
              <input
                className="input"
                value={settings.llm_base_url}
                onChange={(e) => setSettings({ ...settings, llm_base_url: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Model</label>
              <input
                className="input"
                value={settings.llm_model}
                onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })}
              />
            </div>
            <div className="rounded-xl border border-amber-400/20 bg-amber-400/[0.05] p-3.5">
              <p className="flex items-center gap-1.5 text-[11.5px] font-medium text-amber-200">
                <KeyRound size={12} /> API key required
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                Set <code className="rounded bg-black/40 px-1 text-slate-300">LLM_API_KEY</code> in the
                backend environment (or <code className="rounded bg-black/40 px-1 text-slate-300">OPENAI_API_KEY</code>).
                Keys are never stored in project files or sent to the browser.
              </p>
              <p className="mt-1.5 text-[11px] text-slate-400">
                Status: {settings.llm_api_key_set
                  ? <span className="text-emerald-300">key detected in environment</span>
                  : <span className="text-rose-300">no key detected — LLM calls will be skipped</span>}
              </p>
            </div>
          </div>
        </section>
      </div>

      <section className="card flex items-start gap-3 p-4">
        <Info size={16} className="mt-0.5 shrink-0 text-slate-400" />
        <div className="text-[12px] leading-relaxed text-slate-400">
          <p className="font-medium text-slate-300">What runs where</p>
          <ul className="mt-1.5 space-y-1">
            <li>· Transcription, signal analysis, scoring, captions, cropping and rendering: fully local.</li>
            <li>· URL import uses yt-dlp and is subject to each platform&apos;s terms and copyright rules.</li>
            <li>· LLM refinement is the only optional external call, disabled by default.</li>
            <li>· Files are held in local storage under the project&apos;s data folder; add a cloud bucket later if needed.</li>
          </ul>
        </div>
      </section>
      <div className="flex items-center gap-2 text-[11px] text-slate-400">
        <Settings2 size={12} /> Settings are stored server-side in the project data folder.
      </div>
    </div>
  );
}
