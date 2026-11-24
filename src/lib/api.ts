import type {
  Clip,
  DashboardData,
  Job,
  Options,
  Project,
  Settings,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers:
      init?.body instanceof FormData
        ? undefined
        : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      message = data.detail || data.message || message;
    } catch {
      /* keep default */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Record<string, unknown>>("/api/health"),
  dashboard: () => request<DashboardData>("/api/dashboard"),
  options: () => request<Options>("/api/options"),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (patch: Partial<Settings>) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),
  brandApply: (body: { clip_ids?: string[]; project_id?: string }) =>
    request<{ applied: number; clip_ids: string[]; patch: Record<string, unknown> }>(
      "/api/brand/apply",
      { method: "POST", body: JSON.stringify(body) },
    ),

  projects: () => request<Project[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  analyze: (id: string, preset: string, maxClips?: number, aspects?: string[]) =>
    request<{ job_id: string }>(`/api/projects/${id}/analyze`, {
      method: "POST",
      body: JSON.stringify({ preset, max_clips: maxClips, aspects }),
    }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  deleteProject: (id: string) =>
    request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

  importUrl: (url: string) =>
    request<{ project: Project; job_id: string }>("/api/import-url", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  clips: (projectId?: string) =>
    request<Clip[]>(`/api/clips${projectId ? `?project_id=${projectId}` : ""}`),
  clip: (id: string) => request<Clip & { transcript_text: string }>(`/api/clips/${id}`),
  patchClip: (id: string, patch: Partial<Clip>) =>
    request<Clip>(`/api/clips/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  headlineSuggestions: (id: string) =>
    request<{ options: string[]; current: string }>(`/api/clips/${id}/headline`, {
      method: "POST",
    }),
  focusSuggestions: (id: string) =>
    request<{
      single: { x: number; y: number; faces: number };
      dual: { top: { x: number; y: number }; bottom: { x: number; y: number } };
      /** Camera path the renderer will follow, for the animated preview. */
      path?: { times: number[]; x: number[]; y: number[] };
    }>(`/api/clips/${id}/focus-suggestions`),
  frameInfo: (id: string) =>
    request<{
      source: { width: number; height: number; duration: number };
      clip: { start: number; end: number; duration: number };
      crop: { mode: string; x: number; y: number; zoom: number };
      dual: {
        auto: boolean;
        top: { x: number; y: number; zoom: number };
        bottom: { x: number; y: number; zoom: number };
      };
      aspects: Record<string, [number, number]>;
    }>(`/api/clips/${id}/frame-info`),
  undo: (id: string) => request<Clip>(`/api/clips/${id}/undo`, { method: "POST" }),
  redo: (id: string) => request<Clip>(`/api/clips/${id}/redo`, { method: "POST" }),
  captions: (id: string) =>
    request<{
      cues: { start: number; end: number; text: string }[];
      words?: { start: number; end: number; word: string }[];
      style: string;
    }>(
      `/api/clips/${id}/captions`,
    ),
  saveCaptions: (id: string, words: { start: number; end: number; word: string }[]) =>
    request<{
      cues: { start: number; end: number; text: string }[];
      words: { start: number; end: number; word: string }[];
      style: string;
    }>(`/api/clips/${id}/captions`, {
      method: "PUT",
      body: JSON.stringify({ words }),
    }),
  render: (id: string, options: Record<string, unknown> = {}) =>
    request<{
      url: string;
      size: number;
      duration: number;
      width: number;
      height: number;
      caption_cues: number;
      cut_seconds: number;
    }>(`/api/clips/${id}/render`, {
      method: "POST",
      body: JSON.stringify({ options }),
    }),
  batchExport: (clipIds: string[], options: Record<string, unknown> = {}) =>
    request<{ rendered: unknown[]; errors: string[] }>("/api/clips/batch-export", {
      method: "POST",
      body: JSON.stringify({ clip_ids: clipIds, options }),
    }),
};

export type UploadProgress = {
  /** 0–1 of bytes that reached the server. */
  fraction: number;
  loaded: number;
  total: number;
  /** Bytes per second over the last few seconds. */
  speed: number;
  /** Seconds remaining, or null while it is still estimating. */
  eta: number | null;
  phase: "uploading" | "finishing";
};

class UploadError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const CHUNK_RETRIES = 4;
/** Give up on a single 4 MB part after this long, then retry it. */
const CHUNK_TIMEOUT_MS = 60_000;

/** PUT one chunk, reporting bytes as they leave the browser. */
function sendChunk(
  uploadId: string,
  index: number,
  body: Blob,
  signal: AbortSignal | undefined,
  onBytes: (sent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", onAbort);
      fn();
    };
    let attempt = 0;
    let lastError = "Upload part failed";

    const onAbort = () => {
      xhr.abort();
      finish(() => reject(new DOMException("Upload cancelled", "AbortError")));
    };

    const xhr = new XMLHttpRequest();
    const run = () => {
      const timer = setTimeout(() => xhr.abort(), CHUNK_TIMEOUT_MS);
      xhr.open("PUT", `/api/upload/${uploadId}/chunk/${index}`);
      xhr.setRequestHeader("content-type", "application/octet-stream");
      // Bytes actually handed to the network — smooth progress inside a chunk.
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onBytes(e.loaded);
      };
      xhr.onload = () => {
        clearTimeout(timer);
        if (xhr.status >= 200 && xhr.status < 300) {
          onBytes(body.size);
          finish(resolve);
          return;
        }
        if (xhr.status === 404 || xhr.status === 400) {
          let detail = "Upload session expired";
          try {
            detail = JSON.parse(xhr.responseText).detail || detail;
          } catch {
            /* keep default */
          }
          finish(() => reject(new UploadError(detail, xhr.status)));
          return;
        }
        lastError = `Server returned ${xhr.status}`;
        retry();
      };
      xhr.onerror = () => {
        clearTimeout(timer);
        lastError = "The connection was interrupted";
        retry();
      };
      xhr.ontimeout = () => {
        clearTimeout(timer);
        lastError = "The connection stalled";
        retry();
      };
      xhr.onabort = () => {
        clearTimeout(timer);
        if (signal?.aborted) return; // handled by onAbort
        lastError = "The connection stalled";
        retry();
      };
      xhr.send(body);
    };

    const retry = () => {
      if (settled) return;
      if (signal?.aborted) {
        finish(() => reject(new DOMException("Upload cancelled", "AbortError")));
        return;
      }
      if (attempt >= CHUNK_RETRIES) {
        finish(() => reject(new UploadError(`${lastError}. Check your connection and retry.`, 0)));
        return;
      }
      attempt += 1;
      setTimeout(() => {
        if (!settled) run();
      }, Math.min(700 * 2 ** attempt, 6000));
    };

    signal?.addEventListener("abort", onAbort);
    run();
  });
}

/** Parallel chunk uploads keep the pipe full on high-latency connections. */
const UPLOAD_CONCURRENCY = 4;

/**
 * Uploads in parallel 8 MB chunks with resume support. Returns real byte
 * progress across all active streams, so large files saturate your upload
 * bandwidth instead of waiting one piece at a time.
 */
export async function uploadVideo(
  file: File,
  onProgress: (p: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<Project> {
  // Identify the file by name, size and last-modified time so an interrupted
  // upload can be picked up again after a reload.
  const fingerprint = `${file.name}:${file.size}:${file.lastModified}`;
  const started = await request<{
    upload_id: string;
    chunk_size: number;
    total_chunks: number;
    next_chunk: number;
    received_chunks?: number[];
    received?: number;
    resumed?: boolean;
  }>("/api/upload/init", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, size: file.size, fingerprint }),
  });

  const { upload_id, chunk_size, total_chunks } = started;
  const doneSet = new Set<number>(
    started.received_chunks ??
      Array.from({ length: started.next_chunk }, (_, i) => i),
  );

  // Build the queue of remaining chunk indices.
  const queue: number[] = [];
  let completedBytes = 0;
  for (let i = 0; i < total_chunks; i++) {
    const startByte = i * chunk_size;
    const len = Math.min(startByte + chunk_size, file.size) - startByte;
    if (doneSet.has(i)) {
      completedBytes += len;
    } else {
      queue.push(i);
    }
  }

  const inFlight = new Map<number, number>();
  let highWater = completedBytes;
  // Throughput over a trailing window, so an early fast chunk doesn't inflate it.
  const recent: { at: number; bytes: number }[] = [];
  let lastReportAt = 0;

  const currentLoaded = () => {
    let active = 0;
    for (const v of inFlight.values()) active += v;
    const total = Math.min(completedBytes + active, file.size);
    // Keep progress monotonic even if one stream retries.
    if (total > highWater) highWater = total;
    return highWater;
  };

  const report = (phase: UploadProgress["phase"], force = false) => {
    const now = performance.now();
    if (!force && now - lastReportAt < 100) return;
    lastReportAt = now;
    const loaded = currentLoaded();
    recent.push({ at: now, bytes: loaded });
    while (recent.length > 2 && now - recent[0].at > 8000) recent.shift();
    const span = recent.length > 1 ? (now - recent[0].at) / 1000 : 0;
    const moved = recent.length > 1 ? loaded - recent[0].bytes : 0;
    const speed = span > 0.6 && moved > 0 ? moved / span : 0;
    onProgress({
      fraction: Math.min(loaded / file.size, 1),
      loaded,
      total: file.size,
      speed,
      eta: speed > 0 ? Math.max((file.size - loaded) / speed, 0) : null,
      phase,
    });
  };

  report("uploading", true);

  let cursor = 0;
  const worker = async () => {
    while (cursor < queue.length) {
      if (signal?.aborted) throw new DOMException("Upload cancelled", "AbortError");
      const index = queue[cursor++];
      const startByte = index * chunk_size;
      const blob = file.slice(startByte, Math.min(startByte + chunk_size, file.size));
      inFlight.set(index, 0);
      await sendChunk(upload_id, index, blob, signal, (sent) => {
        const prev = inFlight.get(index) ?? 0;
        if (sent > prev) {
          inFlight.set(index, sent);
          report("uploading");
        }
      });
      inFlight.delete(index);
      completedBytes += blob.size;
      report("uploading", true);
    }
  };

  const workers = Math.min(UPLOAD_CONCURRENCY, Math.max(queue.length, 1));
  await Promise.all(Array.from({ length: workers }, () => worker()));

  onProgress({
    fraction: 1,
    loaded: file.size,
    total: file.size,
    speed: 0,
    eta: 0,
    phase: "finishing",
  });

  return request<Project>(`/api/upload/${upload_id}/complete`, { method: "POST" });
}

export const mediaUrl = (path?: string | null) => {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return path;
};

export const fmtTime = (seconds: number, withMs = false) => {
  const s = Math.max(0, seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const base = h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
  if (!withMs) return base;
  return `${base}.${String(Math.floor((s % 1) * 100)).padStart(2, "0")}`;
};

export const fmtDuration = (seconds: number) => {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
};

export const fmtBytes = (bytes: number) => {
  if (!bytes) return "0 MB";
  const mb = bytes / (1024 * 1024);
  if (mb < 1) return `${(bytes / 1024).toFixed(0)} KB`;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
};

export const scoreColor = (score: number) => {
  if (score >= 85) return { text: "text-emerald-300", bg: "bg-emerald-400", ring: "ring-emerald-400/40" };
  if (score >= 72) return { text: "text-lime-300", bg: "bg-lime-400", ring: "ring-lime-400/40" };
  if (score >= 58) return { text: "text-amber-300", bg: "bg-amber-400", ring: "ring-amber-400/40" };
  return { text: "text-slate-300", bg: "bg-slate-400", ring: "ring-slate-400/40" };
};
