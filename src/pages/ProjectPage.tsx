import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Play,
  Trash2,
  Sparkles,
  Clock,
  MonitorPlay,
  HardDrive,
  CheckCircle2,
  Loader2,
  Download,
  SlidersHorizontal,
  ChevronDown,
} from "lucide-react";
import { api, fmtBytes, fmtTime, mediaUrl } from "../lib/api";
import type { Clip, Project } from "../lib/types";
import { loadPrefs, savePrefs } from "../lib/prefs";
import { ClipCard } from "../components/ClipCard";
import { AspectPicker, ASPECT_META } from "../components/AspectPicker";
import { EmptyState, ErrorNote, ProgressBar, ScoreRing } from "../components/ui";

const SORTS = {
  score: "Highest viral potential",
  shortest: "Shortest duration",
  longest: "Longest duration",
  emotion: "Emotional intensity",
  category: "Content category",
} as const;
type SortKey = keyof typeof SORTS;

export default function ProjectPage() {
  const { id = "" } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [preset, setPreset] = useState(loadPrefs().preset);
  const [maxClips, setMaxClips] = useState(loadPrefs().maxClips);
  const [aspects, setAspects] = useState<string[]>(loadPrefs().aspects);
  const [ratioFilter, setRatioFilter] = useState<string>("all");
  const [sort, setSort] = useState<SortKey>("score");
  const [selected, setSelected] = useState<string[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const autoStarted = useRef(false);

  const load = useCallback(async () => {
    try {
      const p = await api.project(id);
      setProject(p);
      setRunning(p.status === "processing");
      return p;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load project");
      return null;
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      void load().then((p) => {
        if (p && p.status !== "processing") setRunning(false);
      });
    }, 1500);
    return () => clearInterval(t);
  }, [running, load]);

  useEffect(() => {
    savePrefs({ preset, maxClips, aspects });
  }, [preset, maxClips, aspects]);

  const start = async () => {
    setError("");
    try {
      await api.analyze(id, preset, maxClips, aspects);
      setRunning(true);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start analysis");
    }
  };

  // Deep link from the intake panel: start analysis immediately, once.
  useEffect(() => {
    if (autoStarted.current) return;
    if (search.get("analyze") !== "1") return;
    if (!project || project.status === "processing" || project.clips.length > 0) return;
    autoStarted.current = true;
    navigate(`/project/${id}`, { replace: true });
    void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, project?.status]);

  const remove = async () => {
    if (!confirm("Delete this project and all of its clips? This cannot be undone.")) return;
    try {
      await api.deleteProject(id);
      navigate("/videos");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const allClips: Clip[] = project?.clips ?? [];
  // Ratios actually present in this project, in a stable display order.
  const presentRatios = useMemo(() => {
    const seen = new Set(allClips.map((c) => c.aspect).filter(Boolean));
    return Object.keys(ASPECT_META).filter((a) => seen.has(a));
  }, [allClips]);

  // When a project holds several ratios, show one at a time so the grid stays
  // readable. Defaults to the first ratio that exists.
  useEffect(() => {
    if (presentRatios.length < 2) {
      setRatioFilter("all");
      return;
    }
    setRatioFilter((cur) =>
      cur !== "all" && presentRatios.includes(cur) ? cur : presentRatios[0],
    );
  }, [presentRatios]);

  const sorted = useMemo(() => {
    const clips = ratioFilter === "all"
      ? [...allClips]
      : allClips.filter((c) => c.aspect === ratioFilter);
    switch (sort) {
      case "shortest":
        return clips.sort((a, b) => a.duration - b.duration);
      case "longest":
        return clips.sort((a, b) => b.duration - a.duration);
      case "emotion":
        return clips.sort((a, b) => (b.components?.emotion ?? 0) - (a.components?.emotion ?? 0));
      case "category":
        return clips.sort((a, b) => a.category_label.localeCompare(b.category_label) || b.score - a.score);
      default:
        return clips.sort((a, b) => b.score - a.score);
    }
  }, [allClips, sort, ratioFilter]);

  // One row per detected moment, so ratio copies don't repeat in the breakdown.
  const moments = useMemo(() => {
    const seen = new Set<number | string>();
    const out: Clip[] = [];
    for (const c of [...allClips].sort((a, b) => b.score - a.score)) {
      const key = c.moment_index ?? c.id;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(c);
    }
    return out;
  }, [allClips]);

  const toggle = (cid: string) =>
    setSelected((s) => (s.includes(cid) ? s.filter((x) => x !== cid) : [...s, cid]));

  const batchExport = async () => {
    if (!selected.length) return;
    setBatchBusy(true);
    setError("");
    try {
      const res = await api.batchExport(selected);
      if (res.errors.length) setError(`Some clips failed: ${res.errors.join("; ")}`);
      await load();
      if (res.rendered.length === 1) {
        window.location.href = `/api/clips/${selected[0]}/download`;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Batch export failed");
    } finally {
      setBatchBusy(false);
    }
  };

  if (!project) {
    return error ? <ErrorNote message={error} /> : <div className="skeleton h-64" />;
  }

  const job = project.job;
  const isProcessing = project.status === "processing" && !job?.error;
  const clips: Clip[] = project.clips;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <Link to="/videos" className="inline-flex items-center gap-1.5 hover:text-slate-300">
          <ArrowLeft size={13} /> My videos
        </Link>
        <span>/</span>
        <span className="truncate text-slate-400">{project.title}</span>
      </div>

      {error && <ErrorNote message={error} onClose={() => setError("")} />}

      <div className="card overflow-hidden">
        <div className="flex flex-col gap-5 p-5 sm:p-6 lg:flex-row">
          <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-xl bg-black/60 lg:w-[320px]">
            {showSource ? (
              <video
                src={`/api/projects/${project.id}/video`}
                controls
                autoPlay
                className="h-full w-full object-contain"
              />
            ) : (
              <>
                {project.thumbnail ? (
                  <img src={mediaUrl(project.thumbnail)} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="grid h-full place-items-center text-slate-700"><Play size={30} /></div>
                )}
                <button
                  onClick={() => setShowSource(true)}
                  className="absolute inset-0 grid place-items-center bg-black/25 transition hover:bg-black/15"
                  aria-label="Play source"
                >
                  <span className="grid h-12 w-12 place-items-center rounded-full bg-white/15 backdrop-blur">
                    <Play size={18} className="ml-0.5 text-white" />
                  </span>
                </button>
              </>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="chip border-violet-400/25 bg-violet-500/10 text-violet-200">
                {project.source_type === "url" ? "Imported link" : "Uploaded file"}
              </span>
              <StatusPill status={project.status} />
              {project.cached_result && <span className="chip">cached analysis</span>}
              {project.transcript_segments ? (
                <span className="chip">{project.transcript_segments} transcript segments</span>
              ) : null}
            </div>
            <h1 className="mt-2.5 text-balance text-xl font-semibold tracking-tight text-white sm:text-2xl">
              {project.title}
            </h1>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <span className="chip"><Clock size={11} /> {fmtTime(project.meta.duration)}</span>
              <span className="chip"><MonitorPlay size={11} /> {project.meta.width}×{project.meta.height}</span>
              <span className="chip"><HardDrive size={11} /> {fmtBytes(project.meta.size)}</span>
              {project.meta.audio_codec ? (
                <span className="chip">{project.meta.audio_codec?.toUpperCase()} audio</span>
              ) : (
                <span className="chip border-rose-400/30 text-rose-300">no audio</span>
              )}
            </div>

            {isProcessing ? (
              <div className="mt-5 rounded-xl border border-violet-400/20 bg-violet-500/[0.06] p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="flex items-center gap-2 text-sm font-medium text-violet-100">
                    <Loader2 size={15} className="animate-spin" />
                    {job?.label || project.stage_label || "Processing"}
                  </p>
                  <span className="text-xs tabular-nums text-violet-200/80">
                    {Math.round((job?.progress ?? project.progress) * 100)}%
                  </span>
                </div>
                <ProgressBar value={job?.progress ?? project.progress} className="mt-3" />
                <p className="mt-2.5 text-[11px] leading-relaxed text-slate-400">
                  Running locally. Long videos can take several minutes — the page updates live and you can
                  leave it open in the background.
                </p>
              </div>
            ) : project.status === "error" ? (
              <div className="mt-5">
                <ErrorNote message={project.error || "Processing failed. Try re-running the analysis."} />
              </div>
            ) : null}

            <div className="mt-5 flex flex-wrap items-center gap-2.5">
              <button className="btn-primary" onClick={() => void start()} disabled={isProcessing || running}>
                {isProcessing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                {clips.length ? "Re-run analysis" : "Analyze video"}
              </button>
              <button className="btn-ghost" onClick={() => setShowSettings((v) => !v)}>
                <SlidersHorizontal size={14} /> Detection settings
              </button>
              {clips.length > 0 && (
                <Link to="/clips" className="btn-ghost">
                  All clips
                </Link>
              )}
              <button className="btn-danger ml-auto" onClick={() => void remove()}>
                <Trash2 size={14} /> Delete
              </button>
            </div>

            {(showSettings || !clips.length) && (
              <div className="glass-inset mt-4 space-y-4 p-4">
              <div>
                <label className="label flex items-center justify-between">
                  <span>Output formats</span>
                  <span className="font-normal normal-case tracking-normal text-slate-400">
                    {aspects.length > 1 ? `${aspects.length} clips per moment` : "one clip per moment"}
                  </span>
                </label>
                <AspectPicker value={aspects} onChange={setAspects} disabled={isProcessing} />
                <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
                  Each selected ratio becomes its own editable clip, so a 6-moment video in two
                  formats gives 12 clips. They share one transcript and one analysis.
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="label">Clip length target</label>
                  <div className="relative">
                    <select
                      className="input appearance-none pr-9"
                      value={preset}
                      onChange={(e) => setPreset(e.target.value)}
                    >
                      <option value="short">15–30 seconds</option>
                      <option value="medium">30–45 seconds</option>
                      <option value="long">45–60 seconds</option>
                      <option value="extended">60–90 seconds</option>
                      <option value="any">Auto mix (15–90s)</option>
                    </select>
                    <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  </div>
                </div>
                <div>
                  <label className="label">Maximum clips · {maxClips}</label>
                  <input
                    type="range"
                    min={3}
                    max={20}
                    value={maxClips}
                    onChange={(e) => setMaxClips(Number(e.target.value))}
                    className="mt-3 w-full accent-violet-500"
                  />
                </div>
              </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {clips.length === 0 && !isProcessing && project.status !== "error" && (
        <EmptyState
          icon={<Sparkles size={22} />}
          title="Ready when you are"
          body="Run the analyzer to transcribe this video and surface its strongest moments. You can adjust clip length and count first."
          action={
            <button className="btn-primary" onClick={() => void start()} disabled={running}>
              <Sparkles size={15} /> Analyze video
            </button>
          }
        />
      )}

      {isProcessing && clips.length === 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton h-72" style={{ animationDelay: `${i * 90}ms` }} />
          ))}
        </div>
      )}

      {clips.length > 0 && (
        <section className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">
                {moments.length} detected moment{moments.length === 1 ? "" : "s"}
                {presentRatios.length > 1 && (
                  <span className="ml-2 text-xs font-normal text-slate-400">
                    · {clips.length} clips in {presentRatios.length} formats
                  </span>
                )}
              </h2>
              <p className="text-xs text-slate-400">
                Sentence-aligned cuts · scored on hook, emotion, novelty, context and pacing
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <select
                  className="input appearance-none py-2 pl-3 pr-9 text-xs"
                  value={sort}
                  onChange={(e) => setSort(e.target.value as SortKey)}
                >
                  {Object.entries(SORTS).map(([k, label]) => (
                    <option key={k} value={k}>Sort: {label}</option>
                  ))}
                </select>
                <ChevronDown size={13} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
              </div>
              {selected.length > 0 && (
                <button className="btn-primary btn-sm" onClick={() => void batchExport()} disabled={batchBusy}>
                  {batchBusy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                  Export {selected.length}
                </button>
              )}
            </div>
          </div>

          {presentRatios.length > 1 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {presentRatios.map((a) => {
                const count = allClips.filter((c) => c.aspect === a).length;
                const active = ratioFilter === a;
                return (
                  <button
                    key={a}
                    onClick={() => setRatioFilter(a)}
                    className={`flex items-center gap-1.5 rounded-[9px] border px-2.5 py-1.5 text-[11.5px] font-medium transition ${
                      active
                        ? "border-violet-400/50 bg-violet-500/[0.14] text-violet-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]"
                        : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-white"
                    }`}
                  >
                    <span className="font-mono tabular-nums">{a}</span>
                    <span className="text-[10px] text-slate-400">{ASPECT_META[a]?.label}</span>
                    <span
                      className={`rounded-full px-1.5 text-[10px] tabular-nums ${
                        active ? "bg-violet-400/25 text-violet-50" : "bg-white/8 text-slate-400"
                      }`}
                    >
                      {count}
                    </span>
                  </button>
                );
              })}
              <button
                onClick={() => setRatioFilter("all")}
                className={`rounded-[9px] border px-2.5 py-1.5 text-[11.5px] font-medium transition ${
                  ratioFilter === "all"
                    ? "border-violet-400/50 bg-violet-500/[0.14] text-violet-100"
                    : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-white"
                }`}
              >
                All formats
              </button>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {sorted.map((clip) => (
              <ClipCard
                key={clip.id}
                clip={clip}
                selected={selected.includes(clip.id)}
                onToggle={toggle}
                onError={setError}
              />
            ))}
          </div>

          {selected.length > 0 && (
            <div className="sticky bottom-4 z-10 mx-auto flex max-w-xl items-center justify-between gap-3 rounded-2xl border border-violet-400/25 bg-ink-800/95 px-4 py-3 shadow-2xl backdrop-blur-xl">
              <p className="text-sm text-slate-300">
                <span className="font-semibold text-white">{selected.length}</span> selected
                <span className="ml-2 text-xs text-slate-400">Batch export renders each clip</span>
              </p>
              <div className="flex gap-2">
                <button className="btn-ghost btn-sm" onClick={() => setSelected([])}>Clear</button>
                <button className="btn-primary btn-sm" onClick={() => void batchExport()} disabled={batchBusy}>
                  {batchBusy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                  Export
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {clips.length > 0 && (
        <section className="card p-5">
          <h3 className="text-sm font-semibold text-white">Score breakdown by moment</h3>
          <p className="mb-4 text-xs text-slate-400">
            Component scores behind each viral estimate. Higher is stronger.
          </p>
          <div className="space-y-2.5">
            {moments.slice(0, 8).map((c) => (
              <div key={c.id} className="flex items-center gap-3">
                <span className="w-7 text-right text-[11px] text-slate-400">{c.score.toFixed(0)}</span>
                <ScoreRing score={c.score} size={30} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-slate-300">{c.selected_title}</p>
                  <div className="mt-1 flex gap-1">
                    {Object.entries(c.components ?? {}).map(([k, v]) => (
                      <span
                        key={k}
                        title={`${k}: ${v}`}
                        className="h-1 flex-1 rounded-full bg-white/8"
                      >
                        <span
                          className="block h-full rounded-full bg-gradient-to-r from-violet-500 to-teal-300"
                          style={{ width: `${v}%` }}
                        />
                      </span>
                    ))}
                  </div>
                </div>
                <span className="w-14 shrink-0 text-right text-[10px] text-slate-400">
                  {c.duration.toFixed(0)}s
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function StatusPill({ status }: { status: Project["status"] }) {
  const map = {
    uploaded: { label: "Uploaded", cls: "border-sky-400/25 bg-sky-500/10 text-sky-200" },
    processing: { label: "Processing", cls: "border-violet-400/25 bg-violet-500/10 text-violet-200" },
    ready: { label: "Analyzed", cls: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200" },
    error: { label: "Error", cls: "border-rose-400/25 bg-rose-500/10 text-rose-200" },
  }[status];
  return (
    <span className={`chip ${map.cls}`}>
      {status === "ready" ? <CheckCircle2 size={11} /> : status === "error" ? null : (
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {map.label}
    </span>
  );
}
