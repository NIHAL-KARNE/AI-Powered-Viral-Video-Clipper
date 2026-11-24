import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Film,
  Scissors,
  Download,
  Gauge,
  TrendingUp,
  ArrowRight,
  Sparkles,
  Loader2,
  CircleAlert,
} from "lucide-react";
import { api, fmtTime, mediaUrl } from "../lib/api";
import type { DashboardData } from "../lib/types";
import { PageHead, EmptyState, ErrorNote, ScoreRing, ProgressBar } from "../components/ui";
import { IntakePanel } from "../components/IntakePanel";

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .dashboard()
        .then((d) => alive && setData(d))
        .catch((e) => alive && setError(e instanceof Error ? e.message : "Could not load dashboard"));
    void load();
    const t = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const stats = data?.stats;
  const processing = data?.projects.filter((p) => p.status === "processing" || p.status === "uploaded") ?? [];

  return (
    <div className="space-y-7">
      <PageHead
        eyebrow="Studio"
        title="Dashboard"
        subtitle="Turn one long video into a batch of short-form clips, ready for Shorts, Reels and TikTok."
        action={
          <Link to="/new" className="btn-ghost">
            <Sparkles size={15} /> New project
          </Link>
        }
      />

      {error && <ErrorNote message={error} onClose={() => setError("")} />}

      <section className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
        <div className="card relative overflow-hidden p-6 sm:p-8">
          {/* Two coloured light pools behind the glass, plus a soft top sheen:
              the panel has visible light to refract instead of sitting flat. */}
          <div className="pointer-events-none absolute -right-20 -top-28 h-72 w-72 rounded-full bg-violet-500/25 blur-[70px]" />
          <div className="pointer-events-none absolute -bottom-32 -left-16 h-64 w-64 rounded-full bg-teal-400/12 blur-[70px]" />
          <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-white/40 to-transparent" />
          <div className="relative">
            <span className="chip border-violet-300/25 bg-violet-400/10 text-violet-100">
              <Sparkles size={11} /> AI clip detection
            </span>
            <h2 className="mt-4 max-w-lg text-balance text-[27px] font-semibold leading-[1.15] tracking-[-0.035em] text-white sm:text-[34px]">
              One hour of footage. A feed full of{" "}
              <span className="shimmer">viral-ready</span> moments.
            </h2>
            <p className="mt-3 max-w-lg text-[13.5px] leading-relaxed text-slate-300/85">
              Upload a podcast, interview or stream. The engine transcribes it, reads the energy,
              finds the strongest hooks, then cuts vertical clips with captions.
            </p>
            <div className="mt-7">
              <IntakePanel compact />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:gap-4">
          <StatCard icon={<Film size={16} />} label="Videos" value={stats ? String(stats.videos) : "—"} tone="violet" />
          <StatCard icon={<Scissors size={16} />} label="Clips found" value={stats ? String(stats.clips) : "—"} tone="teal" />
          <StatCard icon={<Download size={16} />} label="Exports" value={stats ? String(stats.exports) : "—"} tone="sky" />
          <StatCard
            icon={<Gauge size={16} />}
            label="Avg. score"
            value={stats ? stats.avg_score.toFixed(0) : "—"}
            tone="amber"
          />
          <div className="card col-span-2 flex items-center gap-4 p-4">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/[0.05] text-violet-300">
              <TrendingUp size={17} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Footage analyzed</p>
              <p className="text-lg font-semibold tabular-nums text-white">
                {stats ? `${stats.minutes_analyzed.toFixed(0)} min` : "—"}
              </p>
            </div>
            {processing.length > 0 && (
              <span className="chip border-violet-400/25 bg-violet-500/10 text-violet-200">
                <Loader2 size={11} className="animate-spin" /> {processing.length} in progress
              </span>
            )}
          </div>
        </div>
      </section>

      {processing.length > 0 && (
        <section className="card p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">In progress</h3>
            <Link to="/videos" className="text-xs text-violet-300 hover:text-violet-200">
              All videos
            </Link>
          </div>
          <div className="space-y-3">
            {processing.slice(0, 3).map((p) => (
              <Link
                key={p.id}
                to={`/project/${p.id}`}
                className="glass-inset flex items-center gap-3 p-3 transition hover:border-white/15"
              >
                <div className="h-11 w-16 shrink-0 overflow-hidden rounded-lg bg-black/50">
                  {p.thumbnail && <img src={mediaUrl(p.thumbnail)} alt="" className="h-full w-full object-cover" />}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-white">{p.title}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <ProgressBar value={p.progress} className="max-w-[240px]" />
                    <span className="text-[11px] tabular-nums text-slate-400">{Math.round(p.progress * 100)}%</span>
                  </div>
                  <p className="mt-1 truncate text-[11px] text-slate-400">{p.stage_label}</p>
                </div>
                <ArrowRight size={15} className="shrink-0 text-slate-600" />
              </Link>
            ))}
          </div>
        </section>
      )}

      <section>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white">Top scoring clips</h3>
            <p className="text-xs text-slate-400">Ranked by estimated viral potential across all projects</p>
          </div>
          <Link to="/clips" className="btn-ghost btn-sm">
            All clips <ArrowRight size={13} />
          </Link>
        </div>
        {!data ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-64" />
            ))}
          </div>
        ) : data.recent_clips.length === 0 ? (
          <EmptyState
            icon={<Scissors size={22} />}
            title="No clips yet"
            body="Add a video above and run the analyzer. The detected moments will appear here with scores, titles and captions."
            action={
              <Link to="/new" className="btn-primary">
                <Film size={15} /> Start a project
              </Link>
            }
          />
        ) : (
          <div className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.recent_clips.map((c) => (
              <Link
                key={c.id}
                to={`/editor/${c.id}`}
                className="card card-hover group flex gap-3 overflow-hidden p-3"
              >
                <div className="relative aspect-[9/16] w-24 shrink-0 overflow-hidden rounded-lg bg-black/50">
                  {c.thumbnail ? (
                    <img src={mediaUrl(c.thumbnail)} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="grid h-full place-items-center text-slate-700">
                      <Scissors size={16} />
                    </div>
                  )}
                  <span className="absolute inset-x-1 bottom-1 rounded bg-black/70 px-1 py-0.5 text-center text-[9.5px] tabular-nums text-white">
                    {fmtTime(c.start)}–{fmtTime(c.end)}
                  </span>
                </div>
                <div className="flex min-w-0 flex-1 flex-col">
                  <p className="line-clamp-3 text-[13px] font-medium leading-snug text-white">
                    {c.selected_title}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400">{c.category_label}</p>
                  <div className="mt-auto flex items-center justify-between pt-2">
                    <span className="text-[11px] text-slate-400">{c.duration.toFixed(0)}s</span>
                    <ScoreRing score={c.score} size={38} />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="card flex flex-col gap-3 border-amber-400/15 bg-amber-400/[0.035] p-4 sm:flex-row sm:items-center">
        <CircleAlert size={17} className="shrink-0 text-amber-300" />
        <p className="text-[12px] leading-relaxed text-slate-400">
          <span className="font-semibold text-amber-200/90">Honest scoring:</span> viral potential is
          computed from measurable signals — hook language, audio energy, lexical surprise, pacing and
          visual activity. It is an estimate, not a prediction of actual views.
        </p>
      </section>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: "violet" | "teal" | "sky" | "amber";
}) {
  const tones = {
    violet: "text-violet-200 bg-violet-500/18",
    teal: "text-teal-200 bg-teal-500/18",
    sky: "text-sky-200 bg-sky-500/18",
    amber: "text-amber-200 bg-amber-500/18",
  }[tone];
  return (
    <div className="card card-hover group p-4">
      <div
        className={`grid h-9 w-9 place-items-center rounded-[11px] border border-white/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] transition-transform duration-300 group-hover:scale-[1.06] ${tones}`}
      >
        {icon}
      </div>
      <p className="mt-3.5 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-[22px] font-semibold leading-none tabular-nums text-white">{value}</p>
    </div>
  );
}
