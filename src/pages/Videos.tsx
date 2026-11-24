import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Film, Plus, Clock, Scissors, ArrowRight, Loader2, Trash2, RefreshCw } from "lucide-react";
import { api, fmtTime, mediaUrl } from "../lib/api";
import type { Project } from "../lib/types";
import { EmptyState, ErrorNote, PageHead, ProgressBar } from "../components/ui";

export default function Videos() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = () =>
    api
      .projects()
      .then(setProjects)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load videos"));

  useEffect(() => {
    void load();
    const t = setInterval(() => {
      void load();
    }, 5000);
    return () => clearInterval(t);
  }, []);

  const remove = async (id: string) => {
    if (!confirm("Delete this video and its clips?")) return;
    setDeleting(id);
    try {
      await api.deleteProject(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHead
        eyebrow="Library"
        title="My videos"
        subtitle="Every source video you've added, with its analysis status and generated clips."
        action={
          <Link to="/new" className="btn-primary">
            <Plus size={15} /> Add video
          </Link>
        }
      />
      {error && <ErrorNote message={error} onClose={() => setError("")} />}

      {!projects ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton h-24" />)}
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<Film size={22} />}
          title="No videos yet"
          body="Upload a long-form video or paste a link. Once analyzed, your clips will be organized here."
          action={
            <Link to="/new" className="btn-primary">
              <Plus size={15} /> Add your first video
            </Link>
          }
        />
      ) : (
        <div className="space-y-3">
          {projects.map((p) => (
            <div key={p.id} className="card card-hover overflow-hidden">
              <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center">
                <Link
                  to={`/project/${p.id}`}
                  className="relative aspect-video w-full shrink-0 overflow-hidden rounded-xl bg-black/50 sm:w-40"
                >
                  {p.thumbnail ? (
                    <img src={mediaUrl(p.thumbnail)} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="grid h-full place-items-center text-slate-700"><Film size={20} /></div>
                  )}
                  <span className="absolute inset-x-1.5 bottom-1.5 rounded bg-black/70 px-1 py-0.5 text-center text-[10px] tabular-nums text-white">
                    {fmtTime(p.meta?.duration ?? 0)}
                  </span>
                </Link>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusChip status={p.status} />
                    <span className="text-[10.5px] text-slate-400">
                      {new Date(p.created_at * 1000).toLocaleString(undefined, {
                        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                      })}
                    </span>
                  </div>
                  <Link to={`/project/${p.id}`} className="mt-1 block truncate text-[15px] font-medium text-white hover:text-violet-200">
                    {p.title}
                  </Link>
                  <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                    <span className="flex items-center gap-1"><Clock size={11} /> {fmtTime(p.meta?.duration ?? 0)}</span>
                    <span className="flex items-center gap-1"><Scissors size={11} /> {p.clips?.length ?? 0} clips</span>
                    <span>{p.meta?.width}×{p.meta?.height}</span>
                    <span className="uppercase">{p.source_type}</span>
                    {p.analysis_seconds && <span>analyzed in {p.analysis_seconds}s</span>}
                  </div>
                  {p.status === "processing" && (
                    <div className="mt-2.5 flex items-center gap-2">
                      <ProgressBar value={p.progress} className="max-w-[260px]" />
                      <span className="truncate text-[11px] text-slate-400">{p.stage_label}</span>
                    </div>
                  )}
                  {p.status === "error" && (
                    <p className="mt-1.5 line-clamp-2 text-[11px] text-rose-300">{p.error}</p>
                  )}
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <Link to={`/project/${p.id}`} className="btn-ghost btn-sm">
                    Open <ArrowRight size={13} />
                  </Link>
                  <button
                    className="btn-ghost btn-sm"
                    title="Delete"
                    onClick={() => void remove(p.id)}
                    disabled={deleting === p.id}
                  >
                    {deleting === p.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {projects && projects.length > 0 && (
        <button className="btn-ghost btn-sm" onClick={() => void load()}>
          <RefreshCw size={13} /> Refresh
        </button>
      )}
    </div>
  );
}

function StatusChip({ status }: { status: Project["status"] }) {
  const map = {
    uploaded: { label: "Awaiting analysis", cls: "border-sky-400/25 bg-sky-500/10 text-sky-200" },
    processing: { label: "Processing", cls: "border-violet-400/25 bg-violet-500/10 text-violet-200" },
    ready: { label: "Ready", cls: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200" },
    error: { label: "Failed", cls: "border-rose-400/25 bg-rose-500/10 text-rose-200" },
  }[status];
  return <span className={`chip ${map.cls}`}>{map.label}</span>;
}
