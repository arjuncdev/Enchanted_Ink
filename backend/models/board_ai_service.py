import os
import re
import json
import uuid
import requests
import math
from typing import List, Dict, Optional, Any, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from dotenv import load_dotenv, set_key

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
load_dotenv(ENV_PATH)

# =========================================================================
# Pydantic Schemas for Board Objects and Validation
# =========================================================================

class WhiteboardObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: f"obj_{uuid.uuid4().hex[:8]}")
    type: Literal["text", "sticky_note", "rectangle", "ellipse", "arrow", "connector"]
    x: float = 0.0
    y: float = 0.0
    width: float = 160.0
    height: float = 90.0
    text: Optional[str] = ""
    title: Optional[str] = ""
    fill: Optional[str] = "#ffffff"
    stroke: Optional[str] = "#1e293b"
    stroke_width: Optional[float] = 2.0
    font_size: Optional[int] = 14
    from_id: Optional[str] = None
    to_id: Optional[str] = None
    label: Optional[str] = None
    ai_batch_id: Optional[str] = None

    @field_validator("x", "y", "width", "height", "stroke_width")
    @classmethod
    def finite_geometry(cls, value, info):
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be finite")
        if info.field_name in ("width", "height") and not 0 <= value <= 4000:
            raise ValueError(f"{info.field_name} is outside supported bounds")
        if info.field_name in ("width", "height") and value == 0 and info.data.get("type") not in ("arrow", "connector"):
            raise ValueError(f"{info.field_name} must be positive for non-connectors")
        if info.field_name in ("x", "y") and abs(value) > 100000:
            raise ValueError(f"{info.field_name} is outside supported bounds")
        return value

    @field_validator("fill", "stroke")
    @classmethod
    def valid_color(cls, value):
        if value is None or value.lower() == "none":
            return value
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("color must be a six-digit hex color")
        return value

    @field_validator("text", "title", "label")
    @classmethod
    def limit_text(cls, value):
        if value is not None and len(value) > 2000:
            raise ValueError("object text exceeds 2000 characters")
        return value

class BoardCommandResponse(BaseModel):
    batch_id: str
    command: str
    summary: str
    objects: List[WhiteboardObject]
    warnings: Optional[List[str]] = []
    provider_status: str = "fallback"
    provider: str = "rule_based"
    model: Optional[str] = None
    fallback_used: bool = True

# =========================================================================
# AI System Prompt & Instruction
# =========================================================================

WHITEBOARD_SYSTEM_PROMPT = """
You are the AI Whiteboard Engine for Enchanted Ink.
Your role is to translate user commands into visual, spatial whiteboard canvas elements:
diagrams, flowcharts, block diagrams, mind maps, comparison cards, formulas, and structured sticky notes.

You must respond ONLY with valid, parseable JSON conforming to this schema:
{
  "summary": "Short 1-2 sentence description of what was drawn onto the canvas",
  "objects": [
    {
      "id": "unique_string_id",
      "type": "text | sticky_note | rectangle | ellipse | arrow",
      "x": float,
      "y": float,
      "width": float,
      "height": float,
      "text": "text content inside or on the object",
      "title": "optional title (for cards/sticky notes)",
      "fill": "hex color string like #fef08a, #dbeafe, #f3e8ff, #dcfce7, #ffffff",
      "stroke": "hex color string like #2563eb, #059669, #7c3aed, #475569",
      "stroke_width": 2.0,
      "font_size": 14,
      "from_id": "id_of_source_object (only for arrow)",
      "to_id": "id_of_target_object (only for arrow)",
      "label": "optional short connector label like 'Yes', 'No', 'Next'"
    }
  ]
}

CRITICAL SPATIAL & DESIGN RULES:
1. SPATIAL LAYOUT & SIZING:
   - Layout should begin near x=0, y=0 relative to the insertion area (e.g., span across 800-1200px width).
   - For flowcharts: layout sequentially from left-to-right (horizontal flow) or top-to-bottom (vertical flow).
     Maintain at least 60-100px gap between nodes so connecting arrows are clearly visible.
   - For block diagrams: arrange blocks in logical sequence with clear connecting arrows.
   - For mind maps: place central concept in middle, child nodes branching outward.
   - Standard node dimensions:
     * Rectangles & Ellipses: width=180-220, height=70-90.
     * Sticky notes: width=200-240, height=180-220.
     * Title text: width=400-600, height=40-50, font_size=20-24.
     * Formula / annotation cards: width=220-300, height=80-120.

2. ARROWS & CONNECTORS:
   - For every connection between nodes, create an "arrow" object.
   - Set "from_id" to the source node id, and "to_id" to the target node id.
   - Calculate arrow x, y, width, height to span between the two connected node centers.

3. PALETTE & AESTHETICS:
   - Professional, clean, modern whiteboard style (similar to Excalidraw, Miro, or FigJam).
   - Use soft, readable pastel fills:
     * Sticky notes: #fef08a (classic yellow), #dbeafe (soft blue), #dcfce7 (mint green), #fce7f3 (soft pink), #f3e8ff (soft lavender).
     * Diagram nodes: #ffffff (clean white with crisp colored stroke) or light pastel accents.
   - Use crisp, modern stroke colors: #2563eb (blue), #059669 (green), #d97706 (amber), #7c3aed (purple), #334155 (slate).

4. RICH MULTI-OBJECT RESPONSES:
   - When asked to explain a system or circuit (e.g., DC-DC buck converter):
     * Include a bold Title block at top.
     * Include block diagram nodes for each component (e.g., DC Input -> MOSFET Switch -> Inductor L -> Output Filter C -> Load).
     * Include arrows between them.
     * Include a dedicated card for Key Equations (e.g. Vout ≈ D × Vin).
     * Include brief annotation sticky notes for component roles.
   - When asked to summarize notes:
     * Extract key themes and create 2-4 organized sticky notes/cards with bullet points.
   - When asked for a flowchart:
     * Include start/end ellipse nodes, intermediate process rectangles, decision diamonds/rectangles, and labeled arrows.

5. STRICT OUTPUT:
   - NEVER output markdown formatting around the JSON (e.g. no ```json blocks if possible, or if included, ensure valid json inside).
   - NEVER execute or return executable JavaScript code.
"""

