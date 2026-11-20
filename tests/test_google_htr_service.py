import base64
import io
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from models.google_htr_service import GoogleHandwritingRecognizer


class GoogleHandwritingRecognizerTests(unittest.TestCase):
    @staticmethod
    def png_image_base64():
        image = Image.new("RGB", (16, 16), "white")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return base64.b64encode(stream.getvalue()).decode("ascii")

    def test_sends_image_to_configured_gemini_model_and_returns_unscored_text(self):
        recognizer = GoogleHandwritingRecognizer(api_key="test-key", model="gemini-test")
        response = Mock(status_code=200)
        response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "@board create a flowchart"}]}
            }]
        }
        with patch("models.google_htr_service.requests.post", return_value=response) as post:
            result = recognizer.recognize(self.png_image_base64())

        args, kwargs = post.call_args
        self.assertIn("models/gemini-test:generateContent", args[0])
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "test-key")
        image_part = kwargs["json"]["contents"][0]["parts"][1]["inline_data"]
        self.assertEqual(image_part["mime_type"], "image/png")
        self.assertTrue(image_part["data"])
        self.assertEqual(result["transcription"], "@board create a flowchart")
        self.assertEqual(result["model_source"], "google")
        self.assertIsNone(result["calibrated_confidence"])
        self.assertTrue(result["clarification_required"])

    def test_provider_http_error_is_explicit(self):
        recognizer = GoogleHandwritingRecognizer(api_key="test-key", model="gemini-test")
        response = Mock(status_code=401)
        response.json.return_value = {"error": {"message": "Invalid API key"}}
        with patch("models.google_htr_service.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                recognizer.recognize(self.png_image_base64())

    def test_empty_recognition_is_returned_as_empty_text_not_service_failure(self):
        recognizer = GoogleHandwritingRecognizer(api_key="test-key", model="gemini-test")
        response = Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": []}}]}
        with patch("models.google_htr_service.requests.post", return_value=response):
            result = recognizer.recognize(self.png_image_base64())
        self.assertEqual(result["transcription"], "")


if __name__ == "__main__":
    unittest.main()
