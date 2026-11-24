# Project notes

freecode reads this file before every change. Add anything it should always remember about this project.

## Shape
- FastAPI backend in `backend/app` (run from `backend/` on 127.0.0.1:8000), React + TS + Tailwind frontend in `src/`.
- `backend/data/` holds uploads, clips, cache and `db.json`. It is gitignored and must be cleaned
  before finishing: the workspace save limit is 2,000 files / 20 MB. `rm -rf backend/data/{clips,exports,cache/*,uploads/*,db.json}`.

## Analysis rules
- Frame/face analysis is cached per source hash at **0.5 s sampling** (`FRAME_ANALYSIS_VERSION` in
  `media.py`). Renderer, editor and analysis all use `cached_frames(..., 0.5, hash)` so one scan is shared.
- `cached_frames` returns the whole dict (`frames`, `scenes`). `selection.sentence_features`
  expects that dict, not a bare list — passing a list raises `AttributeError`.
- `analyze_frames` demuxes with `grab()` and only decodes sampled frames. Times come from `idx / fps`.

## Frame layouts
- Modes: `manual`, `face-track`, `center`, `pad`, `dual`, `inset`.
- **`inset`** = background + inset ("facecam over gameplay"): `[vcut]split=2` → background cover-crop
  (or blurred full shot with `inset_bg_fit=blur`) → inset is a separate `crop` of the same source at
  `inset_x/inset_y/inset_zoom`, scaled to `inset_size` of the output width at `inset_shape`, overlaid
  at `inset_pos_x/inset_pos_y`. Optional white `drawbox` outline. Layout: `background + inset`.
- Inset styling (`inset_radius` % of shorter side, `inset_border_color`,
  `inset_border_width` px at 1080 wide, `inset_shadow`): FFmpeg cannot draw rounded corners, so
  `_rounded_inset_assets()` renders a mask, ring and shadow with PIL at 4x, downscales with Lanczos,
  writes them into the render's temp `work` dir, and the graph pulls them in with `movie=`. The crop
  is `alphamerge`d with the mask, then overlay + ring overlay. PIL's `ImageFilter` needs RGBA.
- `opts` from the render endpoint always contains every key, with `None` for unset fields. `bool(None)`
  is False, so features that default to *on* must test `is not False` — never `bool(opts.get(k, True))`.
- Zoom ranges: `crop_rect` clamps any zoom to `MAX_ZOOM = 8`. UI caps are 6× for dual panels, inset
  crop and manual; 4× for the background. `INSET_DEFAULT_ZOOM = 1.8` so a fresh inset is a facecam
  close-up instead of the whole frame shrunk.
- Beware `opts.get("k", default)`: render options pass keys with `None`, so `.get` returns None and
  `float(None)` crashes. Use `x if opts.get("k") is not None else default`.

## Face tracking
- `render._subject_track` links detections into per-person tracks and picks the best by area and
  coverage, so the camera follows one person instead of the largest face per frame.
- `render._track_path` returns clip-relative `(times, xs, ys)`; the same path drives the editor preview
  (via `focus-suggestions`) and the render.
- Frames with no detection emit a `{"held": True}` face so downstream never loses the subject; real
  detections are the ones without that flag.
- `_aim` offsets the crop so the face sits slightly above centre.

## Uploads
- Large media lives in `data/uploads` and `data/clips`, which are **symlinks to `/tmp/clipforge-heavy/`**.
  The real uploads blow the 20 MB save budget on their own; keep the symlinks and never inline them.
  Tests must use `CLIPPER_DATA=/tmp/<dir>`, never the live `backend/data`.
- Never delete `backend/data/cache/*` while an analysis job is running — the job needs the audio WAV
  mid-run. `pipeline.ensure_wav()` re-extracts when it is missing or truncated, but don't rely on it.

- Uploads are **chunked and resumable**: `POST /api/upload/init` → `PUT /api/upload/{id}/chunk/{n}`
  (4 MB, raw octet-stream, idempotent on retry) → `POST /api/upload/{id}/complete`. Partial chunks
  live in `data/chunks/<id>/` and are swept after 24 h.
- `init` takes a `fingerprint` (`name:size:lastModified`): a matching recent upload is resumed, so a
  reload or dropped connection continues instead of restarting.
- The client sends chunks with `XMLHttpRequest` (not `fetch`) to get `upload.onprogress` bytes, which is
  what makes the bar move smoothly inside a 4 MB chunk. Each part has a 60 s timeout + backoff retries.
- `complete` joins the parts and hashes in the same pass; don't re-read the file with `sha256_file`.
- The legacy single-shot `POST /api/upload` still works and shares `_finish_upload`.

## Multiple output formats
- Analysis collects "moments" once, then `pipeline._expand_aspects` writes **one clip per moment per
  ratio** (`moment_index` / `ratio_index` / `ratio_count` group them). Ratios are applied after the
  cache lookup, so changing formats reuses the cached transcript and scores.
- Clip ids are `"{moment_stem}-{ratio}"` (ratio with `:` stripped), so re-analysis keeps ids and
  user edits survive. `_finalize` deletes this project's clips that are no longer produced.
- Previews are per moment (`thumbs/{project}-m{n}.jpg`), shared by all its ratio copies.
- UI: `AspectPicker` (multi-select, at least one required) on New project, Project page and Settings;
  project page shows per-format filter tabs and counts moments, not clips.

## Rendering
- Keyframes: `_keyframe_chain` uses `zoompan` and **must** run at the graph's fps (`fps=` in the chain).
  Mismatched rates buffer frames and get OOM-killed (exit 137) / blank output.
- Animated `crop` w/h expressions are unsupported in FFmpeg 6.1; `crop` has no `eval` option.
- `drawbox`/`drawtext` `w`/`h` mean box/text size — use `W`/`H`/`iw`/`ih` for frame size.
- Export encode: `-preset fast -crf 23 -maxrate 6M -bufsize 12M -movflags +faststart`.

- Parallel uploads: browser sends up to 4 chunks in parallel (8 MB each, `UPLOAD_CONCURRENCY = 4`). Server stages in `UPLOADS/.chunks/<id>/data.bin` via `os.pwrite` + `.done` markers and completes with instant `os.replace`. `/api/upload/init` and `/status` return `received_chunks` for out-of-order resume.
