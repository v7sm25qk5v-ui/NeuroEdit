# Security fix ledger

Updated 2026-11-06. Scan `e6bbc1c2-5ecd-4306-a94e-4678895f4498`; canonical retained findings contained 39 occurrences. The scan stopped at a usage limit and is partial. These are local remediation tickets; scan artifacts remain unchanged and no workbench finding is closed. Severity shown is the canonical occurrence severity, preserved even when assessments differ. Source index is the zero-based position in the retained findings array.

All 11 tickets are **fixed and verified within the supplied static-project threat scope**. A fresh independent read-only review found no other concrete in-scope bypasses after the source-hardlink fix. The final complete desktop suite passed: 301 tests in 89.97 seconds, with no failures or skips. The original scan remains partial; its artifacts were not modified and no workbench finding was closed.

## 1. Fitted redaction coordinates
- Owner: Exporter engineer.
- Changed paths: `desktop/src/neuroedit_desktop/exporter.py`, `desktop/tests/test_redaction_export.py`.
- Acceptance: For portrait, square and 4:3 source fitted to an output, cover source-edge identifiers; verify matching-aspect export and non-redaction annotations.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 0 | `occ_ef8e29ef1e242ba11255b74d` | `csf_b16f2e2049f506b1cf44fa8b` | high |
| 28 | `occ_9114014efddfeea2f4ea99c8` | `csf_e26e6e2b3832795bfa0eef5b` | medium |

## 2. Linked masks cleanup
- Owner: Storage engineer.
- Changed paths: `desktop/src/neuroedit_desktop/ui/main_window_utils.py`, `desktop/tests/test_storage_security.py`.
- Acceptance: Close a project with a redirected masks directory without deleting outside files; preserve referenced current, saved, undo and redo masks and clean ordinary orphans.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 1 | `occ_6f8dfe9f6c3bdc06a4c150a1` | `csf_27d2350cd025e3edb9b71a18` | medium |
| 8 | `occ_247a4d2306d1654768d1e019` | `csf_7c64f27e3a10921e45144e99` | medium |
| 13 | `occ_14d21e7cd56c4abe9f16e240` | `csf_5eb329b535c7e7506f3b3b42` | medium |
| 16 | `occ_61a9a5e7e476e81c089dbd8b` | `csf_51e4ec9106a4cb486d9cb903` | medium |
| 20 | `occ_6fb2ffcfa5ec4d4d364b5d24` | `csf_db8ea6ca1dbf499937c05f98` | medium |
| 25 | `occ_d80e3d70fe77c73d5f2f9d19` | `csf_ce0443e4f83ee0d8d7ebfac5` | medium |
| 34 | `occ_7c394845460fd1775c36e70f` | `csf_166afa4c3cc5da03eb811111` | medium |
| 36 | `occ_8f3952ec59207b2fed831691` | `csf_e4db1bc0f259aa72ef8fe141` | medium |

## 3. Managed Save As containment and private-source copying
- Owner: Storage engineer.
- Changed paths: `desktop/src/neuroedit_desktop/project_store.py`, `desktop/src/neuroedit_desktop/ui/main_window.py`, `desktop/tests/test_storage_security.py`.
- Acceptance: Reject parent traversal and redirected source or destination paths, including private-source and outside overwrite cases; copy managed assets and preserve linked external references, missing paths and safe same-file aliases.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 2 | `occ_5384153c513204f7a0f29af3` | `csf_d35c9013daee6075cbb246d5` | medium |
| 9 | `occ_c2bf67532cd332bea1249e08` | `csf_653e4b15c2b1e8d8ade38326` | medium |
| 11 | `occ_f53a2fdb1fa0b6923a3f2504` | `csf_b0f86b48b4b048ac5b3243ed` | low |
| 14 | `occ_72b1863ec04bab777e678f0f` | `csf_1847e77ec53e276739d14f9f` | medium |
| 17 | `occ_7503e74443a71bafbc4b83f8` | `csf_6929fe40e8f845a62b8630ab` | medium |
| 19 | `occ_4c92651363e667da2b1e7da9` | `csf_5eaf594c80ea7fa21caf953a` | medium |
| 21 | `occ_883aae0add481f1d434c7706` | `csf_b8bebabab348a9ac13295b04` | medium |
| 23 | `occ_a9cada27302e73bae126de47` | `csf_2d2173b1970f44ed69812c08` | medium |
| 26 | `occ_d0ffa8a02e7f81299ac811b9` | `csf_437951b89b91ba2d745dadf3` | medium |
| 37 | `occ_5b973ace0bc14693f31bd924` | `csf_377b3a1c7a77a77c3c623b58` | medium |

