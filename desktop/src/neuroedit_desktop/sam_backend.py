from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from neuroedit_desktop.models import SamPoint

ProgressFn = Callable[[str], None]
CancelFn = Callable[[], bool]
SamBackendStatus = Literal["missing", "ready", "unsupported"]


class SamCancelled(Exception):
    """Raised when a caller asks an in-flight propagation to stop (e.g. app quit)."""


@dataclass
class SamBackendInfo:
    status: SamBackendStatus
    device: str
    message: str


@dataclass
class SamSegmentResult:
    mask_path: Path
    score: float
    backend: str = "SAM"


@dataclass
class SamPropagationResult:
    mask_frames: list[dict[str, float | str]]
    score: float
    sample_rate: float
    backend: str = "SAM"


class SamBackend:
    SAM3_MODEL_ID = "facebook/sam3"
    SAM1_MODEL_ID = "facebook/sam-vit-base"
    SAM3_MAX_FRAMES_ENV = "NEUROEDIT_SAM3_MAX_FRAMES"

    def __init__(self) -> None:
        self._sam1_model: Any = None
        self._sam1_processor: Any = None
        self._sam3_tracker_model: Any = None
        self._sam3_tracker_processor: Any = None
        self._sam3_video_model: Any = None
        self._sam3_video_processor: Any = None
        self._device = "cpu"
        self._sam3_error: str | None = None

    def weights_cache_dir(self) -> Path:
        """Directory the SAM3 weights are cached in. Respects HF_HOME /
        HF_HUB_CACHE overrides so cache checks and deletion stay in sync with
        wherever huggingface_hub actually downloads to."""
        hub_cache = os.environ.get("HF_HUB_CACHE")
        if hub_cache:
            base = Path(hub_cache)
        else:
            base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
        return base / "models--facebook--sam3"

    def is_weights_cached(self) -> bool:
        snapshots = self.weights_cache_dir() / "snapshots"
        return snapshots.exists() and any(snapshots.iterdir())

    def login(self, token: str) -> None:
        from huggingface_hub import login
        login(token=token, add_to_git_credential=False)

    def probe(self) -> SamBackendInfo:
        try:
            import torch
            from transformers import (  # noqa: F401
                Sam3TrackerModel,
                Sam3TrackerProcessor,
                Sam3TrackerVideoModel,
                Sam3TrackerVideoProcessor,
                SamModel,
                SamProcessor,
            )
            import cv2  # noqa: F401
        except ImportError as exc:
            return SamBackendInfo("missing", "none", str(exc))

        device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        return SamBackendInfo(
            "ready",
            device,
            f"SAM3 tracker API ready on {device}. Model weights load on first use.",
        )

    def warmup(self, progress: ProgressFn | None = None) -> SamBackendInfo:
        info = self.probe()
        if info.status != "ready":
            return info
        try:
            self._report(progress, "Loading SAM3 video tracker weights...")
            self._ensure_sam3_video_model()
            return SamBackendInfo("ready", self._device, f"SAM3 tracker ready on {self._device}.")
        except Exception as exc:  # noqa: BLE001
            self._sam3_error = self._format_error(exc)
            return SamBackendInfo("missing", "none", f"SAM3 failed: {self._sam3_error}")

    def segment_frame(
        self,
        video_path: Path,
        time_s: float,
        points: list[SamPoint],
        mask_dir: Path,
        progress: ProgressFn | None = None,
        mask_color: tuple[int, int, int] | None = None,
    ) -> SamSegmentResult:
        if not points:
            raise ValueError("Place at least one SAM prompt point before running segmentation.")

        frame_rgb = self._grab_frame(video_path, time_s)
        h, w = frame_rgb.shape[:2]
        point_pixels = [(float(p.x) * w, float(p.y) * h) for p in points]
        labels = [1 if p.type == "positive" else 0 for p in points]

        try:
            self._report(progress, "Running SAM3 segmentation...")
            mask, score = self._run_sam3_on_frame(frame_rgb, point_pixels, labels)
            backend = "SAM3"
        except Exception as exc:  # noqa: BLE001
            self._sam3_error = self._format_error(exc)
            self._report(progress, f"SAM3 failed: {self._sam3_error}")
            self._report(progress, "Falling back to SAM1 segmentation...")
            mask, score = self._run_sam1_on_frame(frame_rgb, point_pixels, labels)
            backend = "SAM1 fallback"

        mask_dir.mkdir(parents=True, exist_ok=True)
        mask_path = mask_dir / (
            f"mask_{backend.lower().replace(' ', '_')}_{int(time_s * 1000):08d}_{uuid4().hex}.png"
        )
        self._save_mask_rgba(mask, (h, w), mask_path, color=mask_color)
        return SamSegmentResult(mask_path=mask_path, score=score, backend=backend)

    def propagate_video(
        self,
        video_path: Path,
        start_time_s: float,
        duration_s: float,
        points: list[SamPoint],
        mask_dir: Path,
        progress: ProgressFn | None = None,
        sample_rate: float = 2.0,
        cancelled: CancelFn | None = None,
        mask_color: tuple[int, int, int] | None = None,
    ) -> SamPropagationResult:
        if not points:
            raise ValueError("Place at least one SAM prompt point before running propagation.")
        mask_dir.mkdir(parents=True, exist_ok=True)
        run_id = uuid4().hex
        try:
            return self._propagate_video_sam3(
                video_path, start_time_s, duration_s, points, mask_dir,
                progress=progress, cancelled=cancelled, mask_color=mask_color, run_id=run_id,
            )
        except SamCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            self._sam3_error = self._format_error(exc)
            self._report(progress, f"SAM3 propagation failed: {self._sam3_error}")
            self._report(progress, "Falling back to SAM1 + optical flow propagation...")
            return self._propagate_video_sam1(
                video_path,
                start_time_s,
                duration_s,
                points,
                mask_dir,
                progress=progress,
                sample_rate=sample_rate,
                cancelled=cancelled,
                mask_color=mask_color,
                run_id=run_id,
            )

    def _ensure_sam3_tracker_model(self) -> tuple[Any, Any, str]:
        if self._sam3_tracker_model is not None:
            return self._sam3_tracker_model, self._sam3_tracker_processor, self._device
        from transformers import Sam3TrackerModel, Sam3TrackerProcessor

        device = self._select_device()
        dtype = self._select_dtype(device)
        model = Sam3TrackerModel.from_pretrained(self.SAM3_MODEL_ID).to(device, dtype=dtype)
        model.eval()
        processor = Sam3TrackerProcessor.from_pretrained(self.SAM3_MODEL_ID)
        self._sam3_tracker_model = model
        self._sam3_tracker_processor = processor
        self._device = device
        return model, processor, device

    def _ensure_sam3_video_model(self) -> tuple[Any, Any, str, Any]:
        if self._sam3_video_model is not None:
            return (
                self._sam3_video_model,
                self._sam3_video_processor,
                self._device,
                self._select_dtype(self._device),
            )
        from transformers import Sam3TrackerVideoModel, Sam3TrackerVideoProcessor

        device = self._select_device()
        dtype = self._select_dtype(device)
        model = Sam3TrackerVideoModel.from_pretrained(self.SAM3_MODEL_ID).to(device, dtype=dtype)
        model.eval()
        processor = Sam3TrackerVideoProcessor.from_pretrained(self.SAM3_MODEL_ID)
        self._sam3_video_model = model
        self._sam3_video_processor = processor
        self._device = device
        return model, processor, device, dtype

    def _ensure_sam1_model(self) -> tuple[Any, Any, str]:
        if self._sam1_model is not None:
            return self._sam1_model, self._sam1_processor, self._device
        from transformers import SamModel, SamProcessor

        device = self._select_device()
        model = SamModel.from_pretrained(self.SAM1_MODEL_ID).to(device)
        model.eval()
        processor = SamProcessor.from_pretrained(self.SAM1_MODEL_ID)
        self._sam1_model = model
        self._sam1_processor = processor
        self._device = device
        return model, processor, device

    def _run_sam3_on_frame(
        self,
        frame_rgb: Any,
        point_pixels: list[tuple[float, float]],
        labels: list[int],
    ) -> tuple[Any, float]:
        import torch
        from PIL import Image

        model, processor, device = self._ensure_sam3_tracker_model()
        inputs = processor(
            images=Image.fromarray(frame_rgb),
            input_points=[[[[float(x), float(y)] for x, y in point_pixels]]],
            input_labels=[[[int(label) for label in labels]]],
            return_tensors="pt",
        )
        model_inputs = self._model_inputs(model, inputs, device)
        with torch.no_grad():
            outputs = model(**model_inputs, multimask_output=False)
        masks = processor.post_process_masks(
            outputs.pred_masks.detach().cpu(),
            inputs["original_sizes"],
        )[0]
        return self._first_binary_mask(masks), self._score_from_outputs(outputs)

    def _run_sam1_on_frame(
        self,
        frame_rgb: Any,
        point_pixels: list[tuple[float, float]],
        labels: list[int],
    ) -> tuple[Any, float]:
        import numpy as np
        import torch
        from PIL import Image

        model, processor, device = self._ensure_sam1_model()
        inputs = processor(
            Image.fromarray(frame_rgb),
            input_points=[[[float(x), float(y)] for x, y in point_pixels]],
            input_labels=[[int(label) for label in labels]],
            return_tensors="pt",
        )
        model_inputs = self._model_inputs(model, inputs, device)
        with torch.no_grad():
            outputs = model(**model_inputs, multimask_output=True)
        masks = processor.image_processor.post_process_masks(
            outputs.pred_masks.detach().cpu(),
            inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu(),
        )
        scores = outputs.iou_scores.detach().cpu().float().numpy()[0][0]
        best_idx = int(scores.argmax())
        return masks[0][0, best_idx].numpy().astype(np.uint8), float(scores[best_idx])

    def _propagate_video_sam3(
        self,
        video_path: Path,
        start_time_s: float,
        duration_s: float,
        points: list[SamPoint],
        mask_dir: Path,
        progress: ProgressFn | None = None,
        cancelled: CancelFn | None = None,
        mask_color: tuple[int, int, int] | None = None,
        run_id: str = "",
    ) -> SamPropagationResult:
        import numpy as np
        import torch

        model, processor, device, dtype = self._ensure_sam3_video_model()
        self._report(progress, "Reading video frames for SAM3 session...")
        frames, times, effective_rate = self._load_video_window(video_path, start_time_s, duration_s)
        h, w = frames[0].shape[:2]
        point_pixels = [(float(p.x) * w, float(p.y) * h) for p in points]
        labels = [1 if p.type == "positive" else 0 for p in points]

        self._report(progress, f"Initializing SAM3 session ({len(frames)} frames)...")
        session = processor.init_video_session(
            video=frames,
            inference_device=device,
            processing_device="cpu",
            video_storage_device="cpu",
            dtype=dtype,
        )
        processor.add_inputs_to_inference_session(
            inference_session=session,
            frame_idx=0,
            obj_ids=1,
            input_points=[[[[float(x), float(y)] for x, y in point_pixels]]],
            input_labels=[[[int(label) for label in labels]]],
            clear_old_inputs=True,
        )

        mask_frames: list[dict[str, float | str]] = []
        scores: list[float] = []
        with torch.no_grad():
            outputs = model.propagate_in_video_iterator(
                session,
                start_frame_idx=0,
                max_frame_num_to_track=len(times),
            )
            for idx, output in enumerate(outputs, start=1):
                if cancelled is not None and cancelled():
                    raise SamCancelled()
                frame_idx = int(output.frame_idx)
                if frame_idx < 0 or frame_idx >= len(times):
                    continue
                if idx == 1 or idx % 10 == 0:
                    self._report(progress, f"SAM3 propagated frame {idx}/{len(times)}...")
                masks = processor.post_process_masks(
                    [output.pred_masks.detach().cpu()],
                    original_sizes=[[session.video_height, session.video_width]],
                    binarize=True,
                )[0]
                mask = self._first_binary_mask(masks)
                path = mask_dir / (
                    f"track_sam3_{int(start_time_s * 1000):08d}_{run_id}_{frame_idx:04d}.png"
                )
                self._save_mask_rgba(mask, (h, w), path, color=mask_color)
                score = self._score_from_outputs(output)
                mask_frames.append({"time": float(times[frame_idx]), "mask_path": str(path), "score": score})
                scores.append(score)
        if not mask_frames:
            raise RuntimeError("SAM3 did not produce propagated masks.")
        return SamPropagationResult(
            mask_frames=mask_frames,
            score=float(np.mean(scores)) if scores else 1.0,
            sample_rate=float(effective_rate),
            backend="SAM3",
        )

    def _propagate_video_sam1(
        self,
        video_path: Path,
        start_time_s: float,
        duration_s: float,
        points: list[SamPoint],
        mask_dir: Path,
        progress: ProgressFn | None = None,
        sample_rate: float = 2.0,
        cancelled: CancelFn | None = None,
        mask_color: tuple[int, int, int] | None = None,
        run_id: str = "",
    ) -> SamPropagationResult:
        import cv2
        import numpy as np

        self._ensure_sam1_model()
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")
        try:
            video_duration = self._video_duration(cap)
            end_time = min(start_time_s + max(0.0, duration_s), video_duration or start_time_s + duration_s)
            step = 1.0 / max(0.5, sample_rate)
            times = []
            t = start_time_s
            while t <= end_time + 1e-6:
                times.append(t)
                t += step
            first_frame = self._read_frame_from_capture(cap, times[0])
            if first_frame is None:
                raise RuntimeError("Failed to read seed frame from video.")
            h, w = first_frame.shape[:2]
            point_pixels = np.array([[float(p.x) * w, float(p.y) * h] for p in points], dtype=np.float32)
            labels = [1 if p.type == "positive" else 0 for p in points]
            prev_gray = cv2.cvtColor(first_frame, cv2.COLOR_RGB2GRAY)
            mask_frames: list[dict[str, float | str]] = []
            scores: list[float] = []
            for idx, frame_time in enumerate(times, start=1):
                if cancelled is not None and cancelled():
                    raise SamCancelled()
                self._report(progress, f"Propagating frame {idx}/{len(times)}...")
                if idx == 1:
                    frame_rgb = first_frame
                else:
                    frame_rgb = self._read_frame_from_capture(cap, frame_time)
                    if frame_rgb is None:
                        break
                    gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
                    next_points, status, _err = cv2.calcOpticalFlowPyrLK(
                        prev_gray,
                        gray,
                        point_pixels.reshape(-1, 1, 2),
                        None,
                    )
                    if next_points is not None and status is not None:
                        ok = status.reshape(-1).astype(bool)
                        point_pixels[ok] = next_points.reshape(-1, 2)[ok]
                    prev_gray = gray
                mask, score = self._run_sam1_on_frame(
                    frame_rgb,
                    [(float(x), float(y)) for x, y in point_pixels],
                    labels,
                )
                path = mask_dir / f"track_{int(start_time_s * 1000):08d}_{run_id}_{idx:04d}.png"
                self._save_mask_rgba(mask, frame_rgb.shape[:2], path, color=mask_color)
                mask_frames.append({"time": float(frame_time), "mask_path": str(path), "score": float(score)})
                scores.append(float(score))
            return SamPropagationResult(
                mask_frames=mask_frames,
                score=float(np.mean(scores)) if scores else 1.0,
                sample_rate=sample_rate,
                backend="SAM1 fallback",
            )
        finally:
            cap.release()

    def _load_video_window(self, video_path: Path, start_time_s: float, duration_s: float):
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            max_frames = max(1, int(os.environ.get(self.SAM3_MAX_FRAMES_ENV, "240")))
            end_time_s = start_time_s + max(0.0, duration_s)
            target_interval = max(1.0 / fps, (end_time_s - start_time_s) / max_frames)
            # Preserve actual presentation timestamps for VFR media. Average-FPS
            # frame indices drift from the source timeline and misalign masks.
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_time_s) * 1000.0)
            frames, times = [], []
            next_sample_s = start_time_s
            fallback_time_s = start_time_s
            while True:
                ok, frame_bgr = cap.read()
                if not ok or frame_bgr is None:
                    break
                frame_time_s = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
                if frame_time_s <= 0.0 and fallback_time_s > 0.0:
                    frame_time_s = fallback_time_s
                fallback_time_s = frame_time_s + 1.0 / fps
                if frame_time_s > end_time_s + 1e-6:
                    break
                if frame_time_s + 1e-6 < next_sample_s and frames:
                    continue
                frames.append(self._downscale_frame(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)))
                times.append(frame_time_s)
                next_sample_s = frame_time_s + target_interval
            if not frames:
                raise RuntimeError("Failed to read frames from video for SAM3 propagation.")
            if len(times) < 2:
                effective_rate = fps
            else:
                effective_rate = 1.0 / max(1e-6, (times[-1] - times[0]) / (len(times) - 1))
            return frames, times, effective_rate
        finally:
            cap.release()

    def _downscale_frame(self, frame_rgb: Any, max_side: int = 1920):
        """Cap the long side of a propagation frame. SAM3 resizes internally
        anyway, and holding 240 raw 4K frames in RAM (~6 GB) is what made
        propagation on 4K sources blow up; 1080p-class frames keep mask quality
        while cutting memory 4x."""
        import cv2

        h, w = frame_rgb.shape[:2]
        long_side = max(h, w)
        if long_side <= max_side:
            return frame_rgb
        scale = max_side / long_side
        return cv2.resize(
            frame_rgb,
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )

    def _model_inputs(self, model: Any, inputs: Any, device: str) -> dict[str, Any]:
        import inspect
        import torch

        params = set(inspect.signature(model.forward).parameters)
        result: dict[str, Any] = {}
        for key, value in inputs.items():
            if key not in params:
                continue
            if torch.is_tensor(value):
                if torch.is_floating_point(value):
                    value = value.to(dtype=torch.float32)
                value = value.to(device)
            result[key] = value
        return result

    def _grab_frame(self, video_path: Path, time_s: float):
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")
        try:
            frame = self._read_frame_from_capture(cap, time_s)
            if frame is None:
                raise RuntimeError("Failed to read frame from video.")
            return frame
        finally:
            cap.release()

    def _read_frame_from_capture(self, cap: Any, time_s: float):
        import cv2

        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_s) * 1000.0)
        ok, frame_bgr = cap.read()
        if not ok or frame_bgr is None:
            return None
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    def _video_duration(self, cap: Any) -> float:
        import cv2

        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        return frame_count / fps if fps > 0 else 0.0

    def _save_mask_rgba(
        self,
        mask: Any,
        frame_shape: tuple[int, int],
        mask_path: Path,
        color: tuple[int, int, int] | None = None,
    ) -> None:
        import cv2
        import numpy as np

        r, g, b = color or (34, 211, 238)
        h, w = frame_shape
        alpha = np.asarray(mask).astype(np.uint8) * 200
        if alpha.shape != (h, w):
            alpha = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_NEAREST)
        bgra = np.zeros((h, w, 4), dtype=np.uint8)
        bgra[..., 0] = b
        bgra[..., 1] = g
        bgra[..., 2] = r
        bgra[..., 3] = alpha
        if not cv2.imwrite(str(mask_path), bgra):
            raise RuntimeError(f"Failed to save mask PNG: {mask_path}")

    def _first_binary_mask(self, masks: Any) -> Any:
        import numpy as np
        import torch

        if torch.is_tensor(masks):
            arr = masks.detach().cpu().float().numpy()
        else:
            arr = np.asarray(masks)
        while arr.ndim > 2:
            arr = arr[0]
        return (arr > 0).astype(np.uint8)

    def _score_from_outputs(self, outputs: Any) -> float:
        import numpy as np
        import torch

        for attr in ("iou_scores", "pred_iou_scores", "object_scores", "scores"):
            value = getattr(outputs, attr, None)
            if value is None:
                continue
            arr = value.detach().cpu().float().numpy() if torch.is_tensor(value) else np.asarray(value)
            if arr.size:
                return float(np.nanmean(arr))
        return 1.0

    def _select_device(self) -> str:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _select_dtype(self, device: str):
        import torch

        return torch.bfloat16 if device == "cuda" else torch.float32

    def _format_error(self, exc: Exception) -> str:
        return str(exc).splitlines()[0] or exc.__class__.__name__

    def _report(self, progress: ProgressFn | None, message: str) -> None:
        if progress is not None:
            progress(message)
