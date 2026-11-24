export type VideoMeta = {
  duration: number;
  width: number;
  height: number;
  fps: number;
  codec?: string;
  audio_codec?: string;
  has_audio: boolean;
  bitrate: number;
  size: number;
  format?: string;
};

export type ClipExport = {
  path: string;
  url: string;
  size: number;
  duration: number;
  width: number;
  height: number;
  caption_cues: number;
  cut_seconds: number;
  rendered_at: number;
  aspect?: string;
  caption_style?: string;
  at?: number;
};

export type Overlay = {
  id?: string;
  text: string;
  start: number;
  end: number;
  /** Default band. Ignored when `x`/`y` are set. */
  position: "top" | "center" | "bottom";
  size: number;
  color: string;
  /** Free position: left edge and top edge of the text block, 0–1 of the frame. */
  x?: number;
  y?: number;
};

export type Clip = {
  id: string;
  project_id: string;
  score: number;
  start: number;
  end: number;
  duration: number;
  category: string;
  category_label: string;
  reasons: string[];
  text: string;
  hook: string;
  titles: string[];
  selected_title: string;
  description: string;
  hashtags: string[];
  keywords: string[];
  thumbnail: string | null;
  components: Record<string, number>;
  energy: number;
  audio_stats: { silence: number; wps: number; loudness: number };
  visual_stats: { motion: number; face_ratio: number };
  caption_style: string;
  caption_position?: string;
  caption_size?: number;
  aspect: string;
  crop_mode: string;
  /** Manual crop centre, normalised 0-1 in the source frame. */
  crop_x?: number;
  crop_y?: number;
  crop_zoom?: number;
  /** Dual-frame panels (two subjects stacked top/bottom). */
  dual_top_x?: number;
  dual_top_y?: number;
  dual_top_zoom?: number;
  dual_bottom_x?: number;
  dual_bottom_y?: number;
  dual_bottom_zoom?: number;
  dual_auto?: boolean;
  /** Background + inset layout: a full backdrop with a cropped window on top. */
  inset_x?: number;
  inset_y?: number;
  inset_zoom?: number;
  /** Inset width as a fraction of the output width (0.12–0.7). */
  inset_size?: number;
  /** Inset window shape, e.g. "16:9" or "1:1". */
  inset_shape?: string;
  /** Inset centre inside the output frame, 0–1. */
  inset_pos_x?: number;
  inset_pos_y?: number;
  /** Background treatment: "cover" crops, "blur" keeps the whole shot. */
  inset_bg_fit?: string;
  inset_bg_x?: number;
  inset_bg_y?: number;
  inset_bg_zoom?: number;
  inset_border?: boolean;
  /** Outline colour as hex, e.g. "#ffffff". */
  inset_border_color?: string;
  /** Outline thickness, in pixels at 1080 wide. */
  inset_border_width?: number;
  /** Corner curve, as a percentage of the window's shorter side. */
  inset_radius?: number;
  inset_shadow?: boolean;
  frame_preset?: string | null;
  track_motion?: boolean;
  /** Hand-placed camera points: clip-relative time plus centre and zoom. */
  keyframes?: { t: number; x: number; y: number; zoom: number }[];
  /** Groups the per-ratio copies of the same detected moment. */
  moment_index?: number;
  ratio_index?: number;
  ratio_count?: number;
  /** Branding & on-screen extras. */
  headline?: string;
  headline_enabled?: boolean;
  headline_seconds?: number;
  progress_bar?: boolean;
  accent_color?: string;
  remove_fillers?: boolean;
  caption_font?: string;
  trim_start: number;
  trim_end: number;
  volume: number;
  denoise: boolean;
  smart_cuts: boolean;
  zoom: boolean;
  music: string;
  music_volume: number;
  watermark: string;
  watermark_size?: number;
  captions_enabled?: boolean;
  /** Auto emoji and keyword highlighting in captions (on unless false). */
  emoji_enabled?: boolean;
  keywords_enabled?: boolean;
  /** Words per caption cue (2-7). */
  caption_words?: number;
  overlays: Overlay[];
  status: string;
  export?: ClipExport;
  export_path?: string;
  exports?: ClipExport[];
  word_count: number;
  title_source?: string;
  project_title?: string;
  project_duration?: number;
  /** Source video dimensions, used to draw the crop window. */
  source_width?: number;
  source_height?: number;
  edited_at?: number;
  history?: unknown[];
  redo?: unknown[];
};

export type Project = {
  id: string;
  title: string;
  source_type: "upload" | "url";
  source_url?: string | null;
  original_filename?: string | null;
  created_at: number;
  status: "uploaded" | "processing" | "ready" | "error";
  stage: string;
  stage_label: string;
  progress: number;
  meta: VideoMeta;
  thumbnail: string | null;
  clip_ids: string[];
  clips: Clip[];
  error?: string;
  analysis_seconds?: number;
  transcript_segments?: number;
  transcript_language?: string;
  cached_result?: boolean;
  job?: Job | null;
  source_meta?: Record<string, unknown>;
};

export type Job = {
  id: string;
  project_id: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  stage: string;
  label: string;
  error?: string;
  kind?: string;
};

export type Stats = {
  videos: number;
  clips: number;
  exports: number;
  avg_score: number;
  processing: number;
  minutes_analyzed: number;
};

export type DashboardData = {
  projects: Project[];
  stats: Stats;
  recent_clips: Clip[];
};

export type Options = {
  platforms: Record<string, { label: string; aspect: string; width: number; height: number }>;
  aspects: Record<string, [number, number]>;
  caption_styles: Record<string, Record<string, unknown>>;
  music: Record<string, unknown>;
  categories: Record<string, string>;
  presets: Record<string, { label: string; min: number; max: number }>;
  whisper_models: string[];
};

/** The saved "channel look" applied to clips in one click. */
export type BrandKit = {
  name?: string;
  caption_style?: string;
  caption_position?: string;
  caption_size?: number;
  caption_font?: string;
  accent_color?: string;
  watermark?: string;
  watermark_size?: number;
  music?: string;
  music_volume?: number;
  progress_bar?: boolean;
  emoji_enabled?: boolean;
  keywords_enabled?: boolean;
  inset_border_color?: string;
  inset_border_width?: number;
  inset_radius?: number;
};

export type Settings = {
  whisper_model: string;
  llm_enabled: boolean;
  llm_base_url: string;
  llm_model: string;
  llm_api_key_set: boolean;
  max_clips: number;
  default_aspect: string;
  default_aspects: string[];
  emoji_enabled: boolean;
  keywords_enabled: boolean;
  brand_kit: BrandKit;
};
