import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Scissors, Download, Loader2, Sparkles, Hash } from "lucide-react";
import { api } from "../lib/api";
import type { Clip, Project } from "../lib/types";
import { ClipCard } from "../components/ClipCard";
import { EmptyState, ErrorNote, PageHead } from "../components/ui";

const SORTS = {
  score: "Highest score",
  shortest: "Shortest first",
  longest: "Longest first",
  newest: "Newest",
} as const;
type SortKey = keyof typeof SORTS;

export default function ClipsLibrary() {
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortKey>("score");
  const [projectFilter, setProjectFilter] = useState("all");
  const [category, setCategory] = useState("all");
  const [ratio, setRatio] = useState("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = () =>
    Promise.all([api.clips(), api.projects()])
      .then(([c, p]) => {
        setClips(c);
        setProjects(p);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load clips"));

  useEffect(() => {
    void load();
  }, []);

  const categories = useMemo(
    () => Array.from(new Set((clips ?? []).map((c) => c.category_label))).sort(),
    [clips],
  );

  const visible = useMemo(() => {
    let list = [...(clips ?? [])];
    if (projectFilter !== "all") list = list.filter((c) => c.project_id === projectFilter);
    if (category !== "all") list = list.filter((c) => c.category_label === category);
    if (ratio !== "all") list = list.filter((c) => c.aspect === ratio);
    switch (sort) {
      case "shortest":
        return list.sort((a, b) => a.duration - b.duration);
      case "longest":
        return list.sort((a, b) => b.duration - a.duration);
      case "newest":
        return list.sort((a, b) => (b as unknown as { created_at: number }).created_at - (a as unknown as { created_at: number }).created_at);
      default:
        return list.sort((a, b) => b.score - a.score);
    }
  }, [clips, projectFilter, category, ratio, sort]);

  const ratios = useMemo(
    () => Array.from(new Set((clips ?? []).map((c) => c.aspect).filter(Boolean))),
    [clips],
  );

  const toggle = (cid: string) =>
    setSelected((s) => (s.includes(cid) ? s.filter((x) => x !== cid) : [...s, cid]));

  const exportAll = async (ids: string[]) => {
    setBusy(true);
    setError("");
    try {
      const res = await api.batchExport(ids);
      if (res.errors.length) setError(res.errors.join("; "));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHead
        eyebrow="Clips"
        title="Generated clips"
        subtitle="Every detected moment across your videos. Sort, filter, select a batch, and export."
        action={
          <div className="flex gap-2">
            <button
              className="btn-ghost"
              onClick={() => void exportAll(selected.length ? selected : visible.map((c) => c.id))}
              disabled={busy || !visible.length}
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
              {selected.length ? `Export ${selected.length}` : `Export all (${visible.length})`}
            </button>
            <Link to="/new" className="btn-primary">
              <Sparkles size={15} /> New
            </Link>
          </div>
        }
      />
      {error && <ErrorNote message={error} onClose={() => setError("")} />}

      <div className="flex flex-wrap items-center gap-2">
        <div>
          <select
            className="input py-2 text-xs"
            value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value)}
          >
            <option value="all">All videos</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.title}</option>
            ))}
          </select>

        </div>
        <div>
          <select
            className="input py-2 text-xs"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

        </div>
        {ratios.length > 1 && (
          <div>
            <select
              className="input py-2 text-xs"
              value={ratio}
              onChange={(e) => setRatio(e.target.value)}
            >
              <option value="all">All formats</option>
              {ratios.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <select
            className="input py-2 text-xs"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          >
            {Object.entries(SORTS).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>

        </div>
        {selected.length > 0 && (
          <button className="btn-ghost btn-sm" onClick={() => setSelected([])}>
            Clear selection ({selected.length})
          </button>
        )}
        {clips && clips.length > 0 && (
          <button
            className="btn-ghost btn-sm ml-auto"
            onClick={() => setSelected(visible.map((c) => c.id))}
          >
            <Hash size={12} /> Select all shown
          </button>
        )}
      </div>

      {!clips ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton h-72" />)}
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          icon={<Scissors size={22} />}
          title="No clips match this filter"
          body="Analyze a video to generate moments, or clear the filters above."
          action={<Link to="/new" className="btn-primary">Add a video</Link>}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((c) => (
            <ClipCard
              key={c.id}
              clip={c}
              selected={selected.includes(c.id)}
              onToggle={toggle}
              onError={setError}
            />
          ))}
        </div>
      )}

      {selected.length > 0 && (
        <div className="sticky bottom-4 z-10 mx-auto flex max-w-xl items-center justify-between gap-3 rounded-2xl border border-violet-400/25 bg-ink-800/95 px-4 py-3 shadow-2xl backdrop-blur-xl">
          <p className="text-sm text-slate-300">
            <span className="font-semibold text-white">{selected.length}</span> selected
          </p>
          <button className="btn-primary btn-sm" onClick={() => void exportAll(selected)} disabled={busy}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />} Export batch
          </button>
        </div>
      )}
    </div>
  );
}
