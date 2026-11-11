import base64
import io
import json
import math
import os
import tempfile
import unittest

from PIL import Image

from models.trocr_htr import TrOCRService
from models.board_ai_service import BoardAIService
from models.board_command_parser import extract_board_command
from training.trocr_iam import writer_disjoint_split, fit_temperature, ece, prepare_manifest


def data_url(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


class TrOCRServiceTests(unittest.TestCase):
    def test_missing_checkpoint_is_explicit(self):
        service = TrOCRService(checkpoint="/missing/trocr", calibration_path="/missing/calibration.json",
                               allow_baseline=False)
        self.assertFalse(service.status()["available"])
        self.assertEqual(service.status()["calibration"], "missing")
        with self.assertRaisesRegex(RuntimeError, "checkpoint"):
            service.recognize(data_url(Image.new("RGB", (20, 20), "black")))

    def test_empty_image_is_empty_not_a_phrase(self):
        service = TrOCRService(checkpoint="/missing/trocr")
        result = service.recognize(data_url(Image.new("RGB", (80, 30), "white")))
        self.assertTrue(result["is_empty"])
        self.assertEqual(result["transcription"], "")
        self.assertIsNone(result["confidence"])

    def test_transparent_empty_canvas_is_empty(self):
        service = TrOCRService(checkpoint="/missing/trocr")
        result = service.recognize(data_url(Image.new("RGBA", (80, 30), (0, 0, 0, 0))))
        self.assertTrue(result["is_empty"])

    def test_corrupt_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "corrupted"):
            TrOCRService.decode_image("data:image/png;base64,not-base64")

    def test_confidence_is_length_normalized_sequence_score(self):
        self.assertAlmostEqual(TrOCRService.calibrated_confidence(-0.5, 1.0), math.exp(-0.5))
        self.assertGreater(TrOCRService.calibrated_confidence(-0.5, 2.0),
                           TrOCRService.calibrated_confidence(-0.5, 1.0))

    def test_missing_calibration_and_low_confidence_require_confirmation(self):
        self.assertTrue(TrOCRService.requires_clarification(0.99, 0.72, False))
        self.assertTrue(TrOCRService.requires_clarification(0.2, 0.72, True))
        self.assertFalse(TrOCRService.requires_clarification(0.9, 0.72, True))

    def test_calibration_file_load_and_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "calibration.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"temperature": 1.6, "acceptance_threshold": 0.8}, stream)
            configured = TrOCRService(checkpoint="/missing", calibration_path=path)
            self.assertEqual(configured.calibration_status, "loaded")
            self.assertEqual(configured.threshold, 0.8)
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"temperature": -1}, stream)
            invalid = TrOCRService(checkpoint="/missing", calibration_path=path)
            self.assertEqual(invalid.calibration_status, "invalid")


class BoardAIServiceTests(unittest.TestCase):
    def test_typed_commands_are_labeled_as_fallback_when_offline(self):
        service = BoardAIService()
        service.api_key = ""
        result = service.generate_board_objects("@board create a flowchart for login")
        self.assertEqual(result.provider_status, "fallback")
        self.assertTrue(result.warnings)
        self.assertTrue(result.objects)
        self.assertEqual(len({item.id for item in result.objects}), len(result.objects))
        self.assertEqual(result.provider_status, "fallback")
        self.assertTrue(result.fallback_used)

    def test_selected_scope_spatial_context_is_formatted(self):
        service = BoardAIService()
        context = {"scope": "selected", "objects": [{"id": "n1", "type": "sticky_note",
                   "text": "keep this", "x": 10, "y": 20, "width": 200, "height": 100}]}
        result = service._format_board_context(context)
        self.assertIn('"id": "n1"', result)
        self.assertIn('"x": 10', result)
        self.assertIn("scope=selected", result)

    def test_invalid_connector_is_rejected_without_partial_output(self):
        service = BoardAIService()
        service.api_key = ""
        service._generate_fallback_response = lambda *_: {"summary": "bad", "objects": [
            {"id": "edge", "type": "arrow", "from_id": "missing", "to_id": "also_missing"}
        ]}
        with self.assertRaisesRegex(ValueError, "missing endpoint"):
            service.generate_board_objects("@board test")


class TrainingUtilityTests(unittest.TestCase):
    def test_iam_manifest_extraction_normalizes_word_delimiters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "iam")
            os.makedirs(os.path.join(root, "lines", "a01"))
            image_path = os.path.join(root, "lines", "a01", "a01-000u-00-00.png")
            Image.new("RGB", (20, 10), "white").save(image_path)
            with open(os.path.join(root, "lines.txt"), "w", encoding="utf-8") as stream:
                stream.write("# IAM line manifest\na01-000u-00-00 ok 154 1 2 3 4 0.0 Write|the|line\n")
            manifest = os.path.join(directory, "manifest.csv")
            self.assertEqual(prepare_manifest(root, manifest), 1)
            with open(manifest, newline="", encoding="utf-8") as stream:
                row = next(__import__("csv").DictReader(stream))
            self.assertEqual(row["writer_id"], "000u")
            self.assertEqual(row["text"], "Write the line")

    def test_writer_split_has_no_writer_overlap(self):
        rows = [{"writer_id": f"writer-{i}", "text": "line"} for i in range(30) for _ in range(2)]
        splits = writer_disjoint_split(rows, seed=7)
        writer_sets = {name: {row["writer_id"] for row in split} for name, split in splits.items()}
        self.assertFalse(writer_sets["train"] & writer_sets["validation"])
        self.assertFalse(writer_sets["train"] & writer_sets["test"])
        self.assertFalse(writer_sets["validation"] & writer_sets["test"])

    def test_validation_temperature_and_ece(self):
        temperature = fit_temperature([-0.05, -2.0, -0.1, -3.0], [1, 0, 1, 0])
        self.assertGreater(temperature, 0)
        self.assertAlmostEqual(ece([0.9, 0.1], [1, 0]), 0.1)


class BoardCommandParserTests(unittest.TestCase):
    def test_supported_ocr_trigger_variants(self):
        for text in ["@board draw a circuit", "@ board draw a circuit", "At Board draw a circuit"]:
            result = extract_board_command(text)
            self.assertTrue(result["command_detected"], text)
            self.assertEqual(result["command_text"], "draw a circuit")

    def test_incomplete_invocation_is_reported(self):
        result = extract_board_command("@board")
        self.assertTrue(result["command_detected"])
        self.assertTrue(result["instruction_missing"])

    def test_word_board_alone_is_not_a_trigger(self):
        result = extract_board_command("I wrote this on the board today")
        self.assertFalse(result["command_detected"])


if __name__ == "__main__":
    unittest.main()
