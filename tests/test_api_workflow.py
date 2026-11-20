import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app, board_ai_service, ai_provider_settings, google_htr_service
from models.ai_provider import ollama_service


class BoardApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_whiteboard_chat_bar_has_no_handwriting_service_label(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("htr-engine-label", response.text)
        self.assertNotIn("Handwriting recognition: external Google service", response.text)

    def test_ai_provider_settings_can_select_ollama(self):
        ollama_status = {
            "available": True, "model": "qwen2.5:7b",
            "model_available": True, "error": None,
        }
        with patch.dict(os.environ, {"AI_PROVIDER": "ollama"}), \
             patch.object(ai_provider_settings, "configure", return_value=True) as configure, \
             patch.object(ollama_service, "status", return_value=ollama_status):
            response = self.client.post("/api/ai/config", json={
                "provider": "ollama", "ollama_base_url": "http://localhost:11434",
                "ollama_model": "qwen2.5:7b"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider_id"], "ollama")
        self.assertTrue(response.json()["configured"])
        configure.assert_called_once_with(
            "ollama", "http://localhost:11434", "qwen2.5:7b")

    def test_api_key_configuration_does_not_break_gemini_provider_setup(self):
        with patch.object(board_ai_service, "set_api_key", return_value=True) as set_key, \
             patch.object(ai_provider_settings, "configure", return_value=True), \
             patch.object(ollama_service, "status", return_value={"available": False}):
            response = self.client.post("/api/ai/config", json={
                "provider": "gemini", "api_key": "test-key"})
        self.assertEqual(response.status_code, 200)
        set_key.assert_called_once_with("test-key")

    def test_htr_endpoint_uses_gemini_and_returns_command_fields(self):
        result = {
            "transcription": "@ board create a flowchart",
            "calibrated_confidence": None, "raw_confidence": None,
            "confidence_status": "google_unscored",
            "clarification_required": True, "model_source": "google",
            "model_name": "gemini-3.1-flash-lite",
            "model_label": "GOOGLE GEMINI VISION — EXTERNAL HANDWRITING RECOGNITION",
            "recognizer": "Google Gemini Vision",
        }
        with patch.object(google_htr_service, "is_configured", return_value=True), \
             patch.object(google_htr_service, "recognize", return_value=result) as recognize:
            response = self.client.post("/api/board/htr", json={
                "image_base64": "fixture", "request_id": "test-htr-1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["command_text"], "create a flowchart")
        self.assertEqual(response.json()["request_id"], "test-htr-1")
        self.assertEqual(response.json()["recognition_engine"], "gemini")
        self.assertEqual(response.json()["recognizer"], "Google Gemini Vision")
        self.assertIsNone(response.json()["confidence"])
        self.assertFalse(response.json()["calibrated"])
        recognize.assert_called_once_with("fixture")

    def test_missing_gemini_configuration_is_explicit_and_never_uses_local_model(self):
        with patch.object(google_htr_service, "is_configured", return_value=False), \
             patch.object(google_htr_service, "recognize") as recognize:
            response = self.client.post("/api/board/htr", json={
                "image_base64": "test-image", "request_id": "missing-key-test"})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertEqual(response.json()["request_id"], "missing-key-test")
        self.assertIn("GEMINI_API_KEY", response.json()["error"])
        recognize.assert_not_called()

    def test_htr_status_reports_external_gemini_provider(self):
        configured_model = google_htr_service.model
        with patch.object(google_htr_service, "is_configured", return_value=True), \
             patch.dict(os.environ, {"GEMINI_HWR_MODEL": configured_model}):
            response = self.client.get("/api/v1/htr/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model_source"], "google")
        self.assertEqual(response.json()["model_name"], configured_model)
        self.assertTrue(response.json()["external_service"])

    def test_incomplete_board_invocation_returns_clear_error(self):
        response = self.client.post("/api/board/command", json={"command": "@board"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("instruction", response.json()["detail"])

    def test_board_command_returns_labeled_editable_fallback(self):
        with patch.object(board_ai_service, "api_key", ""):
            response = self.client.post("/api/board/command", json={
                "command": "@ board create a flowchart for login",
                "board_context": {"scope": "all", "objects": []}})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider_status"], "fallback")
        self.assertTrue(payload["fallback_used"])
        self.assertGreater(len(payload["objects"]), 0)


if __name__ == "__main__":
    unittest.main()
