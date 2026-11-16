# Export decode benchmark — 2026-11-16

`QT_QPA_PLATFORM=offscreen QT_MEDIA_BACKEND=ffmpeg PYTHONPATH=src /private/tmp/neuroedit-release-20261115/runtime/bin/python scripts/benchmark_export_decode.py` (run from `desktop`). One run on macOS 27.0.1 arm64, OpenCV 4.13.0, with the bundled FFmpeg.

The script creates a temporary synthetic 1920 × 1080, 30 fps, six-second H.264 recording with a 180-frame GOP. It uses the same `testsrc2` source as the smoothness fixture, with a longer GOP. A redaction covering 20% of frame width and height is active throughout; the remainder exposes source-frame differences. Both complete exports use software libx264, veryfast, CRF 20. Times include rendering, per-frame SHA-256 hashing, encoding and publication; fixture generation is excluded.

| Decoder | Frames | Elapsed | Export fps |
| --- | ---: | ---: | ---: |
| Prior seek for each frame | 180 | 6.258 s | 28.76 |
| Current sequential path | 180 | 1.200 s | 150.00 |

All 180 rendered RGB frames matched exactly by SHA-256. The benchmark runs the same current renderer in both cases, substituting the prior seek-per-frame decoder; it does not compare separately encoded MP4 bytes. This single synthetic run is not a benchmark of real operative recordings or hardware encoding. No real long-GOP recording was available or used. Static-interval composition memoization from the ticket remains unimplemented.

Timing and frame-selection verification: `QT_QPA_PLATFORM=offscreen QT_MEDIA_BACKEND=ffmpeg PYTHONPATH=src /private/tmp/neuroedit-release-20261115/runtime/bin/python -m pytest tests/test_export_timing.py tests/test_export_frame_selection.py -q` — 41 passed in 7.86 s, clean exit. These include selected CFR and VFR samples; they do not establish correctness for every variable-frame-rate recording.

## Static composition measurement

`QT_QPA_PLATFORM=offscreen PYTHONPATH=src /private/tmp/neuroedit-release-20261115/runtime/bin/python scripts/benchmark_static_export.py` measures 180 warm 1080p calls to the full `_render_frame` path without encoding, compared with 180 copies of a pre-rendered RGB frame. On the same Mac, a synthetic image clip took 0.104 s to render versus 0.016 s for copies; a text slide took 0.125 s versus 0.016 s. The existing exporter already caches the decoded still and slide image. These figures imply a best-case saving of approximately 0.49 ms per image frame or 0.61 ms per slide frame, before any cache bookkeeping; they do not measure the speed of a real composition cache or an end-to-end export.

No composition cache was added: this small absolute saving does not justify cache invalidation and correctness complexity for changing captions, annotations, tracked masks, redactions, fades and clip or slide boundaries. The ticket's requested static composition memoization is therefore not implemented; the benchmark supports that decision for these two synthetic warm cases only, not for every slide, resolution or machine.
