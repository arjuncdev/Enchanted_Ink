import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app, htr_engine, persona_engine, board_ai_service
from models.memory_engine import EpisodicMemoryEngine


class DiaryApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory = EpisodicMemoryEngine(f"{self.temp_dir.name}/diary.sqlite")
        self.client = TestClient(app)
        self.memory_patch = patch("app.memory_engine", self.memory)
        self.memory_patch.start()

    def tearDown(self):
        self.memory_patch.stop()
        self.temp_dir.cleanup()

    def test_low_confidence_does_not_reach_memory_or_reply(self):
        low_result = {"transcription": "unclear words", "calibrated_confidence": 0.3,
                      "confidence": 0.3, "clarification_required": True,
                      "clarification_prompt": "Please confirm.", "is_empty": False}
        with patch.object(htr_engine, "recognize", return_value=low_result), \
             patch.object(persona_engine, "generate_reply") as reply:
            response = self.client.post("/api/v1/process-turn", json={"image_base64": "image"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["clarification_required"])
        self.assertEqual(self.memory.get_page_history(), [])
        reply.assert_not_called()

    def test_user_confirmed_correction_uses_memory_and_reply_pipeline(self):
        with patch.object(persona_engine, "generate_reply", return_value="A reply."):
            response = self.client.post("/api/v1/process-turn", json={
                "page_number": 4, "user_text_hint": "My corrected sentence", "persona_id": "regular_qa"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcription"], "My corrected sentence")
        self.assertEqual(response.json()["state"], "completed")
        pages = self.memory.get_page_history()
        self.assertEqual(pages[0]["user_text"], "My corrected sentence")

    def test_missing_model_returns_visible_service_error(self):
        if htr_engine.available:
            self.skipTest("A local model is configured; missing-checkpoint case does not apply")
        with patch.object(htr_engine, "recognize", side_effect=RuntimeError("TrOCR checkpoint is not configured")):
            response = self.client.post("/api/v1/process-turn", json={"image_base64": "image"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("checkpoint", response.json()["detail"])

    def test_htr_endpoint_returns_command_extraction_fields(self):
        with patch.object(htr_engine, "recognize", return_value={
            "transcription": "@ board create a flowchart", "calibrated_confidence": 0.91,
            "raw_confidence": 0.89, "confidence_status": "loaded", "clarification_required": False
        }):
            response = self.client.post("/api/board/htr", json={"image_base64": "fixture",
                "request_id": "test-htr-1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["command_text"], "create a flowchart")
        self.assertEqual(response.json()["request_id"], "test-htr-1")
        self.assertTrue(response.json()["calibrated"])

    def test_htr_missing_checkpoint_has_structured_unavailable_response(self):
        with patch.object(htr_engine, "recognize", side_effect=RuntimeError("TrOCR checkpoint is not configured")):
            response = self.client.post("/api/board/htr", json={
                "image_base64": "test-image", "request_id": "missing-model-test"})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertEqual(response.json()["request_id"], "missing-model-test")

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
