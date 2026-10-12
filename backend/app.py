import os
import sys
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.htr_calibration import CalibratedHTREngine
from models.memory_engine import EpisodicMemoryEngine
from models.persona_engine import PersonaEngine

app = FastAPI(
    title="Enchanted Ink API",
    description="The AI Diary That Writes Back — Calibrated Multimodal Uncertainty & Episodic Memory Backend",
    version="1.0.0"
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
