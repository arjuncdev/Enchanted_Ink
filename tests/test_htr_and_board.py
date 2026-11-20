import base64
import io
import json
import math
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from models.trocr_htr import TrOCRService
from models.board_ai_service import BoardAIService, WhiteboardObject
from models.board_command_parser import extract_board_command
from models.ai_provider import AIProviderSettings, OllamaService, ai_provider_settings, ollama_service
from training.trocr_iam import (
    writer_disjoint_split, line_random_split, fit_temperature, ece, prepare_manifest,
    prepare_forms_manifest, repair_form_manifest_writer_ids, train,
)


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

    def test_request_waits_for_background_model_initialization(self):
        service = TrOCRService(checkpoint="/missing/trocr", allow_baseline=False)
        service._initialized = True
        service._loading = True
        service._load_lock.acquire()
        model = object()
        processor = object()
        started = threading.Event()
        results = []

        def wait_for_model():
            started.set()
            results.append(service.initialize())

        worker = threading.Thread(target=wait_for_model)
        worker.start()
        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(worker.is_alive())
        service._model = model
        service._processor = processor
        service._loading = False
        service._load_lock.release()
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [True])

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

    def test_finetuned_inference_uses_shared_handwriting_preprocessing(self):
        import torch

        processed_image = Image.new("RGB", (160, 80), "white")

        class FakeProcessor:
            class Tokenizer:
                eos_token_id = 2

            tokenizer = Tokenizer()

            def __call__(self, images, return_tensors):
                self.images = images
                return SimpleNamespace(pixel_values=torch.zeros((len(images), 3, 32, 32)))

            def batch_decode(self, sequences, skip_special_tokens):
                return ["recognized writing"]

        class FakeModel:
            def generate(self, pixel_values, **kwargs):
                return SimpleNamespace(
                    sequences=torch.tensor([[0, 1, 2]]),
                    scores=(torch.tensor([[0.0, 2.0, -2.0]]),),
                    beam_indices=torch.tensor([[0, 0, -1]]),
                )

            def compute_transition_scores(self, sequences, scores, beam_indices,
                                         normalize_logits):
                return torch.tensor([[-0.1, -0.2]])

        service = TrOCRService(checkpoint="/missing", allow_baseline=False)
        processor = FakeProcessor()
        service._processor = processor
        service._model = FakeModel()
        service.model_source = "fine_tuned"
        image = Image.new("RGB", (80, 40), "white")
        image.putpixel((20, 20), (0, 0, 0))
        with patch("models.htr_utils.prep_line_image", return_value=processed_image) as preprocess:
            result = service.recognize(data_url(image))
        preprocess.assert_called_once()
        self.assertEqual(len(processor.images), 1)
        self.assertIs(processor.images[0], processed_image)
        self.assertEqual(result["transcription"], "recognized writing")

    def test_multiline_handwriting_is_split_and_transcribed_in_reading_order(self):
        import torch

        class FakeProcessor:
            class Tokenizer:
                eos_token_id = 2

            tokenizer = Tokenizer()

            def __call__(self, images, return_tensors):
                self.images = images
                return SimpleNamespace(pixel_values=torch.zeros((len(images), 3, 32, 32)))

            def batch_decode(self, sequences, skip_special_tokens):
                return ["first line", "second line"]

        class FakeModel:
            def generate(self, pixel_values, **kwargs):
                batch_size = pixel_values.shape[0]
                sequences = torch.tensor([[0, 1, 2]] * batch_size)
                logits = torch.tensor([[0.0, 2.0, -2.0]] * batch_size)
                return SimpleNamespace(
                    sequences=sequences,
                    scores=(logits, logits),
                    beam_indices=torch.tensor([[0, 0, -1]] * batch_size),
                )

            def compute_transition_scores(self, sequences, scores, beam_indices,
                                         normalize_logits):
                return torch.tensor([[-0.1, -0.2]] * len(sequences))

        image = Image.new("RGB", (240, 100), "white")
        for top in (15, 60):
            for y in range(top, top + 8):
                for x in range(20, 220):
                    image.putpixel((x, y), (25, 25, 25))

        service = TrOCRService(checkpoint="/missing", allow_baseline=False)
        service._processor = FakeProcessor()
        service._model = FakeModel()
        service.model_source = "baseline"
        with patch("models.htr_utils.prep_line_image", side_effect=lambda line: line) as preprocess:
            result = service.recognize(data_url(image))

        self.assertEqual(result["transcription"], "first line\nsecond line")
        self.assertEqual(len(service._processor.images), 2)
        self.assertEqual(preprocess.call_count, 2)

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


