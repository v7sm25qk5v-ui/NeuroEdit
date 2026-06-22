# Identity Asset Checklist (plan P2.3)

Tracks every brand/identity asset, where it comes from in Figma, and where it
lands. Goal: **no placeholder identity in the normal app path.** Update the
"Source Figma frame" column with exact frame names while exporting from the
[Figma Make concept](https://www.figma.com/make/EwIb4hEXiKH6uq5NipTXEr/Redesign-video-editing-app-UI?t=GISE85bHg74npOdT-6)
(Make files must be exported manually — the Figma API cannot read them).

Status legend: ✅ shipped · 🟡 pre-concept asset in place (replace with Figma
export) · 🔴 missing (code falls back to a placeholder).

| Asset | Source Figma frame | Export size | File path | Used on | Status |
|---|---|---|---|---|---|
| Header logo icon | Aperture mark (`design_handoff_logo`) | theme-matched SVG, rendered ~32px | `src/neuroedit_desktop/resources/neuroedit-mark-{light,dark}.svg` | in-app (macOS + Windows) | ✅ swaps line/accent with theme; falls back to "⬡" glyph if QtSvg absent |
| About dialog wordmark | Aperture mark + live text | SVG mark (~52px) + Space Grotesk 600 wordmark | `resources/neuroedit-mark-{light,dark}.svg` + Qt label | in-app (macOS + Windows) | ✅ live lockup; no raster wordmark |
| macOS app icon | Aperture app-icon tile (`design_handoff_logo`) | 1024×1024 → `.icns` | `resources/NeuroEdit.icns` (referenced by `NeuroEdit.spec` `BUNDLE`) | macOS bundle/DMG | ✅ shipped |
| Windows app icon | Aperture app-icon tile | 16–256 multi-res `.ico` | `resources/NeuroEdit.ico` (`NeuroEdit.spec` + `installer/NeuroEdit.iss`) | Windows exe + installer | ✅ shipped |
| Installer banner (Inno Setup) | _TBD_ | 164×314 BMP (`WizardImageFile`) | `desktop/installer/` | Windows installer | 🔴 Inno default |
| DMG background | _TBD_ | 600×400 PNG | build script | macOS DMG | 🔴 plain DMG |
| Release/README screenshots | capture script output | per-surface PNG | `desktop/qa/screenshots/` (gitignored; copy keepers to release notes) | GitHub releases | 🟡 regenerate after brand integration |
| Tutorial clip | n/a (screen recording) | 1080p MP4 | `src/neuroedit_desktop/resources/tutorial_clip.mp4` | in-app tutorial | 🟡 optional, falls back gracefully |

## Regenerating the identity assets

The aperture mark ships from the `design_handoff_logo` package. The source of
truth is the SVGs in `resources/neuroedit-*.svg`; the OS icon rasters are
regenerated from them.

1. Edit the SVGs (or re-export from the design package). The only token that
   tracks `styles.py` is the scalpel handle fill (`ACCENT_CLINICAL`).
2. Regenerate rasters with `scripts/generate_icons.py` (PySide6 + Pillow), then
   copy `build/NeuroEdit.icns`, `build/NeuroEdit.ico`, the `build/appicon/*` →
   `resources/icon_{16..512}.png`, and the iconset into `resources/`.
3. `NeuroEdit.spec` and `installer/NeuroEdit.iss` already point at
   `resources/NeuroEdit.icns` / `.ico`; rebuild both installers.
4. The header/About lockups render the SVGs directly via `QSvgRenderer`
   (`main_window._restyle_identity`) — no code change when the SVGs change.
