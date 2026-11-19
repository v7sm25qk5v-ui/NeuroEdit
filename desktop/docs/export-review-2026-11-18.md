# Export pathway review — 2026-11-18

**Status:** steps 1 and 2 of the build order below were implemented the same day, with the
report moved into the project folder and automatic frame rate on. See the top entry in
`HANDOFF.md`. Step 3 (range export, smart-render research) is still open.

**Goal:** export should feel like the best of iMovie, Final Cut Pro and DaVinci Resolve. It should be simple, smooth and efficient, and it should just work.

**How this was done**
- Three read-only reviews: the render engine with a benchmark, the export flow, and export history plus tests.
- The coordinator re-measured the encoder and parallelism claims.
- No product code changed.

**Machine:** Apple M3 Pro with 12 cores, using the bundled ffmpeg 7.1 (arm64), which has `h264_videotoolbox`.

## Summary

The render engine is correct and careful:
- one frame clock for every segment;
- redactions force a re-render;
- atomic publish;
- audio mixed once from the original files;
- 72 export tests.

The problems are in how export *feels*:
1. **Five modal windows to make one file.** The path is preflight, settings, checklist, save panel, then a completion box. The checklist appears every time, even when every box is already ticked.
2. **The app is frozen while exporting.** The progress dialog is `ApplicationModal`.
3. **Progress can sit at 0% for the whole encode.** An untouched clip reports 0%, then jumps to 92% when its segment finishes.
4. **Cancel takes 3.5–5 s.**
5. **Failures arrive late and in ffmpeg language.**
   - Nothing checks free space before starting.
   - Nothing checks for iCloud-evicted source files.
   - Errors show raw ffmpeg stderr.

**Speed is limited by the hardware encoder.** The Mac hardware encoder runs at about 6× realtime for 1080p, whatever the content. Running it in parallel doesn't help. Switching to the software encoder (libx264) would be slower on real footage, not faster.

The big wins are therefore:
- never blocking the user;
- honest progress with time remaining;
- instant cancel;
- failing before the encode starts rather than at 90%.

Shaving encode time matters less.

## Measurements

### Engine benchmark

Synthetic 1080p30 H.264/AAC test clips, headless `ProjectExporter.export()`:

| Case | Media | Wall | Realtime |
|---|---|---|---|
| One untouched clip | 40 s | 6.8 s | 5.9× |
| Two clips | 70 s | 12.1 s | 5.8× |
| 10 s annotation | 40 s | 7.5 s | 5.3× |
| 10 s redaction | 40 s | 7.3 s | 5.5× |
| 2 s fades | 40 s | 7.3 s | 5.5× |
| Slide at end | 45 s | 7.8 s | 5.8× |
| 2× speed | 20 s | 3.6 s | 5.6× |

- The Python frame-render path (decode, fit, paint) runs at about 479 fps, so it is not the bottleneck.
- The hardware encoder runs at about 200 fps and is.
- The first progress callback arrives within 0.1 s once the venv is warm. Cold iCloud hydration of the venv cost 18 s once.

### Hardware vs software encoder

20 s of 1080p30, re-measured by the coordinator with the app's scale, pad and fps filter chain:

| Encoder | Clean test pattern | Noisy footage (closer to real camera) |
|---|---|---|
| VideoToolbox 12 Mb/s (today) | 3.0 s, 28 MB | **3.2 s, 30 MB** |
| VideoToolbox `-q:v 60` | 2.9 s, 16 MB | 3.1 s, 92 MB |
| libx264 veryfast CRF 20 | 1.3 s, 17 MB | 7.7 s, 302 MB |
| libx264 superfast CRF 20 | 1.0 s, 32 MB | 5.7 s, 325 MB |

- **Keep VideoToolbox.** Its speed and file size are predictable. libx264 is faster only on trivially compressible content.
- Because VideoToolbox is constant-bitrate, the file size can be estimated accurately up front: bitrate × duration came within about 5%.

### Parallel encoding

Running 1, 2 and 3 VideoToolbox encodes at once took 3.2 s, 6.6 s and 10.0 s. One stream saturates the encoder, so parallel segment encoding gives **no** speed-up.

## Findings, ranked by user impact

**Flow** (`ui/export_workflow.py`, `ui/dialogs.py`, `ui/main_window.py`)

1. **Five serial modals in the wrong order** (`export_workflow.py:39-107`).
   - The preflight Yes/No box repeats the PHI questions the checklist asks next (`editor_panels.py:2843`).
   - "Run Guided PHI Review…" in the checklist abandons the export after the user has already chosen settings (`export_workflow.py:85-88`).
   - The shortest happy path is 5 clicks; it is 6 with the preflight, which is typical.
