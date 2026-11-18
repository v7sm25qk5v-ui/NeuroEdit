# NeuroEdit Design Language Brief

Source of truth: the owner's Figma Make concept
[Redesign video editing app UI](https://www.figma.com/make/EwIb4hEXiKH6uq5NipTXEr/Redesign-video-editing-app-UI?t=GISE85bHg74npOdT-6).
Figma Make files cannot be read programmatically through the Figma MCP/API, so
pixel-level values must be transcribed manually from the Make preview into
[`src/neuroedit_desktop/ui/styles.py`](../src/neuroedit_desktop/ui/styles.py) —
this brief is the contract for *where* each decision lands in code.

## Visual grammar

1. **Watercolor-blue light chrome by default (NE-037, 2026-11-18).** Pale
   washed-blue canvas and panels, blue-gray borders, charcoal text and charcoal
   primary actions. Dark uses charcoal surfaces with a washed-blue primary.
   (Replaces the earlier cream/tan Figma direction.)
2. **Dark video canvas in every theme.** The video frame is always the
   brightest or most dominant thing on screen. Light mode keeps the preview
   near-black instead of turning the footage area into a white panel.
3. **Clean, high-contrast controls.** Text and controls meet the audited
   contrast targets (see `tests/test_design_tokens.py`): body text ≥ 4.5:1,
   muted metadata ≥ 4.5:1, auxiliary/dim text ≥ 3:1, and filled button labels
   ≥ 3:1 so the preserved dark primary blue remains valid.
4. **Modern rounded panels.** `RADIUS_SM/MD/LG` (10/12/16 px, NE-039) — list
   rows small, buttons/tabs/inputs/popups medium, dialogs/previews large.
   Number fields use themed chevron steppers (NE-038).
5. **Clear hierarchy between media / timeline / inspector areas.** Three-pane
   layout (media explorer · video column · inspector stack) over a full-width
   timeline; panes separated by `BORDER_SUBTLE` 1px lines, never heavy chrome.
6. **Restrained clinical trust cues.** Red (`DANGER`) is reserved for
   destructive and privacy-risk states only — never decoration, never SAM
   masks (enforced by test). Amber (`WARNING`) marks non-blocking cautions
   (unreviewed audio, missing markers). Emerald (`SUCCESS`) marks confirmed/
   export-ready states.
7. **Pastel timeline semantics in light mode.** Video, audio, color/markers,
   and narration/slides use watercolor blue, sage, ochre, and lilac lanes. Dark mode
   uses brighter versions of the same hues on charcoal.

## Token reference

| Semantic token | Role | Light value | Dark value |
|---|---|---|---|
| `SURFACE_SUNKEN` | app background | `#e6ecf2` | `#161819` |
| `SURFACE` | panels, timeline background | `#f5f8fb` | `#1c1f22` |
| `SURFACE_HEADER` | header, status bar, popovers | `#dde5ed` | `#22262a` |
| `SURFACE_RAISED` | buttons, inputs, cards | `#fbfcfe` | `#2a2e33` |
| `BG_HOVER` | hover fill | `#d3dfea` | `#33383e` |
| `BORDER_SUBTLE` / `BORDER_BRIGHT` | resting / engaged borders | `#c4d1dd` / `#93a7ba` | `#3a4047` / `#56606b` |
| `ACCENT_PRIMARY` (+`PRIMARY_HOVER`) | primary action, selection | `#33383e` / `#4a5058` | `#8fb4d8` / `#a6c4e2` |
| `ACCENT_CLINICAL` | SAM / stills / captions cues | `#2f6690` | `#7cc0dc` |
| `ACCENT_SLIDES` | slides track + panel accent | `#76588a` | `#b6a0dc` |
| `DANGER` | destructive / privacy risk only | `#9f2f24` | `#f26b6b` |
| `WARNING` | non-blocking caution | `#76500f` | `#f5b23d` |
| `SUCCESS` | confirmation / ready | `#276749` | `#3ccf93` |
| `SELECTION_OUTLINE` | timeline selected block + snap guide | `#2a6fb0` | `#FFD60A` |
| `VIDEO_CANVAS` | video viewer background | `#15171a` | `#000000` |
| `TEXT_PRIMARY` → `TEXT_DIM` | 4-step text ramp | `#25292e #4a525b #56606b #77818c` | `#e7eaee #b4bcc5 #9ba5b0 #78828d` |

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
  from the bundled static font files; Qt registers them at runtime, so no system
  font installation is required. Tracked in
  [ASSET_CHECKLIST.md](ASSET_CHECKLIST.md).

## Verification

- Automated: `python -m pytest tests/test_design_tokens.py` (contrast +
  red-reservation audit).
- Visual: `python scripts/capture_baseline_screenshots.py` before and after a
  token change; compare against [VISUAL_QA_CHECKLIST.md](VISUAL_QA_CHECKLIST.md).