class OllamaServiceTests(unittest.TestCase):
    def test_chat_uses_local_non_streaming_api_and_json_mode(self):
        response = Mock(status_code=200)
        response.json.return_value = {"message": {"content": "Local answer"}}
        service = OllamaService(AIProviderSettings())
        with patch("models.ai_provider.requests.post", return_value=response) as post:
            answer = service.chat([{"role": "user", "content": "Hello"}], response_format="json")
        self.assertEqual(answer, "Local answer")
        self.assertEqual(post.call_args.args[0], "http://localhost:11434/api/chat")
        self.assertFalse(post.call_args.kwargs["json"]["stream"])
        self.assertEqual(post.call_args.kwargs["json"]["format"], "json")

    def test_status_checks_server_and_selected_model(self):
        response = Mock(status_code=200)
        response.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
        service = OllamaService(AIProviderSettings())
        with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen2.5:7b"}), \
             patch("models.ai_provider.requests.get", return_value=response):
            status = service.status()
        self.assertTrue(status["available"])
        self.assertTrue(status["model_available"])

    def test_provider_settings_are_persisted_without_changing_other_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = os.path.join(directory, ".env")
            with open(env_path, "w", encoding="utf-8") as stream:
                stream.write("GEMINI_API_KEY=keep-this-value\n")
            settings = AIProviderSettings()
            with patch("models.ai_provider.ENV_PATH", env_path), \
                 patch.dict(os.environ, {}, clear=False):
                self.assertTrue(settings.configure(
                    "ollama", "http://localhost:11434/", "qwen2.5:7b"))
                with open(env_path, encoding="utf-8") as stream:
                    saved = stream.read()
                self.assertIn("GEMINI_API_KEY=keep-this-value", saved)
                self.assertIn("AI_PROVIDER='ollama'", saved)
                self.assertEqual(os.environ["OLLAMA_BASE_URL"], "http://localhost:11434")

    def test_provider_settings_reject_invalid_ollama_url(self):
        with self.assertRaisesRegex(ValueError, "Ollama URL"):
            AIProviderSettings().configure(
                "ollama", "http://localhost:11434/api", "qwen2.5:7b")


