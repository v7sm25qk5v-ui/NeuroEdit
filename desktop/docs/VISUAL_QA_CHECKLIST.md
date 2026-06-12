# Visual Regression Checklist (plan P5.1)

Run before every release candidate and after any change to
`src/neuroedit_desktop/ui/styles.py`. Generate the screenshot set with:

```bash
cd desktop
python scripts/capture_baseline_screenshots.py        # offscreen, ~5 s
```

Compare the new capture folder against the previous baseline under
`desktop/qa/screenshots/` (gitignored — keep the last known-good set locally
or attach it to the release notes). On Windows, repeat the spot checks below
manually at 100% / 125% / 150% display scaling — offscreen capture cannot
reproduce fractional DPI.

For theme work, run one pass with View → Appearance → Light and one quick spot
pass with Dark and System. New installs should show the first-run appearance
chooser before the main window.

## Checklist

Per item: layout intact (no clipping/overlap), tokens applied (no stray
hard-coded colors), text readable, disabled/hover/pressed states visible.

| # | Surface | Capture file | Check |
|---|---|---|---|
| 1 | Full window 1440×900 | `window_1440x900.png` | three panes + timeline visible, no horizontal scrollbars at rest |
| 2 | Header rows 1–2 | `header.png` | both rows fit; tool buttons, swatches, label combo aligned; active panel tab shows its accent |
| 3 | Toolbar row wrapping | resize window to its 1085px minimum | header scrolls (never clips); panels keep full width |
| 4 | Primary/secondary/danger buttons | any panel | light primary = near-black/white, dark primary = brand blue/white; danger = red tint, never used for non-destructive actions; pressed state darkens |
| 5 | Right panels ×5 | `panel_sam/labels/tips/slides/audio.png` | no horizontal scrollbar; titles/muted text contrast OK |
| 6 | SAM missing-backend state | `panel_sam_missing_backend.png` | explainer replaces controls; Install/Download buttons present; **no auto-opened setup dialog** |
| 7 | Timeline states | `timeline.png` + manual | light lanes read as peach/sage/mauve/amber; dark keeps high-contrast lanes; selection outline, hover lift, snap guide, playhead smooth during playback |
| 8 | Project library rows | `dialog_project_library.png` | search field + sort combo present; green/red/gray row states; thumbnails or gray placeholder |
| 9 | Export dialog | `dialog_export.png` | "★ Recommended for this project" line; advanced collapsed by default; privacy checkbox checked |
| 10 | Export checklist | `dialog_export_checklist.png` | OK disabled until 3 required checks; amber audio note |
| 11 | Export history | `dialog_export_history.png` | rows show name/relative time/preset/folder; missing files grayed |
| 12 | PHI review stepper | `dialog_phi_review.png` | "Section N of M"; resumes at first unreviewed; ✓ reviewed suffix |
| 13 | Storage location dialog | `dialog_storage_location.png` | recommended option preselected; migration prompt appears when changing a non-empty root |
| 14 | SAM setup dialog | `dialog_sam_setup.png` | token field masked; opens only from Download Weights |
| 15 | Captions preview | manual (fixture project) | white text, dark box, safe-area margin; size/position controls apply |
| 16 | Export completion box | manual (run an export) | Reveal MP4 / Reveal Report buttons; report path listed |
| 17 | Empty/error states | empty project + fixture's missing clip | "No recent projects", "No projects match the search", missing-media warnings in red |

## Smoothness spot checks (fixture project)

Build once with `python scripts/make_smoothness_fixture.py --register`, then
with Help → Performance Diagnostics enabled:

- scrub the timeline and play through the 4K clip — no `over_budget=1` lines
  beyond isolated spikes in the diagnostics log,
- drag an annotation and a clip — `timeline_paint`/`canvas_paint` summaries
  stay under the 33 ms budget on average,
- switch all five panels, open the project library, start (and cancel) an
  export — no UI freeze at any point.
