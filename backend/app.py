import os
import sys
import json
import uuid
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.htr_calibration import CalibratedHTREngine
from models.memory_engine import EpisodicMemoryEngine
from models.persona_engine import PersonaEngine
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
htr_engine = CalibratedHTREngine(temperature=1.45, rejection_threshold=0.65)
memory_engine = EpisodicMemoryEngine()
persona_engine = PersonaEngine()
board_storage = BoardStorage()

# =========================================================================
# WHITEBOARD API ENDPOINTS
# =========================================================================

class BoardCommandRequest(BaseModel):
    command: str
    selected_ids: Optional[List[str]] = None
    board_context: Optional[Dict[str, Any]] = None
    insertion_point: Optional[Dict[str, float]] = None

class BoardSaveRequest(BaseModel):
    name: str = "Whiteboard"
    data: Dict[str, Any]
    thumbnail: Optional[str] = None

class BoardCreateRequest(BaseModel):
    name: str = "Untitled Board"

class BoardHTRRequest(BaseModel):
    strokes: Optional[List[Dict[str, Any]]] = None
    image_base64: Optional[str] = ""
    canvas_width: int = 800
    canvas_height: int = 600

@app.post("/api/board/command")
async def execute_board_command(req: BoardCommandRequest):
    """
    Core @board AI interaction endpoint:
    Interprets user command and canvas context, returning validated native whiteboard objects.
    """
    if not req.command or len(req.command.strip()) == 0:
        raise HTTPException(status_code=400, detail="Command cannot be empty.")

    try:
        response = board_ai_service.generate_board_objects(
            command=req.command,
            board_context=req.board_context,
            insertion_point=req.insertion_point
        )
        return JSONResponse(status_code=200, content=response.model_dump())
    except Exception as e:
        print(f"[BoardCommand] Error generating board objects: {e}")
        # Safe fallback
        fallback = board_ai_service._generate_fallback_response(req.command, req.board_context)
        return JSONResponse(status_code=200, content={
            "batch_id": f"ai_batch_{uuid.uuid4().hex[:8]}",
            "command": req.command,
            "summary": fallback.get("summary", "Generated whiteboard content."),
            "objects": fallback.get("objects", []),
            "warnings": [f"Handled with fallback: {str(e)}"]
        })

@app.post("/api/board/htr")
async def recognize_board_handwriting(req: BoardHTRRequest):
    """
    Online handwriting recognition for canvas strokes.
    Converts hand-drawn ink into editable digital text.
    """
    try:
        if req.strokes and len(req.strokes) > 0:
            res = htr_engine.recognize_online_strokes(
                strokes=req.strokes,
                canvas_width=req.canvas_width,
                canvas_height=req.canvas_height
            )
            if res and res.get("text"):
                return JSONResponse(status_code=200, content={
                    "text": res["text"],
                    "confidence": res.get("confidence", 0.90),
                    "candidates": res.get("candidates", [])
                })
        
        # Fallback to raster image if strokes not provided
        if req.image_base64 and len(req.image_base64) > 100:
            turn_res = htr_engine.process_turn(strokes=None, image_base64=req.image_base64)
            return JSONResponse(status_code=200, content={
                "text": turn_res.get("transcription", ""),
                "confidence": turn_res.get("confidence", 0.70),
                "candidates": []
            })
            
        return JSONResponse(status_code=200, content={"text": "", "confidence": 0.0, "candidates": []})
    except Exception as e:
        print(f"[BoardHTR] Error: {e}")
        return JSONResponse(status_code=200, content={"text": "", "confidence": 0.0, "error": str(e)})

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
        "provider": "Google Gemini (gemini-2.5-flash / gemini-3.5-flash-lite)"
    })

@app.post("/api/board/config/key")
async def set_board_api_key(cfg: Dict[str, str]):
    key = cfg.get("api_key", "").strip()
    success = board_ai_service.set_api_key(key)
    return JSONResponse(content={"status": "saved" if success else "failed", "configured": board_ai_service.is_configured()})


class TurnRequest(BaseModel):
    page_number: int = 1
    image_base64: str = ""
    stroke_data: Optional[List[dict]] = None
    user_text_hint: Optional[str] = None
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
        htr_result = htr_engine.process_turn(strokes=req.stroke_data, image_base64=req.image_base64)

        has_hint = bool(req.user_text_hint and len(req.user_text_hint.strip()) > 0)

        if htr_result.get("is_empty") and not has_hint:
            return JSONResponse(status_code=200, content={
                "transcription": "",
                "confidence": 0.0,
                "clarification_required": False,
                "ai_reply": "The page awaits your quill... Write upon my parchment.",
                "retrieved_memories": []
            })

        # If user provided an explicit hint/override (e.g. from the on-screen transcription inspector)
        transcription = htr_result["transcription"]
        if has_hint:
            transcription = req.user_text_hint.strip()
            htr_result["confidence"] = 0.95
            htr_result["clarification_required"] = False

        confidence = htr_result["confidence"]
        clarification_required = htr_result["clarification_required"]

        # Step 2: Gating on Calibrated Uncertainty
        if clarification_required and not req.user_text_hint:
            clarification_msg = htr_result.get("clarification_prompt", "Thy ink was faint and troubled... Didst thou speak to me?")
            return JSONResponse(status_code=200, content={
                "transcription": transcription,
                "confidence": confidence,
                "clarification_required": True,
                "ai_reply": clarification_msg,
                "retrieved_memories": [],
                "debug": htr_result
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
            "debug": htr_result
        })
    except Exception as e:
        print(f"[ProcessTurn] Unexpected error handled gracefully: {e}")
        return JSONResponse(status_code=200, content={
            "transcription": "(Inscribed thought)",
            "confidence": 0.70,
            "clarification_required": False,
            "ai_reply": "I felt the pressure of your quill upon my page. The ink stirs my memory... Tell me more.",
            "retrieved_memories": []
        })

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