class BoardAIServiceTests(unittest.TestCase):
    def test_board_command_uses_ollama_and_labels_local_provider(self):
        response = json.dumps({"summary": "Solar energy", "objects": [{
            "id": "solar", "type": "text", "x": 0, "y": 0,
            "width": 220, "height": 50, "text": "Solar energy"
        }]})
        service = BoardAIService()
        with patch.dict(os.environ, {"AI_PROVIDER": "ollama", "OLLAMA_MODEL": "qwen2.5:7b"}), \
             patch.object(ollama_service, "chat", return_value=response) as chat:
            result = service.generate_board_objects("@board create a note about solar energy")
        self.assertEqual(result.provider_status, "ollama")
        self.assertEqual(result.provider, "Ollama (local)")
        self.assertEqual(result.model, "qwen2.5:7b")
        self.assertFalse(result.fallback_used)
        self.assertEqual(chat.call_args.kwargs["response_format"], "json")
        self.assertEqual(len(result.objects), 1)

    def test_cat_drawing_uses_direct_editable_illustration(self):
        service = BoardAIService()
        service.api_key = "test-key"
        with patch.object(service, "_call_gemini") as gemini:
            result = service.generate_board_objects("@board draw a cat")
        gemini.assert_not_called()
        self.assertEqual(result.provider_status, "local")
        self.assertEqual(result.provider, "Built-in illustration")
        self.assertFalse(result.fallback_used)
        self.assertIn("cat illustration", result.summary.lower())
        self.assertGreaterEqual(len(result.objects), 8)
        self.assertIn("ellipse", {item.type for item in result.objects})
        self.assertIn("▲", {item.text for item in result.objects})
        self.assertIn("cat_head", {item.id for item in result.objects})

    def test_board_generation_retries_secondary_gemini_model(self):
        service = BoardAIService()
        service.api_key = "test-key"
        service.model_name = "gemini-primary"
        service.fallback_model = "gemini-backup"
        primary_error = Mock(status_code=503)
        primary_error.json.return_value = {"error": {"message": "temporarily unavailable"}}
        backup_response = Mock(status_code=200)
        backup_response.json.return_value = {"candidates": [{"content": {"parts": [{
            "text": json.dumps({"summary": "A visible test label", "objects": [{
                "id": "label", "type": "text", "x": 0, "y": 0,
                "width": 180, "height": 40, "text": "External model worked"
            }]})
        }]}}]}
        with patch("models.board_ai_service.requests.post", side_effect=[primary_error, backup_response]) as post:
            result = service.generate_board_objects("@board create a label saying External model worked")
        self.assertEqual(result.provider_status, "gemini")
        self.assertEqual(result.model, "gemini-backup")
        self.assertFalse(result.fallback_used)
        self.assertEqual(len(result.objects), 1)
        self.assertEqual(post.call_count, 2)
        self.assertIn("/v1beta/interactions", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gemini-backup")
        self.assertEqual(post.call_args.kwargs["json"]["response_format"]["mime_type"], "application/json")

    def test_transparent_generated_colors_are_normalized_for_canvas(self):
        item = WhiteboardObject(type="text", stroke="transparent", fill="transparent")
        self.assertIsNone(item.stroke)
        self.assertIsNone(item.fill)

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

    def test_connector_geometry_is_derived_from_endpoints_not_model_dimensions(self):
        service = BoardAIService()
        service.api_key = ""
        service._generate_fallback_response = lambda *_: {"summary": "connected nodes", "objects": [
            {"id": "source", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 80,
             "text": "source"},
            {"id": "target", "type": "rectangle", "x": 200, "y": 0, "width": 100, "height": 80,
             "text": "target"},
            {"id": "edge", "type": "arrow", "from_id": "source", "to_id": "target",
             "x": 200, "y": 0, "width": -200, "height": -4},
        ]}
        result = service.generate_board_objects(
            "@board connect the source to the target",
            insertion_point={"x": 100, "y": 200},
        )
        arrow = next(item for item in result.objects if item.id == "edge")
        self.assertEqual((arrow.x, arrow.y, arrow.width, arrow.height), (150, 240, 200, 0))


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

    def test_kaggle_line_manifest_parses_labels_without_inventing_writer_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "kaggle")
            image_dir = os.path.join(root, "self_lines")
            os.makedirs(image_dir)
            image_path = os.path.join(image_dir, "selfMade_0.png")
            Image.new("RGB", (20, 10), "white").save(image_path)
            with open(os.path.join(root, "lines.txt"), "w", encoding="utf-8") as stream:
                stream.write(
                    "selfMade_0 x x x x x x x x Machine|Learning|example\n"
                )
            manifest = os.path.join(directory, "manifest.csv")
            self.assertEqual(prepare_manifest(root, manifest), 1)
            with open(manifest, newline="", encoding="utf-8") as stream:
                row = next(__import__("csv").DictReader(stream))
            self.assertEqual(row["text"], "Machine Learning example")
            self.assertEqual(row["writer_id"], "unknown")
            self.assertEqual(row["image_path"], image_path)

    def test_prepare_reports_missing_local_iam_path_and_colab_path(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_root = os.path.join(directory, "content", "iam")
            with self.assertRaisesRegex(FileNotFoundError, "Google Colab"):
                prepare_manifest(missing_root, os.path.join(directory, "manifest.csv"))

    def test_prepare_forms_crops_handwriting_and_marks_alignment_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "forms", "data", "000")
            output = os.path.join(directory, "line-crops")
            os.makedirs(root)
            image_path = os.path.join(root, "a01-000u.png")
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            from PIL import ImageDraw, ImageFont
            font = ImageFont.truetype(font_path, 38)
            image = Image.new("RGB", (1400, 1800), "white")
            draw = ImageDraw.Draw(image)
            draw.text((180, 180), "Printed reference paragraph.", font=font, fill="black")
            draw.line((150, 330, 1250, 330), fill="black", width=3)
            draw.text((180, 430), "Handwritten first line.", font=font, fill="black")
            draw.text((180, 610), "Handwritten second line.", font=font, fill="black")
            draw.line((150, 1350, 1250, 1350), fill="black", width=3)
            draw.text((180, 1380), "Name: writer signature", font=font, fill="black")
            image.save(image_path)
            manifest = os.path.join(output, "forms.csv")
            ocr_result = Mock(returncode=0, stdout=b"Handwritten first line. Second line.",
                              stderr=b"")
            with patch("training.trocr_iam.subprocess.run", return_value=ocr_result):
                count = prepare_forms_manifest(
                    os.path.join(directory, "forms"), output, manifest, limit=1)
            self.assertEqual(count, 2)
            with open(manifest, newline="", encoding="utf-8") as stream:
                rows = list(__import__("csv").DictReader(stream))
            self.assertEqual([row["writer_id"] for row in rows], ["000u", "000u"])
            self.assertTrue(all(row["alignment_review_required"] == "true" for row in rows))
            self.assertTrue(all(os.path.isfile(row["image_path"]) for row in rows))

    def test_repair_form_manifest_corrects_writer_ids_in_new_output(self):
        with tempfile.TemporaryDirectory() as directory:
            original = os.path.join(directory, "forms.csv")
            corrected = os.path.join(directory, "forms-corrected.csv")
            with open(original, "w", newline="", encoding="utf-8") as stream:
                writer = __import__("csv").DictWriter(
                    stream, fieldnames=["source_form", "writer_id", "text"])
                writer.writeheader()
                writer.writerow({"source_form": "a01-000u.png", "writer_id": "a01", "text": "words"})
            self.assertEqual(repair_form_manifest_writer_ids(original, corrected), 1)
            with open(corrected, newline="", encoding="utf-8") as stream:
                row = next(__import__("csv").DictReader(stream))
            self.assertEqual(row["writer_id"], "000u")
            with open(original, newline="", encoding="utf-8") as stream:
                original_row = next(__import__("csv").DictReader(stream))
            self.assertEqual(original_row["writer_id"], "a01")

    def test_train_stops_with_clear_error_when_manifest_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "Run the prepare command"):
                train(Mock(manifest=os.path.join(directory, "missing.csv")))

    def test_train_refuses_unreviewed_form_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = os.path.join(directory, "forms.csv")
            with open(manifest, "w", newline="", encoding="utf-8") as stream:
                writer = __import__("csv").DictWriter(
                    stream, fieldnames=["image_path", "text", "writer_id",
                                        "alignment_review_required"])
                writer.writeheader()
                writer.writerow({"image_path": "/unused.png", "text": "test",
                                 "writer_id": "a01", "alignment_review_required": "true"})
            with self.assertRaisesRegex(ValueError, "still require transcript review"):
                train(Mock(manifest=manifest))

    def test_writerless_manifest_requires_explicit_line_split(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = os.path.join(directory, "line.png")
            Image.new("RGB", (20, 10), "white").save(image_path)
            manifest = os.path.join(directory, "lines.csv")
            with open(manifest, "w", newline="", encoding="utf-8") as stream:
                writer = __import__("csv").DictWriter(
                    stream, fieldnames=["image_path", "text", "writer_id"])
                writer.writeheader()
                for index in range(10):
                    writer.writerow({"image_path": image_path, "text": f"line {index}",
                                     "writer_id": "unknown"})
            args = Mock(manifest=manifest, max_text_chars=1000, seed=42,
                        allow_line_split=False)
            with self.assertRaisesRegex(ValueError, "--allow-line-split"):
                train(args)

    def test_writer_split_has_no_writer_overlap(self):
        rows = [{"writer_id": f"writer-{i}", "text": "line"} for i in range(30) for _ in range(2)]
        splits = writer_disjoint_split(rows, seed=7)
        writer_sets = {name: {row["writer_id"] for row in split} for name, split in splits.items()}
        self.assertFalse(writer_sets["train"] & writer_sets["validation"])
        self.assertFalse(writer_sets["train"] & writer_sets["test"])
        self.assertFalse(writer_sets["validation"] & writer_sets["test"])

    def test_line_random_split_is_deterministic_and_nonempty(self):
        rows = [{"writer_id": "unknown", "text": f"line {index}"} for index in range(20)]
        splits = line_random_split(rows, seed=7)
        repeated = line_random_split(rows, seed=7)
        self.assertEqual(splits, repeated)
        self.assertEqual({name: len(split) for name, split in splits.items()},
                         {"train": 16, "validation": 2, "test": 2})
        split_lines = [{row["text"] for row in split} for split in splits.values()]
        self.assertFalse(split_lines[0] & split_lines[1])
        self.assertFalse(split_lines[0] & split_lines[2])
        self.assertFalse(split_lines[1] & split_lines[2])

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
