"""Deprecated import shim for pre-TrOCR callers.

All handwriting recognition is handled by :mod:`trocr_htr`. This module no
longer calls an external handwriting API or assigns heuristic transcription
confidence. Stroke-only callers must rasterize their handwriting and provide
an image to the local TrOCR service.
"""
from .trocr_htr import TrOCRService


class CalibratedHTREngine(TrOCRService):
    def process_turn(self, strokes=None, image_base64=""):
        if not image_base64:
            raise RuntimeError("Stroke-only HTR is no longer supported; supply a raster image for local TrOCR.")
        result = self.recognize(image_base64)
        return {**result, "confidence": result["calibrated_confidence"]}

    def recognize_online_strokes(self, strokes, **kwargs):
        raise RuntimeError("External online handwriting recognition has been removed; use local TrOCR image inference.")
