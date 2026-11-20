import os
import sys
import json
import uuid
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Literal

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.google_htr_service import google_htr_service
from models.ai_provider import ai_provider_settings, ollama_service
from models.board_command_parser import extract_board_command
from models.board_storage import BoardStorage
from models.board_ai_service import board_ai_service, BoardCommandResponse

# Main entry point: expose the whiteboard UI and coordinate its API services.
app = FastAPI(
    title="Enchanted Ink — AI Whiteboard API",
    description="Interactive AI Whiteboard with spatial generation, handwriting recognition, and persistent canvas storage",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instantiate API services.
board_storage = BoardStorage()


# =========================================================================
# WHITEBOARD API ENDPOINTS
# =========================================================================
# These routes handle board generation, recognition, and persisted board state.

class BoardCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    selected_ids: Optional[List[str]] = Field(default=None, max_length=40)
    board_context: Optional[Dict[str, Any]] = None
    insertion_point: Optional[Dict[str, float]] = None

    @field_validator("board_context")
    @classmethod
    def bounded_board_context(cls, value):
        if value is not None:
            if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 1048576:
                raise ValueError("Board context exceeds 1 MB")
            objects = value.get("objects", [])
            if not isinstance(objects, list) or len(objects) > 1000:
                raise ValueError("Board context may include at most 1000 objects")
        return value

class BoardSaveRequest(BaseModel):
    name: str = "Whiteboard"
    data: Dict[str, Any]
    thumbnail: Optional[str] = None

class BoardCreateRequest(BaseModel):
    name: str = "Untitled Board"

class BoardHTRRequest(BaseModel):
    strokes: Optional[List[Dict[str, Any]]] = None
    image_base64: Optional[str] = Field(default="", max_length=12_000_000)
    canvas_width: int = 800
    canvas_height: int = 600
    request_id: Optional[str] = Field(default=None, max_length=100)
    stroke_metadata: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=1000)
    retry_model: bool = False

@app.post("/api/board/command")
async def execute_board_command(req: BoardCommandRequest):
    """
    Core @board AI interaction endpoint:
    Interprets user command and canvas context, returning validated native whiteboard objects.
    """
    if not req.command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty.")
    parsed_command = extract_board_command(req.command)
    if not parsed_command["command_detected"]:
        raise HTTPException(status_code=400, detail="Start your request with @board to get a board response.")
    if parsed_command["instruction_missing"]:
        raise HTTPException(status_code=400, detail="Please add a question or instruction after @board.")
    req.command = f"@board {parsed_command['command_text']}"
    if req.board_context and req.board_context.get("scope") == "selected" and not req.board_context.get("objects"):
        raise HTTPException(status_code=422, detail="Selected Objects scope requires at least one selected object.")

    try:
        response = board_ai_service.generate_board_objects(
            command=req.command,
            board_context=req.board_context,
            insertion_point=req.insertion_point
        )
        return JSONResponse(status_code=200, content=response.model_dump())
    except Exception as e:
        print(f"[BoardCommand] Invalid response: {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail=f"Board response was invalid; nothing was inserted. {e}")

@app.post("/api/board/htr")
async def recognize_board_handwriting(req: BoardHTRRequest):
    """Transcribe whiteboard handwriting with external Google Gemini Vision."""
    request_id = req.request_id or uuid.uuid4().hex
    try:
        if not req.image_base64:
            return JSONResponse(status_code=400, content={"success": False, "status": "invalid_request",
                "error": "A raster handwriting image is required for recognition.", "request_id": request_id})
        if not google_htr_service.is_configured():
            raise RuntimeError(
                "External handwriting recognition is not configured. Set GEMINI_API_KEY."
            )
        result = await run_in_threadpool(
            google_htr_service.recognize, req.image_base64)

        command = extract_board_command(result["transcription"])
        return JSONResponse(status_code=200, content={
            "success": True, "status": "recognized" if result["transcription"] else "empty",
            "text": result["transcription"], "confidence": None,
            "raw_confidence": None,
            "calibrated": False,
            "clarification_required": True,
            "model_source": result.get("model_source"),
            "model_name": result.get("model_name"),
            "model_label": result.get("model_label"),
            "recognizer": result.get("recognizer", "Google Gemini Vision"),
            "recognition_engine": "gemini",
            "command_detected": command["command_detected"],
            "command_text": command["command_text"],
            "instruction_missing": command["instruction_missing"],
            "confidence_status": "google_unscored", "request_id": request_id
        })
    except ValueError as e:
        return JSONResponse(status_code=422, content={"success": False, "status": "invalid_image",
            "error": str(e), "request_id": request_id})
    except RuntimeError as e:
        print(f"[BoardHTR:{request_id}] {type(e).__name__}: {e}")
        return JSONResponse(status_code=503, content={"success": False, "status": "unavailable",
            "error": str(e), "request_id": request_id})
    except Exception as e:
        print(f"[BoardHTR:{request_id}] {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={"success": False, "status": "recognition_error",
            "error": "Handwriting recognition failed.", "request_id": request_id})

