"""Local TrOCR inference with explicit fine-tuned and pretrained model status."""
import base64
import io
import json
import math
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageStat


BASELINE_MODEL = "microsoft/trocr-small-handwritten"
BASELINE_LABEL = "PRETRAINED BASELINE — NOT ENCHANTED INK FINE-TUNED"


def _project_path(value: str) -> str:
    """Resolve configured relative paths from the repository root, not cwd."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return str(path.resolve())


class TrOCRService:
    def __init__(self, checkpoint: Optional[str] = None, calibration_path: Optional[str] = None,
                 threshold: Optional[float] = None, allow_baseline: Optional[bool] = None,
                 baseline_model: Optional[str] = None):
        configured_checkpoint = checkpoint if checkpoint is not None else os.getenv(
            "TROCR_CHECKPOINT", os.getenv("TROCR_MODEL_PATH", "./models/trocr-iam"))
        configured_calibration = calibration_path if calibration_path is not None else os.getenv(
            "TROCR_CALIBRATION", "./models/trocr-iam/calibration.json")
        self.checkpoint = _project_path(configured_checkpoint) if configured_checkpoint else ""
        self.calibration_path = _project_path(configured_calibration) if configured_calibration else ""
        self.baseline_model = baseline_model or os.getenv("TROCR_BASELINE_MODEL", BASELINE_MODEL)
        self.allow_baseline = (allow_baseline if allow_baseline is not None else
            os.getenv("TROCR_ALLOW_BASELINE_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"})
        self.device = os.getenv("TROCR_DEVICE", "cpu").strip() or "cpu"
        self.threshold = float(threshold if threshold is not None else os.getenv("HTR_ACCEPTANCE_THRESHOLD", "0.72"))
        self.temperature = 1.0
        self.calibration_status = "missing"
        self.model_source: Optional[str] = None
        self.model_name: Optional[str] = None
        self.model_label: Optional[str] = None
        self.load_error: Optional[str] = None
        self._initialized = False
        self._loading = False
        self._processor = None
        self._model = None
        self._load_lock = threading.Lock()
        self._load_calibration()

    @property
    def checkpoint_present(self) -> bool:
        if not self.checkpoint or not os.path.isdir(self.checkpoint):
            return False
        return self._has_model_weights(self.checkpoint) and os.path.isfile(os.path.join(self.checkpoint, "config.json"))

    @staticmethod
    def _has_model_weights(directory: str) -> bool:
        names = ("model.safetensors", "pytorch_model.bin", "model.safetensors.index.json",
                 "pytorch_model.bin.index.json")
        return any(os.path.isfile(os.path.join(directory, name)) for name in names)

    @property
    def available(self) -> bool:
        return self._model is not None and self._processor is not None

    def status(self) -> Dict[str, Any]:
        if self.model_source == "baseline":
            calibration = "not_applicable_baseline"
        else:
            calibration = self.calibration_status
        return {
            "available": self.available,
            "loaded": self.available,
            "loading": self._loading,
            "checkpoint": self.checkpoint or None,
            "checkpoint_present": self.checkpoint_present,
            "model_source": self.model_source,
            "model_name": self.model_name,
            "model_label": self.model_label,
            "device": self.device,
            "baseline_fallback_enabled": self.allow_baseline,
            "calibration": calibration,
            "calibrated": self.available and self.model_source == "fine_tuned" and self.calibration_status == "loaded",
            "acceptance_threshold": self.threshold,
            "error": self.load_error,
        }

    def _load_calibration(self) -> None:
        if not self.calibration_path or not os.path.isfile(self.calibration_path):
            return
        try:
            with open(self.calibration_path, encoding="utf-8") as f:
                config = json.load(f)
            temperature = float(config["temperature"])
            threshold = float(config.get("acceptance_threshold", self.threshold))
            if not math.isfinite(temperature) or temperature <= 0 or not 0 < threshold < 1:
                raise ValueError("invalid calibration values")
            self.temperature, self.threshold = temperature, threshold
            self.calibration_status = "loaded"
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.calibration_status = "invalid"

    def initialize(self, force_retry: bool = False) -> bool:
        """Load the local model first, then the configured Hub baseline if enabled."""
        if self.available and not force_retry:
            return True
        if self._initialized and not force_retry:
            return False
        with self._load_lock:
            if self.available and not force_retry:
                return True
            if self._initialized and not force_retry:
                return False
            self._initialized = True
            self._loading = True
            self._processor = self._model = None
            self.model_source = self.model_name = self.model_label = None
            errors = []
            try:
                import torch
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            except ImportError as exc:
                self.load_error = "HTR dependencies are missing. Install the CPU HTR requirements."
                self._loading = False
                return False

            candidates = []
            if self.checkpoint_present:
                candidates.append(("fine_tuned", self.checkpoint, "ENCHANTED INK FINE-TUNED CHECKPOINT"))
            else:
                errors.append(f"Fine-tuned checkpoint is missing or incomplete at {self.checkpoint}.")
            if self.allow_baseline and self.baseline_model:
                candidates.append(("baseline", self.baseline_model, BASELINE_LABEL))

            for source, model_id, label in candidates:
                try:
                    # Slow tokenizer avoids a protobuf-version conflict with the
                    # existing Gemini client dependency in this environment.
                    processor = TrOCRProcessor.from_pretrained(model_id, use_fast=False)
                    model = VisionEncoderDecoderModel.from_pretrained(model_id)
                    model.to(self.device).eval()
                    self._processor, self._model = processor, model
                    self.model_source = source
                    self.model_name = model_id
                    self.model_label = label
                    self.load_error = None
                    self._loading = False
                    return True
                except Exception as exc:
                    errors.append(f"Could not load {model_id}: {type(exc).__name__}: {exc}")

            self.load_error = " ".join(errors) or "No TrOCR model is configured."
            self._loading = False
            return False

    def _ensure_model(self, force_retry: bool = False) -> None:
        if not self.initialize(force_retry=force_retry):
            raise RuntimeError(self.load_error or "TrOCR model is unavailable")

    @staticmethod
    def decode_image(image_base64: str) -> Image.Image:
        encoded = image_base64.split(",", 1)[-1]
        if len(encoded) > 12_000_000:
            raise ValueError("Handwriting image exceeds the 9 MB limit")
        try:
            raw = base64.b64decode(encoded, validate=True)
            image = Image.open(io.BytesIO(raw))
            image.load()
        except Exception as exc:
            raise ValueError("Handwriting image is empty or corrupted") from exc
        if image.width * image.height > 16_000_000:
            raise ValueError("Handwriting image dimensions are too large")
        if "A" in image.getbands():
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            background.alpha_composite(rgba)
            image = background
        return image.convert("RGB")

    @staticmethod
    def is_blank(image: Image.Image) -> bool:
        gray = image.convert("L")
        stat = ImageStat.Stat(gray)
        return stat.mean[0] >= 250 and stat.stddev[0] < 3.0

    @staticmethod
    def calibrated_confidence(mean_log_probability: float, temperature: float) -> float:
        z = max(-60.0, min(0.0, mean_log_probability / temperature))
        return math.exp(z)

    @staticmethod
    def requires_clarification(confidence: Optional[float], threshold: float,
                               calibration_loaded: bool) -> bool:
        return not calibration_loaded or confidence is None or confidence < threshold

    def recognize(self, image_base64: str, force_retry: bool = False) -> Dict[str, Any]:
        image = self.decode_image(image_base64)
        if self.is_blank(image):
            return self._result("", None, "empty", False)
        self._ensure_model(force_retry=force_retry)
        try:
            import torch
            pixel_values = self._processor(images=image, return_tensors="pt").pixel_values.to(self.device)
            with torch.inference_mode():
                generated = self._model.generate(pixel_values, num_beams=1, max_new_tokens=128,
                                                  return_dict_in_generate=True, output_scores=True)
                sequence = generated.sequences[0]
                step_log_probs = []
                for index, logits in enumerate(generated.scores):
                    token_id = int(sequence[index + 1])
                    if token_id == self._processor.tokenizer.eos_token_id:
                        break
                    step_log_probs.append(float(torch.log_softmax(logits[0].float(), dim=-1)[token_id]))
                token_ids = sequence.tolist()
                text = self._processor.batch_decode([token_ids], skip_special_tokens=True)[0].strip()
            if not text or not step_log_probs:
                return self._result("", None, "empty", False)
            if len(text) > 1000:
                return self._result(text[:1000], None, "too_long", False)
            mean_logp = sum(step_log_probs) / len(step_log_probs)
            raw = math.exp(max(-60.0, mean_logp))
            calibrated_model = self.model_source == "fine_tuned" and self.calibration_status == "loaded"
            calibrated = self.calibrated_confidence(mean_logp, self.temperature) if calibrated_model else None
            clarification = self.requires_clarification(calibrated, self.threshold, calibrated_model)
            confidence_status = self.calibration_status if self.model_source == "fine_tuned" else "baseline_uncalibrated"
            return {"transcription": text, "raw_confidence": raw,
                    "calibrated_confidence": calibrated, "confidence": calibrated,
                    "confidence_status": confidence_status,
                    "sequence_log_probability": mean_logp, "token_count": len(step_log_probs),
                    "clarification_required": clarification,
                    "clarification_prompt": "Please confirm or correct the recognized handwriting.",
                    "is_empty": False, "error": None, "model_source": self.model_source,
                    "model_name": self.model_name, "model_label": self.model_label}
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"TrOCR inference failed: {exc}") from exc

    def _result(self, text: str, confidence: Optional[float], reason: str, clarify: bool) -> Dict[str, Any]:
        return {"transcription": text, "raw_confidence": confidence,
                "calibrated_confidence": confidence, "confidence": confidence,
                "confidence_status": "unavailable", "sequence_log_probability": None,
                "token_count": 0, "clarification_required": clarify,
                "clarification_prompt": "Please confirm or correct the recognized handwriting." if clarify else None,
                "is_empty": reason == "empty", "error": reason if reason != "empty" else None,
                "model_source": self.model_source, "model_name": self.model_name,
                "model_label": self.model_label}