2. **The whole app is blocked during export** (`export_workflow.py:179`, `ApplicationModal`). The worker already exports a snapshot (`:175`), and closing the window or switching projects are already guarded (`main_window.py:1226-1247`, `3418-3480`). So letting the user keep editing is mostly a UI change.
3. **There is no keyboard shortcut and no menu item for exporting video.** The toolbar button is the only entry point (`main_window.py:720`).
4. **The save location is never remembered.** `~/Movies` is hard-coded (`export_workflow.py:94`). A second export of the same project hits the OS overwrite prompt, which replaces an earlier PHI-reviewed file.
5. **Some advanced settings mislead users.**
   - "Quality (CRF)" is ignored on Macs, because the hardware encoder uses a fixed bitrate (`exporter.py:657-667`).
   - The "File type" combo is disabled and has one option.
   - Width and Height accept arbitrary sizes.
6. **The completion box is modal**, with a long path and the report path in it (`export_workflow.py:270-288`).
7. **The `.export-report.txt` is written next to the MP4** (`export_workflow.py:309`). The report's own header says it may contain case notes and is not de-identified. It sits in the folder people share or email.
8. **The tutorial's export step says the MP4 "includes… audio"** (`ui/tutorial.py:738`). That contradicts the remove-original-audio default.

**Engine** (`exporter.py`)

9. **No progress inside ffmpeg segments** (`:332-337`). A 30-minute untouched clip shows 0% for minutes, and there is no time remaining.
10. **Cancel is slow** (measured 3.5–5 s).
    - `_run_ffmpeg` sends SIGTERM and then waits (`:698-701`), so ffmpeg finishes writing the file, including the faststart rewrite, before it exits.
    - The render path waits up to 5 s for ffmpeg blocked on stdin, and only closes stdin afterwards (`:602-611`).
    - The `-encoders` and audio probes (up to 15 s each) don't poll cancel.
11. **No free-space check** (unlike Save As). Peak temp use is about 3× the output size in `$TMPDIR` on the startup disk, which is about 98% full here.
12. **Temp folders leak after a crash** (measured: `neuroedit_export_*` folders are left behind). Nothing sweeps them at startup.
13. **Raw ffmpeg errors are shown to the user.** For example: `[mov,mp4,m4a,3gp,3g2,mj2 @ 0x…] moov atom not found`. The message doesn't name which clip failed.
14. **iCloud-evicted sources** (suspected; consistent with the Save As investigation). Export only stats them (`:220`), so the first ffmpeg read either blocks while macOS downloads the file or fails.
15. **Output is always 30 fps** (`dialogs.py:582-610`). 25, 50 and 60 fps sources, which are common from PAL endoscopy towers and screen recorders, are converted to 30 and judder. Clips don't store their frame rate; `video_probe.py:16` reads it but discards it.
16. **Avoidable full-file passes.**
    - `+faststart` is applied to every segment, the join and the mux; only the last one matters.
    - The join and the audio mux are separate full copies.
    - A destination on another volume adds one more copy (`_publish_file`).
17. **The audio mux opens the source file once per split clip and reads it from the start** (`_mux_audio`, `:1248-1273`). There is no input `-ss`. This only matters when original clip audio is kept, which is off by default (read in code, not measured).

**Already good — don't re-flag**
- The frame clock and redaction forcing.
- Atomic publish and overwrite safety.
- stderr goes to a temp file, so there is no pipe deadlock.
- The CFR forward-read decode (NE-026, closed).
- Audio mixed once from the originals, with no gaps at joins.
- Mixed sizes, rotation, VFR, odd sizes and no-audio clips all export correctly (measured: 36.000 s, 1080 frames).

## What to borrow from each app

| From | Pattern | Adopt? |
|---|---|---|
| iMovie | One share sheet, plain-language quality choices, **live estimated file size** | Yes |
| iMovie / FCP | Export in the background, progress in the toolbar, notification when done | Yes (the biggest win) |
| FCP | One keystroke (⌘E) with a remembered default destination, inline warnings, Show in Finder | Yes |
| Resolve | Time remaining, Quick Export presets | Yes |
| Resolve / FCP | Export a marked range (in/out) | Later |
| Resolve / FCP | Smart render or "bypass re-encode" | Later, research only. It's the only route past the hardware ceiling (40 s untouched: 0.04 s copied vs 5.9 s encoded). But for long-GOP H.264 the re-encoded joins must share the source's encoder parameters or players glitch at the joins. FCP and Resolve only do this reliably for matching intra-frame codecs. |
| Resolve | Render queue, multiple destinations, codec choice | No. Too complex. Upload destinations are also a PHI risk. Keep H.264 MP4 for compatibility with hospital PCs and PowerPoint. |