@app.get("/api/board/list")
async def list_boards():
    """List all saved whiteboard boards."""
    boards = board_storage.list_boards()
    return JSONResponse(content={"boards": boards})

@app.post("/api/board/new")
async def create_board(req: BoardCreateRequest):
    """Create a new blank whiteboard board."""
    new_id = f"board_{uuid.uuid4().hex[:8]}"
    initial_data = {"version": "1.0", "objects": []}
    success = board_storage.save_board(new_id, req.name, json.dumps(initial_data))
    if success:
        return JSONResponse(content={"id": new_id, "name": req.name})
    raise HTTPException(status_code=500, detail="Failed to create board.")

@app.get("/api/board/{board_id}")
async def get_board(board_id: str):
    """Retrieve full board data."""
    board = board_storage.get_board(board_id)
    if not board:
        # If default board requested and not found, create it
        if board_id == "default":
            board_storage.save_board("default", "Main Whiteboard", json.dumps({"version": "1.0", "objects": []}))
            board = board_storage.get_board("default")
        else:
            raise HTTPException(status_code=404, detail="Board not found.")
    return JSONResponse(content=board)

@app.post("/api/board/{board_id}/save")
async def save_board(board_id: str, req: BoardSaveRequest):
    """Save canvas objects to SQLite."""
    success = board_storage.save_board(
        board_id=board_id,
        name=req.name,
        data_json=json.dumps(req.data),
        thumbnail=req.thumbnail
    )
    if success:
        return JSONResponse(content={"status": "saved", "id": board_id})
    raise HTTPException(status_code=500, detail="Failed to save board.")

@app.delete("/api/board/{board_id}")
async def delete_board(board_id: str):
    """Delete a board."""
    if board_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default board.")
    success = board_storage.delete_board(board_id)
    if success:
        return JSONResponse(content={"status": "deleted", "id": board_id})
    raise HTTPException(status_code=404, detail="Board not found.")

@app.get("/api/board/config/status")
async def get_board_config_status():
    """Check AI provider configuration status."""
    provider = ai_provider_settings.provider
    ollama_status = await run_in_threadpool(ollama_service.status) if provider == "ollama" else None
    configured = (bool(ollama_status and ollama_status["model_available"])
                  if provider == "ollama" else board_ai_service.is_configured())
    return JSONResponse(content={
        "configured": configured,
        "provider": "Ollama (local)" if provider == "ollama" else "Google Gemini",
        "provider_id": provider,
        "model": ai_provider_settings.ollama_model if provider == "ollama" else board_ai_service.model_name,
        "ollama_base_url": ai_provider_settings.ollama_base_url,
        "ollama": ollama_status,
        "fallback_model": board_ai_service.fallback_model or None
    })

class AIProviderConfigRequest(BaseModel):
    provider: Literal["gemini", "ollama"]
    ollama_base_url: str = Field(default="http://localhost:11434", min_length=1, max_length=500)
    ollama_model: str = Field(default="qwen2.5:7b", min_length=1, max_length=128)
    api_key: Optional[str] = Field(default=None, max_length=500)

@app.post("/api/ai/config")
async def configure_ai_provider(cfg: AIProviderConfigRequest):
    """Persist the selected response provider and local Ollama settings."""
    if cfg.api_key and cfg.api_key.strip():
        if not board_ai_service.set_api_key(cfg.api_key):
            raise HTTPException(status_code=500, detail="Failed to save Google AI API key.")
    try:
        saved = ai_provider_settings.configure(
            cfg.provider, cfg.ollama_base_url, cfg.ollama_model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not saved:
        raise HTTPException(status_code=500, detail=ai_provider_settings.last_error)
    return await get_board_config_status()

@app.post("/api/board/config/key")
async def set_board_api_key(cfg: Dict[str, str]):
    key = cfg.get("api_key", "").strip()
    success = board_ai_service.set_api_key(key)
    return JSONResponse(content={"status": "saved" if success else "failed", "configured": board_ai_service.is_configured()})

@app.get("/api/v1/htr/status")
async def get_htr_status():
    configured = google_htr_service.is_configured()
    status = {
        "available": configured,
        "configured": configured,
        "loaded": False,
        "loading": False,
        "model_source": "google",
        "model_name": google_htr_service.model,
        "model_label": "GOOGLE GEMINI VISION — EXTERNAL HANDWRITING RECOGNITION",
        "recognizer": "Google Gemini Vision",
        "external_service": True,
        "confidence_status": "google_unscored",
        "inactivity_ms": max(5000, min(15000, int(os.getenv("HTR_INACTIVITY_MS", "12000")))),
        "retry_available": True,
        "error": None if configured else "Set GEMINI_API_KEY.",
    }
    return JSONResponse(content=status)

# Serve static files and HTML
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Enchanted Ink API is running."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("APP_PORT", "8000")), reload=True)
