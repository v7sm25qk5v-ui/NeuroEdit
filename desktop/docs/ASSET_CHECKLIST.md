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
| Header logo icon | _TBD (logo frame)_ | 64×64 PNG (rendered 32×32) | `src/neuroedit_desktop/resources/icon_64.png` | in-app (macOS + Windows) | 🟡 falls back to a gradient "⬡" glyph if absent |
| About dialog wordmark | _TBD (wordmark frame)_ | ≥560px wide PNG (rendered 280) | `src/neuroedit_desktop/resources/logo_wordmark.png` | in-app (macOS + Windows) | 🟡 falls back to plain text if absent |
| macOS app icon | _TBD (app icon frame)_ | 1024×1024 → `.icns` | `desktop/NeuroEdit.spec` (`BUNDLE` icon) | macOS bundle/DMG | 🔴 PyInstaller default |
| Windows app icon | _TBD (app icon frame)_ | 256×256 multi-res `.ico` | `desktop/NeuroEdit.spec` + `installer/NeuroEdit.iss` | Windows exe + installer | 🔴 PyInstaller/Inno default |
| Installer banner (Inno Setup) | _TBD_ | 164×314 BMP (`WizardImageFile`) | `desktop/installer/` | Windows installer | 🔴 Inno default |
| DMG background | _TBD_ | 600×400 PNG | build script | macOS DMG | 🔴 plain DMG |
| Release/README screenshots | capture script output | per-surface PNG | `desktop/qa/screenshots/` (gitignored; copy keepers to release notes) | GitHub releases | 🟡 regenerate after brand integration |
| Tutorial clip | n/a (screen recording) | 1080p MP4 | `src/neuroedit_desktop/resources/tutorial_clip.mp4` | in-app tutorial | 🟡 optional, falls back gracefully |

## Export procedure

1. Open the Make concept, export each frame at the size above (2× for raster
   assets that render on high-DPI displays).
2. Drop files into the listed path; the app picks up `icon_64.png` and
   `logo_wordmark.png` automatically (no code change).
3. Icons: regenerate `.icns`/`.ico`, reference them from `NeuroEdit.spec` and
   `NeuroEdit.iss`, and rebuild both installers.
4. Re-run `python scripts/capture_baseline_screenshots.py` and update this
   table's Status column + the release notes screenshots.
