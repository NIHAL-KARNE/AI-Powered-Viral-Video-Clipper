import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  UploadCloud,
  Link2,
  Film,
  ArrowRight,
  CircleAlert,
  Loader2,
  X,
  MonitorPlay,
  Clock,
  HardDrive,
} from "lucide-react";
import { api, fmtBytes, fmtDuration, fmtTime, mediaUrl, uploadVideo } from "../lib/api";
import type { UploadProgress } from "../lib/api";
import type { Project } from "../lib/types";
import { ErrorNote } from "./ui";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v,.mpeg,.mpg";
type Mode = "upload" | "url";

export function IntakePanel({ compact = false }: { compact?: boolean }) {
  const [mode, setMode] = useState<Mode>("upload");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phaseLabel, setPhaseLabel] = useState("");
  const [speed, setSpeed] = useState(0);
  const [eta, setEta] = useState<number | null>(null);
  /** Bytes haven't moved for a while — the connection is likely stuck. */
  const [stalled, setStalled] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const lastMove = useRef<{ at: number; loaded: number }>({ at: 0, loaded: 0 });
  const [error, setError] = useState("");
  const [url, setUrl] = useState("");
  const [phase, setPhase] = useState("");
  const [pending, setPending] = useState<Project | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const cancel = () => {
    abortRef.current?.abort();
  };

  const handleFile = useCallback(
    async (file: File) => {
      setError("");
      setPending(null);
      setBusy(true);
      setProgress(0);
      setSpeed(0);
      setEta(null);
      setPhase(`Uploading ${file.name}`);
      setPhaseLabel("Starting upload");
      const controller = new AbortController();
      abortRef.current = controller;
      lastMove.current = { at: Date.now(), loaded: 0 };
      setStalled(false);
      try {
        const project = await uploadVideo(
          file,
          (p: UploadProgress) => {
            setProgress(p.fraction);
            setSpeed(p.speed);
            setEta(p.eta);
            if (p.loaded > lastMove.current.loaded) {
              lastMove.current = { at: Date.now(), loaded: p.loaded };
              setStalled(false);
            } else if (p.phase === "uploading" && Date.now() - lastMove.current.at > 12000 && p.fraction < 1) {
              // A quiet connection is worth naming, not leaving as a frozen bar.
              setStalled(true);
            }
            setPhaseLabel(
              p.phase === "finishing"
                ? "Upload complete — reading the video"
                : `Uploading ${fmtBytes(p.loaded)} of ${fmtBytes(p.total)}`,
            );
          },
          controller.signal,
        );
        setPhase("Video received — checking metadata");
        setProgress(1);
        setPending(project);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          setError("Upload cancelled. Nothing was saved.");
        } else {
          setError(err instanceof Error ? err.message : "Upload failed");
        }
      } finally {
        abortRef.current = null;
        setBusy(false);
        setPhase("");
        setPhaseLabel("");
        setSpeed(0);
        setEta(null);
      }
    },
    [],
  );

  const submitUrl = async () => {
    setError("");
    setPending(null);
    if (!url.trim()) {
      setError("Paste a video link first.");
      return;
    }
    setBusy(true);
    setProgress(0.05);
    setPhase("Validating link and fetching metadata");
    try {
      const res = await api.importUrl(url.trim());
      setPending(res.project);
      setPhase("Downloaded and ready");
      setProgress(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not import that link");
    } finally {
      setBusy(false);
    }
  };

  const openProject = (p: Project, analyze = false) =>
    navigate(`/project/${p.id}${analyze ? "?analyze=1" : ""}`);

  return (
    <div className={compact ? "" : "space-y-5"}>
      <div className="card overflow-hidden">
        <div className="relative flex gap-1 border-b border-white/8 p-1.5">
          {(
            [
              { key: "upload", label: "Upload video", icon: UploadCloud },
              { key: "url", label: "Paste link", icon: Link2 },
            ] as const
          ).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => {
                setMode(key);
                setError("");
              }}
              className={`relative flex flex-1 items-center justify-center gap-2 rounded-[11px] border px-4 py-2.5 text-[13px] font-medium transition ${
                mode === key
                  ? "border-white/12 bg-gradient-to-b from-white/12 to-white/[0.03] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.16),0_8px_18px_-14px_rgba(0,0,0,0.9)]"
                  : "border-transparent text-slate-400 hover:bg-white/[0.04] hover:text-slate-200"
              }`}
            >
              <Icon size={15} className={mode === key ? "text-violet-200" : ""} />
              {label}
            </button>
          ))}
        </div>

        <div className="p-5 sm:p-7">
          {mode === "upload" ? (
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file && !busy) void handleFile(file);
              }}
              className={`group relative grid place-items-center overflow-hidden rounded-2xl border border-dashed px-6 py-12 text-center transition ${
                dragging
                  ? "border-violet-300/80 bg-violet-400/12 shadow-[inset_0_0_60px_-10px_rgba(129,102,255,0.55)]"
                  : "border-white/16 bg-gradient-to-b from-white/[0.055] to-white/[0.012] hover:border-white/30 hover:from-white/[0.08]"
              }`}
            >
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleFile(file);
                  e.target.value = "";
                }}
              />
              <div
                className={`grid h-16 w-16 place-items-center rounded-[18px] border border-white/12 bg-gradient-to-br from-violet-400/30 via-violet-500/15 to-teal-300/10 text-violet-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_16px_34px_-18px_rgba(129,102,255,0.95)] ${
                  busy ? "" : "pulse-ring"
                }`}
              >
                {busy ? <Loader2 size={26} className="animate-spin" /> : <UploadCloud size={26} />}
              </div>
              <h3 className="mt-4 text-[17px] font-semibold text-white">
                {busy ? phase || "Uploading…" : "Drop your long-form video here"}
              </h3>
              <p className="mt-1.5 text-sm text-slate-400">
                MP4, MOV, MKV, WEBM, AVI · up to 4 GB · processed locally
              </p>
              {!busy && (
                <button className="btn-primary mt-5" onClick={() => fileInput.current?.click()}>
                  <Film size={16} /> Choose file
                </button>
              )}
              {busy && (
                <div className="mt-5 w-full max-w-sm">
                  <div className="h-2 overflow-hidden rounded-full border border-white/10 bg-black/40">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-violet-500 via-violet-400 to-teal-300 transition-[width] duration-200"
                      style={{ width: `${Math.max(Math.round(progress * 100), 2)}%` }}
                    />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-3 text-xs tabular-nums text-slate-400">
                    <span className="truncate">{phaseLabel}</span>
                    <span className="shrink-0 font-semibold text-slate-200">
                      {Math.round(progress * 100)}%
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center justify-between gap-3 text-[11px] tabular-nums text-slate-400">
                    <span className={stalled ? "text-amber-300" : ""}>
                      {stalled
                        ? "Waiting on the connection — retrying…"
                        : `${speed > 0 ? `${fmtBytes(speed)}/s` : "Measuring speed…"}${
                            eta !== null && eta > 1 && !stalled ? ` · about ${fmtDuration(eta)} left` : ""
                          }`}
                    </span>
                    <button
                      onClick={cancel}
                      className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 font-medium text-slate-300 transition hover:border-rose-400/40 hover:text-rose-200"
                    >
                      <X size={11} /> Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div>
              <label className="label">Video URL</label>
              <div className="flex flex-col gap-2.5 sm:flex-row">
                <input
                  className="input flex-1"
                  placeholder="https://www.youtube.com/watch?v=…"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !busy) void submitUrl();
                  }}
                  disabled={busy}
                />
                <button className="btn-primary shrink-0" onClick={() => void submitUrl()} disabled={busy}>
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Link2 size={16} />}
                  {busy ? "Fetching…" : "Import video"}
                </button>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-slate-400">
                Supported: YouTube, Vimeo, Dailymotion, Twitch. Only download videos you have the right
                to use — processing follows each platform&apos;s terms and your local copyright rules.
              </p>
              {busy && (
                <div className="glass-inset mt-4 p-4">
                  <div className="flex items-center gap-2 text-sm text-slate-300">
                    <Loader2 size={15} className="animate-spin text-violet-300" />
                    {phase}
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full w-2/5 animate-pulse rounded-full bg-violet-400" />
                  </div>
                </div>
              )}
            </div>
          )}

          {error && (
            <div className="mt-4">
              <ErrorNote message={error} onClose={() => setError("")} />
            </div>
          )}

          {pending && (
            <div className="animate-rise mt-5 rounded-2xl border border-emerald-400/20 bg-emerald-500/[0.06] p-4">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-xl bg-black/50 sm:w-40">
                  {pending.thumbnail ? (
                    <img src={mediaUrl(pending.thumbnail)} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="grid h-full place-items-center text-slate-600">
                      <MonitorPlay size={22} />
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> Ready to analyze
                  </div>
                  <h4 className="mt-1 truncate text-[15px] font-semibold text-white">{pending.title}</h4>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="chip"><Clock size={11} /> {fmtTime(pending.meta.duration)}</span>
                    <span className="chip"><MonitorPlay size={11} /> {pending.meta.width}×{pending.meta.height}</span>
                    <span className="chip"><HardDrive size={11} /> {fmtBytes(pending.meta.size)}</span>
                  </div>
                </div>
                <button className="btn-primary shrink-0" onClick={() => openProject(pending, true)}>
                  Analyze video <ArrowRight size={16} />
                </button>
              </div>
            </div>
          )}

          {!compact && (
            <div className="mt-5 flex items-start gap-2 rounded-xl glass-inset px-4 py-3 text-[12px] leading-relaxed text-slate-400">
              <CircleAlert size={15} className="mt-0.5 shrink-0 text-slate-400" />
              <p>
                Analysis runs on this machine: Whisper speech-to-text, audio energy analysis, scene and
                face detection, then a weighted scoring model finds self-contained moments. Viral scores
                are estimates, not guarantees.
              </p>
            </div>
          )}
        </div>
      </div>
      {pending && (
        <p className="px-1 text-xs text-slate-400">
          Duration {fmtDuration(pending.meta.duration)} · {pending.meta.fps.toFixed(0)} fps ·{" "}
          {pending.meta.codec?.toUpperCase()}
        </p>
      )}
    </div>
  );
}