## Recommended design

### The sheet

One sheet opens from ⌘E, File ▸ Export Movie…, or the Export button:

```
┌ Export ──────────────────────────────────────────────┐
│ [frame]  Case 12 — Lumbar decompression       12:41  │
│ Quality  (•) Standard 1080p ( ) Smaller 720p ( ) 4K  │
│          About 1.1 GB · about 2 min on this Mac      │
│ Audio    [x] Remove original clip audio              │
│ Captions [ ] Burn in captions                        │
│ Frame rate  Automatic (matches your video: 25 fps) ▾ │
│ Save as  [Case 12 — Lumbar decompression ]           │
│ Where    [~/Movies ▾]                                │
│ ── Privacy ───────────────────────────────────────── │
│ ✓ PHI review, de-identification and consent          │
│   confirmed                             [Review…]    │
│   (or the three checkboxes when any is unconfirmed)  │
│ 3 suggestions for this video                [View]   │
│                                  [Cancel] [Export]   │
└──────────────────────────────────────────────────────┘
```

- **Removed:**
  - the preflight modal; PHI items move into the sheet, and the rest becomes "N suggestions";
  - the separate checklist dialog;
  - the native save panel; the folder and name are inline and remembered;
  - the File type combo;
  - the CRF, width and height fields.
- **Privacy gate is unchanged.** Export stays disabled until the three required confirmations and the conditional caption check hold. Edits already reset the confirmations: `_mark_dirty(review_relevant=True)` is called from the timeline, slides, audio, gesture and annotation paths, about 25 call sites. So showing "confirmed" is exactly as strong as today's pre-ticked boxes. "Review…" opens the guided review and returns to the sheet.
- **Never overwrite silently.** If the name exists, suggest "… 2".

### After Export

- The sheet closes and the user can keep editing; the export uses the snapshot taken at click time.
- The Export button becomes a progress pill, for example "Exporting 42% · 1 min left". Clicking it shows details and Cancel.
- When it finishes:
  - the status bar and a macOS notification say "Exported 'Case 12' — Show in Finder";
  - no modal box appears;
  - the entry is added to Export History.
- If it fails, one plain-language dialog explains which clip and what to do, with Details and Try Again.

### Engine work behind the sheet

- **Progress and time remaining.** Use `-progress pipe:1` for ffmpeg segments.
- **Instant cancel.** Use `kill()`; close stdin before waiting; poll cancel during the probes.
- **Checks before encoding.**
  - Free space on the temp and destination volumes; reuse `project_copy.space_problem` and `format_bytes`.
  - Hydrate iCloud-evicted sources with a "Downloading from iCloud…" phase; reuse `project_copy.is_dataless`.
  - Destination is writable.
- **Fewer passes.**
  - `+faststart` only on the final file.
  - Join and audio mux in one ffmpeg pass.
  - Write the final file as a hidden partial in the destination folder, then rename it (no cross-volume copy).
- **Clean up.** Sweep stale `neuroedit_export_*` temp folders at startup.
- **Plain-language errors.** Map no space, permission denied and unreadable or corrupt source (naming the clip). Keep the raw text under Details.
- **Automatic frame rate.** Match the dominant source rate (for example 25, 30, 50 or 60, using the probed fps). Keep an override.

### Decisions for the owner

1. **Where the export report goes.** The recommendation is the project folder, reachable from Export History. Today it sits beside the MP4, where it can be shared by accident.
2. **Automatic frame rate.** The recommendation is to turn it on. It changes the output frame rate for 25, 50 and 60 fps sources, which today become 30.

## Suggested order

1. **Engine:**
   - progress with time remaining;
   - instant cancel;
   - checks before encoding;
   - temp sweep;
   - plain errors;
   - fewer passes.

   This is invisible and low-risk, it lives in `exporter.py` and its tests, and background export depends on its progress reporting.
2. **Flow:**
   - the single sheet;
   - ⌘E and the menu item;
   - remembered location;
   - background export with the toolbar pill and notification;
   - the tutorial wording.

   This lives in `dialogs.py`, `export_workflow.py`, `main_window.py` and their tests. It can be built in parallel with step 1 because the files don't overlap, and the progress callback signature stays the same.
3. **Then:** automatic frame rate, the report location, range export, and the smart-render research.

## Not verified

- Real clinical footage. The benchmarks used synthetic sources, including a noise-heavy source standing in for real camera footage.
- Behaviour on 4K, on 8-core or fanless Macs, and on Windows (libx264 with CRF, so the size estimate there is approximate).
- Whether the UI stays smooth while a background export runs its Python render segments, which compete for the GIL. This needs measuring once export is non-modal.