# =========================================================================
# Board AI Service Provider Class
# =========================================================================

class BoardAIService:
    """
    Decoupled AI Provider service for the AI Whiteboard.
    Translates natural language @board commands and canvas context into validated whiteboard objects.
    """
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model_name = os.getenv("GEMINI_BOARD_MODEL", "gemini-3.8-flash").strip()
        self.last_error = ""

    def set_api_key(self, key: str) -> bool:
        clean_key = key.strip()
        self.api_key = clean_key
        os.environ["GEMINI_API_KEY"] = clean_key
        try:
            if not os.path.exists(ENV_PATH):
                with open(ENV_PATH, "w") as f:
                    f.write("")
            set_key(ENV_PATH, "GEMINI_API_KEY", clean_key)
            return True
        except Exception as e:
            print(f"[BoardAIService] Error saving .env: {e}")
            return False

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    def generate_board_objects(
        self,
        command: str,
        board_context: Optional[Dict[str, Any]] = None,
        insertion_point: Optional[Dict[str, float]] = None
    ) -> BoardCommandResponse:
        """
        Main entry point for @board commands.
        Gathers context, calls LLM provider, validates output schema, and applies spatial offset.
        """
        batch_id = f"ai_batch_{uuid.uuid4().hex[:8]}"
        clean_command = command.strip()
        
        # Remove leading/trailing @board token if present
        prompt_instruction = re.sub(r'(?i)^\s*@board\s*', '', clean_command).strip()
        if not prompt_instruction:
            prompt_instruction = clean_command

        # Default insertion point if not provided
        target_x = insertion_point.get("x", 200.0) if insertion_point else 200.0
        target_y = insertion_point.get("y", 150.0) if insertion_point else 150.0

        # Construct structured context description
        context_str = self._format_board_context(board_context)

        # Call the configured provider; any offline rule response is explicitly
        # marked so the client can never mistake it for a Gemini answer.
        self.last_error = ""
        raw_result = self._call_gemini(prompt_instruction, context_str) if self.is_configured() else None
        provider_status = "gemini" if raw_result else "fallback"
        warnings = [] if raw_result else [self.last_error or "Gemini is not configured; using a limited rule-based response."]
        if not raw_result:
            # Deterministic, high-quality rule-based fallback generator for offline or error states
            raw_result = self._generate_fallback_response(prompt_instruction, board_context)

        # Parse & Validate objects
        raw_objects = raw_result.get("objects", [])
        if not isinstance(raw_objects, list) or not raw_objects or len(raw_objects) > 80:
            raise ValueError("Provider must return 1 to 80 whiteboard objects")
        validated_objects = []
        node_map = {}
        for raw_obj in raw_objects:
            if not isinstance(raw_obj, dict):
                raise ValueError("Provider returned a non-object canvas item")
            obj_id = str(raw_obj.get("id") or f"obj_{uuid.uuid4().hex[:8]}")
            if obj_id in node_map:
                raise ValueError(f"Duplicate whiteboard object id: {obj_id}")
            payload = dict(raw_obj)
            payload.update(id=obj_id, x=float(raw_obj.get("x", 0)) + target_x,
                           y=float(raw_obj.get("y", 0)) + target_y,
                           width=float(raw_obj.get("width", 160)),
                           height=float(raw_obj.get("height", 80)), ai_batch_id=batch_id)
            wb_obj = WhiteboardObject.model_validate(payload)
            if wb_obj.font_size is not None and not 8 <= wb_obj.font_size <= 72:
                raise ValueError("font size must be between 8 and 72")
            if wb_obj.type in ("arrow", "connector") and (not wb_obj.from_id or not wb_obj.to_id):
                raise ValueError("Connectors require source and target IDs")
            validated_objects.append(wb_obj)
            node_map[obj_id] = wb_obj

        for obj in validated_objects:
            if obj.type in ("arrow", "connector"):
                if obj.from_id not in node_map or obj.to_id not in node_map:
                    raise ValueError(f"Connector {obj.id} references a missing endpoint")

        # Post-process arrows to ensure endpoint alignment
        for obj in validated_objects:
            if obj.type in ["arrow", "connector"] and obj.from_id and obj.to_id:
                src = node_map.get(obj.from_id)
                dst = node_map.get(obj.to_id)
                if src and dst:
                    # Calculate center-to-center coordinates
                    sx = src.x + src.width / 2.0
                    sy = src.y + src.height / 2.0
                    dx = dst.x + dst.width / 2.0
                    dy = dst.y + dst.height / 2.0
                    obj.x = round(min(sx, dx), 1)
                    obj.y = round(min(sy, dy), 1)
                    obj.width = round(abs(dx - sx), 1)
                    obj.height = round(abs(dy - sy), 1)

        summary = raw_result.get("summary", f"Generated visual response for: {prompt_instruction[:50]}")
        return BoardCommandResponse(
            batch_id=batch_id,
            command=clean_command,
            summary=summary,
            objects=validated_objects,
            warnings=warnings, provider_status=provider_status,
            provider="Google Gemini" if provider_status == "gemini" else "Rule-based fallback",
            model=self.model_name if provider_status == "gemini" else None,
            fallback_used=provider_status != "gemini"
        )

    def _format_board_context(self, context: Optional[Dict[str, Any]]) -> str:
        if not context:
            return "No previous objects on the board."
        
        parts = []
        objects = context.get("objects", [])
        if objects:
            compact = []
            for obj in objects[:40]:
                if not isinstance(obj, dict):
                    continue
                compact.append({k: obj.get(k) for k in ("id", "type", "text", "x", "y", "width", "height", "from_id", "to_id")})
            parts.append(f"Board scope={context.get('scope', 'all')}; objects={json.dumps(compact, ensure_ascii=False)[:12000]}")
        # Legacy clients remain readable during transition.
        if context.get("selected_text"):
            parts.append("Selected text: " + "; ".join(map(str, context["selected_text"][:20])))
        if context.get("existing_notes"):
            parts.append("Board notes: " + "; ".join(map(str, context["existing_notes"][:20])))
            
        return "\n\n".join(parts) if parts else "Empty canvas."

    def _call_gemini(self, prompt: str, context_str: str) -> Optional[Dict]:
        """
        Invokes Google Gemini with structured output.
        """
        models_to_try = [self.model_name]
        self.last_error = ""
        
        user_message = f"""USER WHITEBOARD COMMAND:
{prompt}

CURRENT WHITEBOARD CONTEXT:
{context_str}

Please generate the optimal visual arrangement of whiteboard objects (diagram, flowchart, sticky notes, formulas, or connectors) to fulfill this command."""

        for model_name in models_to_try:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
                payload = {
                    "contents": [
                        {"role": "user", "parts": [{"text": WHITEBOARD_SYSTEM_PROMPT}]},
                        {"role": "model", "parts": [{"text": "Understood. I will strictly return JSON conforming to the whiteboard schema."}]},
                        {"role": "user", "parts": [{"text": user_message}]}
                    ],
                    "generationConfig": {
                        "temperature": 0.4,
                        "maxOutputTokens": 4096,
                        "topP": 0.95,
                        "responseMimeType": "application/json"
                    }
                }
                resp = requests.post(url, json=payload, timeout=20.0)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        clean_json = self._extract_json_block(text_content)
                        if clean_json:
                            try:
                                parsed = json.loads(clean_json, strict=False)
                            except Exception:
                                clean_json_fixed = re.sub(r',\s*([\]}])', r'\1', clean_json)
                                parsed = json.loads(clean_json_fixed, strict=False)
                            if "objects" in parsed and isinstance(parsed["objects"], list):
                                return parsed
                            self.last_error = f"{model_name} returned an invalid structured response"
                        else:
                            self.last_error = f"{model_name} returned no parseable JSON"
                    else:
                        self.last_error = f"{model_name} returned no candidates"
                else:
                    try:
                        message = resp.json().get("error", {}).get("message", "")
                    except Exception:
                        message = resp.text[:300]
                    self.last_error = f"Gemini {model_name} HTTP {resp.status_code}: {message[:300]}"
                    print(f"[BoardAIService] {self.last_error}")
            except requests.Timeout:
                self.last_error = f"Gemini {model_name} request timed out"
            except requests.RequestException as e:
                self.last_error = f"Gemini network error: {type(e).__name__}"
            except Exception as e:
                self.last_error = f"Gemini response parsing failed ({type(e).__name__})"
                print(f"[BoardAIService] {self.last_error}: {e}")

        return None

    def _extract_json_block(self, text: str) -> Optional[str]:
        text = text.strip()
        # Direct JSON match
        if text.startswith("{") and text.endswith("}"):
            return text
        # Regex search for ```json ... ``` or { ... }
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            return match.group(1)
        # Search for first { to last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end+1]
        return None

    def _generate_fallback_response(self, command: str, context: Optional[Dict]) -> Dict:
        """
        High-fidelity fallback generator when Gemini API is offline or unconfigured.
        Provides robust visual responses for common engineering, flowchart, and note commands.
        """
        cmd_lower = command.lower()

        # 1. Buck converter / Circuit Diagram fallback
        if "buck converter" in cmd_lower or "circuit" in cmd_lower or "converter" in cmd_lower:
            return {
                "summary": "Generated DC-DC Buck Converter block diagram, circuit flow, equations, and component functions.",
                "objects": [
                    # Title
                    {"id": "n_title", "type": "text", "x": 0, "y": 0, "width": 600, "height": 45, "text": "DC-DC Buck Converter: Architecture & Operation", "font_size": 22, "fill": "#0f172a", "stroke": "none"},
                    
                    # Block 1: DC Source
                    {"id": "n_vin", "type": "rectangle", "x": 0, "y": 90, "width": 160, "height": 75, "text": "DC Input (Vin)\n[Unregulated Supply]", "fill": "#eff6ff", "stroke": "#2563eb", "stroke_width": 2},
                    
                    # Block 2: PWM Switch
                    {"id": "n_sw", "type": "rectangle", "x": 220, "y": 90, "width": 170, "height": 75, "text": "MOSFET Switch (Q1)\n[PWM High-Side Gate]", "fill": "#eff6ff", "stroke": "#2563eb", "stroke_width": 2},
                    
                    # Block 3: Inductor
                    {"id": "n_ind", "type": "rectangle", "x": 450, "y": 90, "width": 170, "height": 75, "text": "Power Inductor (L)\n[Energy Storage Flux]", "fill": "#eff6ff", "stroke": "#2563eb", "stroke_width": 2},
                    
                    # Block 4: Output Filter
                    {"id": "n_cap", "type": "rectangle", "x": 680, "y": 90, "width": 160, "height": 75, "text": "Filter Cap (C)\n[Ripple Voltage Smoothing]", "fill": "#eff6ff", "stroke": "#2563eb", "stroke_width": 2},

                    # Block 5: Load
                    {"id": "n_load", "type": "rectangle", "x": 900, "y": 90, "width": 150, "height": 75, "text": "Load (Rload)\n[Regulated Vout]", "fill": "#ecfdf5", "stroke": "#059669", "stroke_width": 2},

                    # Freewheeling Diode (Shunt)
                    {"id": "n_diode", "type": "ellipse", "x": 335, "y": 210, "width": 140, "height": 70, "text": "Schottky Diode (D1)\n[Freewheeling Path]", "fill": "#fffbeb", "stroke": "#d97706", "stroke_width": 2},

                    # Connectors
                    {"id": "arr_1", "type": "arrow", "x": 160, "y": 125, "width": 60, "height": 10, "from_id": "n_vin", "to_id": "n_sw", "stroke": "#2563eb"},
                    {"id": "arr_2", "type": "arrow", "x": 390, "y": 125, "width": 60, "height": 10, "from_id": "n_sw", "to_id": "n_ind", "stroke": "#2563eb"},
                    {"id": "arr_3", "type": "arrow", "x": 620, "y": 125, "width": 60, "height": 10, "from_id": "n_ind", "to_id": "n_cap", "stroke": "#2563eb"},
                    {"id": "arr_4", "type": "arrow", "x": 840, "y": 125, "width": 60, "height": 10, "from_id": "n_cap", "to_id": "n_load", "stroke": "#059669"},
                    {"id": "arr_5", "type": "arrow", "x": 340, "y": 165, "width": 40, "height": 45, "from_id": "n_sw", "to_id": "n_diode", "stroke": "#d97706", "label": "Switch Off"},

                    # Formula Sticky Note
                    {"id": "n_eq", "type": "sticky_note", "x": 0, "y": 210, "width": 260, "height": 160, "title": "⚡ Key Equations", "text": "• Vout ≈ D × Vin (CCM)\n• Duty Cycle: D = Ton / T\n• Inductor Ripple: ΔIL = (Vin - Vout)·D / (f·L)\n• Efficiency: η > 90%", "fill": "#fef08a", "stroke": "#ca8a04"},

                    # Component Annotations Sticky Note
                    {"id": "n_notes", "type": "sticky_note", "x": 540, "y": 210, "width": 300, "height": 160, "title": "🔍 Operation Phases", "text": "1. ON-State (Q1 Closed): Current ramps through L, charging C and powering load.\n2. OFF-State (Q1 Open): Inductor discharges through freewheeling diode D1, sustaining current.", "fill": "#dbeafe", "stroke": "#2563eb"}
                ]
            }

        # 2. Flowchart fallback
        elif "flowchart" in cmd_lower or "login" in cmd_lower or "shopping" in cmd_lower or "process" in cmd_lower:
            return {
                "summary": "Generated structured interactive flowchart with process nodes, decision points, and directed connectors.",
                "objects": [
                    {"id": "fc_title", "type": "text", "x": 0, "y": 0, "width": 500, "height": 40, "text": "System Flowchart Architecture", "font_size": 22, "fill": "#0f172a"},
                    {"id": "fc_start", "type": "ellipse", "x": 0, "y": 70, "width": 160, "height": 65, "text": "Start Session", "fill": "#dcfce7", "stroke": "#16a34a", "stroke_width": 2},
                    {"id": "fc_step1", "type": "rectangle", "x": 220, "y": 70, "width": 180, "height": 65, "text": "Receive Input / Credentials", "fill": "#eff6ff", "stroke": "#2563eb", "stroke_width": 2},
                    {"id": "fc_dec1", "type": "rectangle", "x": 460, "y": 60, "width": 180, "height": 85, "text": "Validate Request / Auth?\n[Check Database]", "fill": "#fef3c7", "stroke": "#d97706", "stroke_width": 2},
                    {"id": "fc_success", "type": "rectangle", "x": 700, "y": 70, "width": 180, "height": 65, "text": "Grant Access & Load Session", "fill": "#eff6ff", "stroke": "#2563eb", "stroke_width": 2},
                    {"id": "fc_end", "type": "ellipse", "x": 940, "y": 70, "width": 150, "height": 65, "text": "Complete / Ready", "fill": "#dcfce7", "stroke": "#16a34a", "stroke_width": 2},
                    {"id": "fc_retry", "type": "rectangle", "x": 460, "y": 200, "width": 180, "height": 65, "text": "Display Error & Rate Limit", "fill": "#fee2e2", "stroke": "#dc2626", "stroke_width": 2},

                    {"id": "arr_fc1", "type": "arrow", "x": 160, "y": 102, "width": 60, "height": 10, "from_id": "fc_start", "to_id": "fc_step1", "stroke": "#2563eb"},
                    {"id": "arr_fc2", "type": "arrow", "x": 400, "y": 102, "width": 60, "height": 10, "from_id": "fc_step1", "to_id": "fc_dec1", "stroke": "#2563eb"},
                    {"id": "arr_fc3", "type": "arrow", "x": 640, "y": 102, "width": 60, "height": 10, "from_id": "fc_dec1", "to_id": "fc_success", "stroke": "#16a34a", "label": "Valid"},
                    {"id": "arr_fc4", "type": "arrow", "x": 880, "y": 102, "width": 60, "height": 10, "from_id": "fc_success", "to_id": "fc_end", "stroke": "#16a34a"},
                    {"id": "arr_fc5", "type": "arrow", "x": 550, "y": 145, "width": 10, "height": 55, "from_id": "fc_dec1", "to_id": "fc_retry", "stroke": "#dc2626", "label": "Invalid"}
                ]
            }

        # 3. Mind map or Note Summary fallback
        elif "mind map" in cmd_lower or "brainstorm" in cmd_lower:
            return {
                "summary": "Generated Mind Map with central topic, radiating domain branches, and connecting vectors.",
                "objects": [
                    {"id": "mm_center", "type": "ellipse", "x": 300, "y": 120, "width": 200, "height": 80, "text": f"Core Concept:\n{command[:30]}", "fill": "#e0e7ff", "stroke": "#4f46e5", "stroke_width": 3},
                    {"id": "mm_b1", "type": "rectangle", "x": 30, "y": 20, "width": 180, "height": 70, "text": "Branch 1: Architecture\n• Data Pipeline\n• Service Layers", "fill": "#fef08a", "stroke": "#ca8a04"},
                    {"id": "mm_b2", "type": "rectangle", "x": 580, "y": 20, "width": 180, "height": 70, "text": "Branch 2: Algorithms\n• Deep Learning\n• Inference Optimization", "fill": "#dcfce7", "stroke": "#16a34a"},
                    {"id": "mm_b3", "type": "rectangle", "x": 30, "y": 220, "width": 180, "height": 70, "text": "Branch 3: Interaction\n• Canvas Pointer Events\n• Direct Manipulation", "fill": "#dbeafe", "stroke": "#2563eb"},
                    {"id": "mm_b4", "type": "rectangle", "x": 580, "y": 220, "width": 180, "height": 70, "text": "Branch 4: Evaluation\n• User Engagement\n• Latency Benchmarks", "fill": "#fce7f3", "stroke": "#db2777"},

                    {"id": "mm_arr1", "type": "arrow", "x": 210, "y": 60, "width": 90, "height": 60, "from_id": "mm_center", "to_id": "mm_b1", "stroke": "#4f46e5"},
                    {"id": "mm_arr2", "type": "arrow", "x": 500, "y": 60, "width": 80, "height": 60, "from_id": "mm_center", "to_id": "mm_b2", "stroke": "#4f46e5"},
                    {"id": "mm_arr3", "type": "arrow", "x": 210, "y": 180, "width": 90, "height": 40, "from_id": "mm_center", "to_id": "mm_b3", "stroke": "#4f46e5"},
                    {"id": "mm_arr4", "type": "arrow", "x": 500, "y": 180, "width": 80, "height": 40, "from_id": "mm_center", "to_id": "mm_b4", "stroke": "#4f46e5"}
                ]
            }

        # 4. General synthesis / summary / comparison fallback
        else:
            return {
                "summary": f"Synthesized structured whiteboard notes and action plan for: {command[:40]}",
                "objects": [
                    {"id": "sum_title", "type": "text", "x": 0, "y": 0, "width": 550, "height": 40, "text": f"Whiteboard Analysis: {command[:35]}", "font_size": 22, "fill": "#0f172a"},
                    {"id": "card_1", "type": "sticky_note", "x": 0, "y": 60, "width": 240, "height": 200, "title": "📌 Key Insights", "text": "• Core mechanics broken into discrete spatial stages.\n• Immediate direct manipulation on canvas.\n• Integrated contextual intelligence.", "fill": "#fef08a", "stroke": "#ca8a04"},
                    {"id": "card_2", "type": "sticky_note", "x": 270, "y": 60, "width": 240, "height": 200, "title": "💡 Technical Details", "text": "• Decoupled provider interface.\n• Schema-validated object generation.\n• Non-blocking asynchronous interaction.", "fill": "#dbeafe", "stroke": "#2563eb"},
                    {"id": "card_3", "type": "sticky_note", "x": 540, "y": 60, "width": 240, "height": 200, "title": "🚀 Action Items", "text": "1. Verify connector bindings.\n2. Adjust spatial layout & alignment.\n3. Export board or continue editing.", "fill": "#dcfce7", "stroke": "#16a34a"}
                ]
            }

board_ai_service = BoardAIService()