## 4. Predictable save temporary symlink
- Owner: Storage engineer.
- Changed paths: `desktop/src/neuroedit_desktop/project_store.py`, `desktop/tests/test_storage_security.py`.
- Acceptance: A planted project.json.tmp link cannot truncate its target; normal save and reopen succeeds, including autosave save_data.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 27 | `occ_10d80fa6c1cff5a13dc65bb1` | `csf_217363ba0619aee8baaa93fc` | medium |

## 5. Raw library derivative
- Owner: UI engineer.
- Changed paths: `desktop/src/neuroedit_desktop/ui/project_library.py`, `desktop/tests/test_security_ui.py`, `desktop/tests/test_project_library.py`.
- Acceptance: Reviewed footage with a redacted identifier never produces/displays raw frame cache; stale caches are handled and library metadata/placeholders remain usable.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 3 | `occ_f335a4600d9a4cb501fa7c12` | `csf_f488215c30304324360de35e` | low |
| 10 | `occ_37c3ef07135a825f3de1a9d9` | `csf_6af024498d2bcba2e1af3b8d` | low |
| 12 | `occ_fe1c362e5d2239cf8bfe7e81` | `csf_36115554bad572d5d419551d` | low |
| 15 | `occ_352b0c28eb6822167cda788c` | `csf_34b5e11c3b17b2c218314c45` | low |
| 18 | `occ_3a3a37d93ac90676467c8dcd` | `csf_4cfe5008ded65c9eb8e83fa1` | low |
| 22 | `occ_2ad480612cd79805cf902375` | `csf_95c97dbd316671e9b112ce87` | low |
| 24 | `occ_111fd0ea78db350a1a67c387` | `csf_0ad438f308e0956954af21ca` | low |
| 30 | `occ_2c53f237a0984d1b24c20735` | `csf_d7e54594bf3fe4dabe403a28` | medium |
| 35 | `occ_c0d18ff65fa32ae6773badac` | `csf_77282b0c416ef1741956de72` | low |
| 38 | `occ_641a013c5a0c23615b7cd478` | `csf_d12f28503f6c1d30951a919d` | low |

## 6. Take Still coverage
- Owner: UI engineer.
- Changed paths: `desktop/src/neuroedit_desktop/ui/main_window.py`, `desktop/tests/test_security_ui.py`.
- Acceptance: Insert still through finite and infinite redaction spans and keep resumed footage covered; verify unaffected timing and ordinary still insertion.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 4 | `occ_80b33e509c8f2a3e5db17a98` | `csf_7cff18a10a1d5f1579287a6b` | medium |

## 7. Inclusive fast export endpoint
- Owner: Exporter engineer.
- Changed paths: `desktop/src/neuroedit_desktop/exporter.py`, `desktop/tests/test_export_timing.py`.
- Acceptance: Final frame exactly at finite redaction endpoint stays covered on fast export; verify before/after frames and normal timing.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 7 | `occ_09c7fe1c333a9cc42e162318` | `csf_c1fd99d921d572ded2efabbb` | low |
| 29 | `occ_a39a9f8b58cd7bbc60ff3b62` | `csf_96817ac11fdbfd2eae0c46e2` | medium |

## 8. Source stream metadata
- Owner: Exporter engineer.
- Changed paths: `desktop/src/neuroedit_desktop/exporter.py`, `desktop/tests/test_export_timing.py`.
- Acceptance: Remove source stream as well as container tags on fast export; verify valid output and intended metadata behavior.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 6 | `occ_916e81790426cf4040876372` | `csf_468483cd35505b6ba2fbd163` | medium |
| 32 | `occ_c712fe71e3e1d2e59bd3ec92` | `csf_fbc3b2f287abaa48caa2bb88` | medium |

