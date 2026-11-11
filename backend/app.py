import os
import sys
import json
import uuid
import logging
import threading
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.trocr_htr import TrOCRService
from models.memory_engine import EpisodicMemoryEngine
from models.persona_engine import PersonaEngine
from models.gemini_service import gemini_service
from models.board_command_parser import extract_board_command
from models.board_storage import BoardStorage
from models.board_ai_service import board_ai_service, BoardCommandResponse

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

# Instantiate core engines
htr_engine = TrOCRService()
memory_engine = EpisodicMemoryEngine()
persona_engine = PersonaEngine()
board_storage = BoardStorage()


@app.on_event("startup")
def initialize_htr_model():
    """Load HTR in the background so a cold model download does not block the API."""
    def load_model():
        try:
            loaded = htr_engine.initialize()
            if loaded:
                logging.getLogger(__name__).info("HTR ready: %s (%s)", htr_engine.model_label, htr_engine.model_name)
            else:
                logging.getLogger(__name__).warning("HTR unavailable: %s", htr_engine.load_error)
        except Exception:
            logging.getLogger(__name__).exception("HTR initialization failed")

    try:
        threading.Thread(target=load_model, name="trocr-model-loader", daemon=True).start()
    except Exception:
        logging.getLogger(__name__).exception("HTR initialization failed")

# =========================================================================
# WHITEBOARD API ENDPOINTS
# =========================================================================

class BoardCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    selected_ids: Optional[List[str]] = Field(default=None, max_length=40)
    board_context: Optional[Dict[str, Any]] = None
    insertion_point: Optional[Dict[str, float]] = None

    @field_validator("board_context")
    @classmethod
    def bounded_board_context(cls, value):
        if value is not None:
            if len(json.dumps(value, ensure_ascii=False)) > 24000:
                raise ValueError("Board context exceeds 24 KB")
            objects = value.get("objects", [])
            if not isinstance(objects, list) or len(objects) > 40:
                raise ValueError("Board context may include at most 40 objects")
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
    stroke_metadata: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=100)
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
    if parsed_command["command_detected"]:
        if parsed_command["instruction_missing"]:
            raise HTTPException(status_code=400, detail="Please add an instruction after @board.")
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
    """
    Recognizes a cropped pen-stroke line with local TrOCR and reports any
    constrained @board invocation separately from the transcription.
    """
    request_id = req.request_id or uuid.uuid4().hex
    try:
        if not req.image_base64:
            return JSONResponse(status_code=400, content={"success": False, "status": "invalid_request",
                "error": "A raster handwriting image is required by the TrOCR line model.", "request_id": request_id})
        result = htr_engine.recognize(req.image_base64, force_retry=req.retry_model)
        command = extract_board_command(result["transcription"])
        clarification = bool(result["clarification_required"])
        return JSONResponse(status_code=200, content={
            "success": True, "status": "recognized" if result["transcription"] else "empty",
            "text": result["transcription"], "confidence": result["calibrated_confidence"],
            "raw_confidence": result["raw_confidence"],
            "calibrated": result["confidence_status"] == "loaded",
            "clarification_required": clarification,
            "model_source": result.get("model_source"),
            "model_name": result.get("model_name"),
            "model_label": result.get("model_label"),
            "command_detected": command["command_detected"],
            "command_text": command["command_text"],
            "instruction_missing": command["instruction_missing"],
            "confidence_status": result["confidence_status"], "request_id": request_id
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
    return JSONResponse(content={
        "configured": board_ai_service.is_configured(),
        "provider": "Google Gemini",
        "model": os.getenv("GEMINI_BOARD_MODEL", "gemini-3.8-flash")
    })

@app.post("/api/board/config/key")
async def set_board_api_key(cfg: Dict[str, str]):
    key = cfg.get("api_key", "").strip()
    success = board_ai_service.set_api_key(key)
    return JSONResponse(content={"status": "saved" if success else "failed", "configured": board_ai_service.is_configured()})


class TurnRequest(BaseModel):
    page_number: int = Field(default=1, ge=1, le=100000)
    image_base64: str = Field(default="", max_length=12_000_000)
    stroke_data: Optional[List[dict]] = None
    user_text_hint: Optional[str] = Field(default=None, max_length=1000)
    persona_id: str = "tom_riddle"

@app.post("/api/v1/process-turn")
async def process_turn(req: TurnRequest):
    """
    Core multimodal interaction turn:
    1. Analyzes handwritten canvas stroke vector coordinates (online HTR) + image.
    2. Computes temperature-calibrated confidence score.
    3. Handles diegetic clarification if confidence < tau.
    4. Retrieves episodic memory context.
    5. Generates persona-aligned AI reply.
    6. Extracts & stores new user proposition.
    """
    try:
        # Step 1: Handwriting Recognition & Calibration
        has_hint = bool(req.user_text_hint and len(req.user_text_hint.strip()) > 0)
        if has_hint:
            transcription = req.user_text_hint.strip()
            confidence = None
            clarification_required = False
            htr_result = {"transcription": transcription, "confidence": None,
                          "confidence_status": "user_confirmed", "is_empty": False}
        else:
            htr_result = htr_engine.recognize(req.image_base64)
            transcription = htr_result["transcription"]
            confidence = htr_result["calibrated_confidence"]
            clarification_required = htr_result["clarification_required"]

        if htr_result.get("is_empty") and not has_hint:
            return JSONResponse(status_code=200, content={
                "transcription": "",
                "confidence": None,
                "clarification_required": False,
                "ai_reply": "",
                "retrieved_memories": [], "state": "empty"
            })

        # Step 2: Gating on Calibrated Uncertainty
        if clarification_required and not req.user_text_hint:
            clarification_msg = htr_result.get("clarification_prompt", "Thy ink was faint and troubled... Didst thou speak to me?")
            return JSONResponse(status_code=200, content={
                "transcription": transcription,
                "confidence": confidence,
                "clarification_required": True,
                "ai_reply": clarification_msg,
                "retrieved_memories": [],
                "debug": htr_result, "state": "clarification_required"
            })

        # Step 3: Episodic Memory Retrieval
        memories = memory_engine.retrieve_relevant_memories(transcription, top_k=3)
        history = memory_engine.get_page_history()

        # Step 4: Persona Dialogue Generation (Live Gemini LLM or Dynamic Engine)
        ai_reply = persona_engine.generate_reply(
            user_query=transcription,
            persona_id=req.persona_id,
            retrieved_memories=memories,
            history=history
        )

        # Step 5: Extract proposition & commit to memory
        memory_engine.extract_and_store_proposition(transcription)

        # Step 6: Record page turn
        memory_engine.record_page_turn(
            page_number=req.page_number,
            user_text=transcription,
            ai_reply=ai_reply,
            confidence=confidence,
            persona=req.persona_id
        )

        return JSONResponse(status_code=200, content={
            "transcription": transcription,
            "confidence": confidence,
            "clarification_required": False,
            "ai_reply": ai_reply,
            "retrieved_memories": memories,
            "debug": htr_result, "state": "completed",
            "reply_source": persona_engine.last_reply_source,
            "reply_warning": gemini_service.last_error if persona_engine.last_reply_source != "gemini" else None
        })
    except RuntimeError as e:
        print(f"[ProcessTurn] HTR unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print(f"[ProcessTurn] {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Diary turn failed. Your writing has been retained in the browser.")

@app.get("/api/v1/htr/status")
async def get_htr_status():
    status = htr_engine.status()
    status["inactivity_ms"] = max(500, min(10000, int(os.getenv("HTR_INACTIVITY_MS", "2200"))))
    status["retry_available"] = True
    return JSONResponse(content=status)

@app.get("/api/v1/config/gemini-status")
async def get_gemini_status():
    from models.gemini_service import gemini_service
    return JSONResponse(content={"configured": gemini_service.is_configured()})

class KeyConfig(BaseModel):
    api_key: str

@app.post("/api/v1/config/gemini-key")
async def set_gemini_key(cfg: KeyConfig):
    from models.gemini_service import gemini_service
    success = gemini_service.set_api_key(cfg.api_key)
    return JSONResponse(content={"status": "saved" if success else "failed", "configured": gemini_service.is_configured()})

@app.get("/api/v1/memories")
async def get_memories():
    return JSONResponse(content=memory_engine.list_all_memories())

@app.delete("/api/v1/memories/{memory_id}")
async def delete_memory(memory_id: int):
    success = memory_engine.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory proposition not found.")
    return JSONResponse(content={"status": "deleted", "id": memory_id})

@app.post("/api/v1/memories/purge")
async def purge_memories():
    memory_engine.purge_all_memories()
    return JSONResponse(content={"status": "purged", "message": "All memories and pages wiped."})

@app.get("/api/v1/pages")
async def get_pages():
    return JSONResponse(content=memory_engine.get_page_history())

@app.get("/api/v1/personas")
async def get_personas():
    return JSONResponse(content=[
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in persona_engine.personas.items()
    ])

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
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
