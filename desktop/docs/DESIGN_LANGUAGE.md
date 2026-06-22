# NeuroEdit Design Language Brief

Source of truth: the owner's Figma Make concept
[Redesign video editing app UI](https://www.figma.com/make/EwIb4hEXiKH6uq5NipTXEr/Redesign-video-editing-app-UI?t=GISE85bHg74npOdT-6).
Figma Make files cannot be read programmatically through the Figma MCP/API, so
pixel-level values must be transcribed manually from the Make preview into
[`src/neuroedit_desktop/ui/styles.py`](../src/neuroedit_desktop/ui/styles.py) —
this brief is the contract for *where* each decision lands in code.

## Visual grammar

1. **Warm light editor chrome by default.** The primary app shell follows the
   Figma screenshot: cream canvas, bone panels, tan borders, near-black text,
   and earthy accents. Dark remains available as the high-contrast alternate.
2. **Dark video canvas in every theme.** The video frame is always the
   brightest or most dominant thing on screen. Light mode keeps the preview
   near-black instead of turning the footage area into a white panel.
3. **Clean, high-contrast controls.** Text and controls meet the audited
   contrast targets (see `tests/test_design_tokens.py`): body text ≥ 4.5:1,
   muted metadata ≥ 4.5:1, auxiliary/dim text ≥ 3:1, and filled button labels
   ≥ 3:1 so the preserved dark primary blue remains valid.
4. **Modern rounded panels.** `RADIUS_SM/MD/LG` (7/8/12 px) — buttons and tabs
   small, inputs/list rows/timeline blocks medium, dialogs/previews large.
5. **Clear hierarchy between media / timeline / inspector areas.** Three-pane
   layout (media explorer · video column · inspector stack) over a full-width
   timeline; panes separated by `BORDER_SUBTLE` 1px lines, never heavy chrome.
6. **Restrained clinical trust cues.** Red (`DANGER`) is reserved for
   destructive and privacy-risk states only — never decoration, never SAM
   masks (enforced by test). Amber (`WARNING`) marks non-blocking cautions
   (unreviewed audio, missing markers). Emerald (`SUCCESS`) marks confirmed/
   export-ready states.
7. **Pastel timeline semantics in light mode.** Video, audio, color/markers,
   and narration/slides use peach, sage, amber, and mauve lanes. Dark mode
   keeps the older high-contrast accent mapping.

## Token reference

| Semantic token | Role | Light value | Dark value |
|---|---|---|---|
| `SURFACE_SUNKEN` | app background | `#f5f0e8` | `#090a0f` |
| `SURFACE` | panels, timeline background | `#fffdf8` | `#10131a` |
| `SURFACE_HEADER` | header, status bar, popovers | `#f0ebe2` | `#151923` |
| `SURFACE_RAISED` | buttons, inputs, cards | `#fffaf1` | `#1b202b` |
| `BG_HOVER` | hover fill | `#e8dfd2` | `#242a36` |
| `BORDER_SUBTLE` / `BORDER_BRIGHT` | resting / engaged borders | `#d8cfc1` / `#b9aa98` | `#2c3340` / `#465161` |
| `ACCENT_PRIMARY` (+`PRIMARY_HOVER`) | primary action, selection | `#1a1714` / `#332c25` | `#4f7cff` / `#3f68dc` |
| `ACCENT_CLINICAL` | SAM / stills / captions cues | `#2f6f4e` | `#22d3ee` |
| `ACCENT_SLIDES` | slides track + panel accent | `#8a5570` | `#8b5cf6` |
| `DANGER` | destructive / privacy risk only | `#9f2f24` | `#ef4444` |
| `WARNING` | non-blocking caution | `#76500f` | `#f59e0b` |
| `SUCCESS` | confirmation / ready | `#276749` | `#10b981` |
| `SELECTION_OUTLINE` | timeline selected block + snap guide | `#8f3f25` | `#FFD60A` |
| `VIDEO_CANVAS` | video viewer background | `#11100e` | `#000000` |
| `TEXT_PRIMARY` → `TEXT_DIM` | 4-step text ramp | `#1a1714 #635b52 #6f665c #8b8176` | `#e2e8f0 #94a3b8 #8093ab #64748b` |

`styles.py` owns both themes, the `appearance/themeMode` setting, the Qt
palette, QSS sheet, and timeline semantic colors. Startup applies the saved
theme before importing `MainWindow`, so token imports resolve to the active
appearance.

## Surface → token/component map

| NeuroEdit surface | Code location | Tokens / components | Figma Make reference |
|---|---|---|---|
| Header (identity, history, project, tabs, export) | `main_window._build_header` | `SURFACE_HEADER`, panel-tab QSS role, `_tool_btn_css` | top toolbar frame |
| Transport controls | `_build_central_ui` controls bar | `SURFACE`, `ACCENT_PRIMARY` play button | player chrome frame |
| Media/project library | `MediaExplorerPanel`, `ProjectLibraryDialog` | `SURFACE`, list-row QSS, `SUCCESS`/`DANGER`/`TEXT_MUTED` status colors | left rail + library modal |
| Timeline tracks | `editor_panels.TimelineCanvas` | `TIMELINE_VIDEO/AUDIO/SLIDES/MARKERS`, `SELECTION_OUTLINE`, snap guide | timeline frame |
| Inspector panels (SAM/Labels/Tips/Slides/Audio) | `editor_panels.py`, `main_window.py` panels | per-panel accents from `PANELS` | right inspector frames |
| SAM mask list | `SamPanel` | `MASK_PALETTE` (no red), busy/disabled states | segmentation panel frame |
| PHI review stepper | `PhiReviewDialog` | `ACCENT_CLINICAL` mark button, muted hints | privacy flow frame |
| Caption controls/preview | `AudioPanel` captions group, `captions.paint_caption` | white text, dark box, safe-area margins | captions frame |
| Export dialogs (settings, checklist, history) | `ExportDialog`, `ExportChecklistDialog`, `ExportHistoryDialog` | `SUCCESS` export button, `WARNING` audio note, recommendation line | export flow frames |
| Empty/error states | library placeholders, SAM explainer, missing-media labels | `TEXT_MUTED`, `DANGER` | empty-state frames |

Every planned UI change should name its row in this table plus the Figma
frame it traces to (fill in exact frame names while transcribing the Make
concept).

## Appearance preference

New users are prompted at first startup to choose Light, Dark, or System. The
choice is saved in `QSettings("NeuroEdit", "Desktop")` under
`appearance/themeMode` and can be changed later from View → Appearance.

## Known deviations to resolve with the Figma pass

- Identity assets now ship the **aperture + scalpel** mark (a seven-blade lens
  iris revealing a surgical scalpel): theme-matched header/About lockups render
  `neuroedit-mark-{light,dark}.svg` directly, and the macOS/Windows app icons
  come from the dark-tile app icon. Wordmark is Space Grotesk 600 at −0.02em
  (falls back to the UI sans). Tracked in [ASSET_CHECKLIST.md](ASSET_CHECKLIST.md).

## Verification

- Automated: `python -m pytest tests/test_design_tokens.py` (contrast +
  red-reservation audit).
- Visual: `python scripts/capture_baseline_screenshots.py` before and after a
  token change; compare against [VISUAL_QA_CHECKLIST.md](VISUAL_QA_CHECKLIST.md).