## 9. Passive load timeline compaction
- Owner: Lead engineer.
- Changed paths: `desktop/src/neuroedit_desktop/ui/editor_panels.py`, `desktop/tests/test_security_ui.py`.
- Acceptance: Load a reviewed gapped project without moving clips away from their redactions or retaining stale approval after an effective review change; preserve legitimate project load and editing.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 33 | `occ_b942d48e9b2c326a8dc2723a` | `csf_121acf765958707d243d7715` | low |

## 10. Thumbnail URL request
- Owner: UI engineer.
- Changed paths: `desktop/src/neuroedit_desktop/ui/project_library.py`, `desktop/tests/test_security_ui.py`.
- Acceptance: HTTP and other untrusted URL source paths cause no thumbnail network request; missing sources remain represented and the library opens.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 31 | `occ_c6720ad50b567093d3b56614` | `csf_d25cd3fbbe93ae5e45f3e4ba` | low |

## 11. Timeline duration denial of service
- Owner: UI engineer.
- Changed paths: `desktop/src/neuroedit_desktop/models.py`, `desktop/src/neuroedit_desktop/ui/editor_panels.py`, `desktop/src/neuroedit_desktop/ui/project_library.py`, `desktop/tests/test_security_ui.py`.
- Acceptance: Load extreme duration input with bounded rendering work and no UI freeze; ordinary timeline ticks and navigation remain usable.
- Verification: fixed within the static-project scope; the trigger and legitimate control above passed in the focused and complete test runs.

| Source index | Occurrence ID | Finding ID | Severity |
|---:|---|---|---|
| 5 | `occ_e8a03aefb062d75ed88b47c8` | `csf_8c181ca416570a97d76df28c` | low |

## Focused verification recorded

Storage: `cd desktop && QT_QPA_PLATFORM=offscreen PYTHONPATH=src /private/tmp/neuroedit-security-20261106/bin/python -m pytest -q tests/test_storage_security.py tests/test_project_lifecycle_review.py tests/test_undo_history.py tests/test_sam_workflow.py` — 64 passed. Syntax compilation passed for the affected storage modules and tests; Ruff passed for `project_store.py`, `main_window_utils.py`, and `test_storage_security.py`. The complete run and independent review subsequently passed within the stated scope.

## Current evidence and limits

- Export focused checks: 55 passed with bundled arm64 FFmpeg, including encoded endpoint, metadata with and without audio, direct concat and mux, mixed-aspect controls, and shared frame-clock correction.
- Source hardlink copying had a failing reproducer before the candidate fix; 18 controls, including safe same-file aliases, passed afterward. Managed-directory junction checks have a simulated test; actual Windows has not been tested.
- Full suite: `cd desktop && PATH=/private/tmp/neuroedit-security-bin:$PATH QT_QPA_PLATFORM=offscreen PYTHONPATH=src /private/tmp/neuroedit-security-20261106/bin/python -m pytest -q --disable-warnings -o faulthandler_timeout=120` — 301 passed in 89.97 seconds, no failures or skips. An earlier wrong-architecture `/usr/local/bin/ffmpeg` failure was environmental; the corrected rerun passed.
- The imported-static-project threat does not establish protection against concurrent hostile filesystem mutation; migration is not guaranteed race-free. Where directory descriptors or `O_NOFOLLOW` are unavailable, orphan cleanup skips deletion, including on Windows, so stale orphans may remain.
- The original scan is partial. No new audit or workbench closure has been performed.

- Global checks passed: `/private/tmp/neuroedit-security-20261106/bin/python -m ruff check src tests scripts`, `/private/tmp/neuroedit-security-20261106/bin/python -m compileall -q src` (both from `desktop`), and `git diff --check`.
- One earlier full-suite attempt was terminated after a stale offscreen tutorial modal blocked it. A native Qt sample confirmed the deferred callback could open `QDialog.exec`; the headless window fixture in `desktop/tests/test_main_window_headless.py` now suppresses that callback before construction to prevent it outliving restored settings. Production behavior was unchanged; the corrected full rerun passed.
- Independent review: a source-hardlink bypass was reproduced before the fix and fixed while retaining same-file alias controls. A zero-frame hypothesis was withdrawn after checking the caller’s `stop > first` guard. No other concrete in-scope bypass was identified.
